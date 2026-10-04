"""Tests for service/graph.py (Phase D): walking_pairs, commute_from_all_stops.

Spec: CONTRACT.md, section "Build-time: commute to campus (`service/graph.py`, Phase D)".

Every network here is hand-built so the right answer is obvious. Stops sit on a local grid
around (49.25, -123.0) given in METERS (north_m, east_m). Expected walking distances are
computed with the haversine below (R = 6,371,000 m); for points on the same meridian the
distance is exact (north offsets are converted with R * pi / 180 meters per degree).

Times: trips are written in minutes after 08:00 and stored as seconds (Int32), like the
parsed GTFS columns. Decision 8: only hops whose trip DEPARTS stop A in 07:00 <= t < 19:00
count, so every fixture below (08:00-09:06) is inside that window unless a test (see
TestDaytimeWindow) deliberately sets absolute clock times with `at()`. Expected commute (minutes) =
    ride seconds + (penalised boardings * board_penalty_s) + walk_m / walk_mps, all / 60,
then rounded to 1 decimal by the function. Tests compare against the unrounded value with
abs=0.051 and separately check that every returned value is already rounded.

Unless a test says otherwise: campus_radius_m=1000, transfer_m=250, board_penalty_s=300,
walk_mps=1.4. The campus stop C is 100 m north of the campus point (walk 100 / 1.4 s =
1.19 min); origins are kilometres away so no accidental walk links exist.
"""
from __future__ import annotations

import copy
import math
import time
import warnings

import numpy as np
import pandas as pd
import pytest

from service import graph
from service.graph import (
    BOARD_PENALTY_S,
    CAMPUS_RADIUS_M,
    TRANSFER_RADIUS_M,
    WALK_MPS,
    commute_from_all_stops,
    walking_pairs,
)

R_EARTH = 6_371_000.0
M_PER_DEG_LAT = R_EARTH * math.pi / 180  # ~111,194.9 m
LAT0, LON0 = 49.25, -123.0
CAMPUS = (LAT0, LON0)
BASE_S = 8 * 3600  # 08:00


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def pt(north_m: float, east_m: float = 0.0) -> tuple[float, float]:
    """Grid point -> (lat, lon). Pure north offsets are exact meters along the meridian."""
    lat = LAT0 + north_m / M_PER_DEG_LAT
    lon = LON0 + east_m / (M_PER_DEG_LAT * math.cos(math.radians(LAT0)))
    return lat, lon


def make_stops(spec: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """{stop_id: (north_m, east_m)} -> load_stops-shaped DataFrame."""
    rows = []
    for sid, (n, e) in spec.items():
        lat, lon = pt(n, e)
        rows.append((sid, f"Stop {sid}", lat, lon))
    df = pd.DataFrame(rows, columns=["stop_id", "stop_name", "stop_lat", "stop_lon"])
    return df.astype({"stop_id": str, "stop_name": str, "stop_lat": "float64", "stop_lon": "float64"})


def stops_latlon(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """[(stop_id, lat, lon)] -> load_stops-shaped DataFrame."""
    df = pd.DataFrame(
        [(s, f"Stop {s}", la, lo) for s, la, lo in rows],
        columns=["stop_id", "stop_name", "stop_lat", "stop_lon"],
    )
    return df.astype({"stop_id": str, "stop_name": str, "stop_lat": "float64", "stop_lon": "float64"})


def walk_min(stops: pd.DataFrame, a: str, b: str | tuple[float, float], mps: float = WALK_MPS) -> float:
    """Walking minutes from stop a to stop b (or to a (lat, lon) point)."""
    ra = stops.set_index("stop_id").loc[a]
    if isinstance(b, tuple):
        lat2, lon2 = b
    else:
        rb = stops.set_index("stop_id").loc[b]
        lat2, lon2 = rb.stop_lat, rb.stop_lon
    return haversine_m(ra.stop_lat, ra.stop_lon, lat2, lon2) / mps / 60


def call(stop, arr_min, dep_min=None, pickup="0", drop="0"):
    """One stop_times call; times in minutes after 08:00 (None = missing)."""
    return (stop, arr_min, arr_min if dep_min is None else dep_min, pickup, drop)


def at(h: int, m: int = 0, s: int = 0) -> float:
    """Absolute clock time -> the 'minutes after 08:00' that `call` expects (may be < 0)."""
    return (h * 3600 + m * 60 + s - BASE_S) / 60


def trip_rows(trip_id: str, *calls, seqs=None) -> list[dict]:
    """Rows for one trip; stop_sequence is 1..n as TEXT unless `seqs` given."""
    rows = []
    for i, (stop, arr, dep, pu, do) in enumerate(calls):
        rows.append({
            "trip_id": trip_id,
            "stop_id": stop,
            "stop_sequence": str(seqs[i] if seqs else i + 1),
            "arrival_s": None if arr is None else BASE_S + round(arr * 60),
            "departure_s": None if dep is None else BASE_S + round(dep * 60),
            "pickup_type": pu,
            "drop_off_type": do,
        })
    return rows


def make_stop_times(rows: list[dict], *, pickup_drop: bool = True) -> pd.DataFrame:
    cols = ["trip_id", "stop_id", "stop_sequence", "arrival_s", "departure_s"]
    if pickup_drop:
        cols += ["pickup_type", "drop_off_type"]
    df = pd.DataFrame(rows, columns=["trip_id", "stop_id", "stop_sequence", "arrival_s",
                                     "departure_s", "pickup_type", "drop_off_type"])
    df = df[cols]
    df = df.astype({"trip_id": str, "stop_id": str, "stop_sequence": str})
    df["arrival_s"] = pd.array(df["arrival_s"].tolist(), dtype="Int32")
    df["departure_s"] = pd.array(df["departure_s"].tolist(), dtype="Int32")
    return df


def make_trips(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    """[(trip_id, route_id, service_id, direction_id)] -> load_trips-shaped DataFrame."""
    return pd.DataFrame(rows, columns=["trip_id", "route_id", "service_id", "direction_id"]).astype(str)


def run(stops, st_rows, trips, *, service_ids=frozenset({"WK"}), pickup_drop=True, **kw):
    st = make_stop_times(st_rows, pickup_drop=pickup_drop)
    routes = pd.DataFrame(columns=["route_id", "route_short_name", "route_long_name"])
    res = commute_from_all_stops(stops, st, make_trips(trips), routes, set(service_ids), CAMPUS, **kw)
    return {k: v["minutes"] for k, v in res.items()}


def approx(minutes: float):
    return pytest.approx(minutes, abs=0.051)


# Standard layout: C at campus (100 m north of the point), others kilometres east.
STD = {
    "A": (0, 8000),
    "B": (0, 5000),
    "M": (0, 4000),
    "C": (100, 0),
}


def test_constants_match_contract():
    assert (CAMPUS_RADIUS_M, TRANSFER_RADIUS_M, BOARD_PENALTY_S, WALK_MPS) == (1000, 250, 300, 1.4)


# ===========================================================================
# walking_pairs
# ===========================================================================
def pairs_dict(pairs) -> dict[tuple[str, str], float]:
    d = {(a, b): m for a, b, m in pairs}
    assert len(d) == len(pairs), "each ordered pair must appear exactly once"
    return d


class TestWalkingPairs:
    def test_within_and_beyond(self):
        """A at origin, B 200 m north, C 300 m north, D 1 km east.
        max_m=250: only A<->B (200 m) and B<->C (100 m); A-C (300 m) and D excluded."""
        stops = make_stops({"A": (0, 0), "B": (200, 0), "C": (300, 0), "D": (0, 1000)})
        d = pairs_dict(walking_pairs(stops, 250))
        assert set(d) == {("A", "B"), ("B", "A"), ("B", "C"), ("C", "B")}
        assert d[("A", "B")] == pytest.approx(200.0, abs=0.5)
        assert d[("B", "C")] == pytest.approx(100.0, abs=0.5)

    def test_both_directions_same_distance(self):
        stops = make_stops({"A": (0, 0), "B": (120, 90)})
        d = pairs_dict(walking_pairs(stops, 250))
        assert set(d) == {("A", "B"), ("B", "A")}
        assert d[("A", "B")] == pytest.approx(d[("B", "A")], abs=1e-6)

    def test_distance_in_meters_matches_haversine(self):
        """Diagonal offsets: compare to the R=6371000 haversine to +-0.5 m."""
        stops = make_stops({"A": (0, 0), "B": (150, 150), "C": (-80, 60), "E": (30, -170)})
        d = pairs_dict(walking_pairs(stops, 250))
        idx = stops.set_index("stop_id")
        assert d, "expected some pairs"
        for (a, b), m in d.items():
            exp = haversine_m(idx.loc[a].stop_lat, idx.loc[a].stop_lon,
                              idx.loc[b].stop_lat, idx.loc[b].stop_lon)
            assert m == pytest.approx(exp, abs=0.5), (a, b)
            assert exp <= 250
        # every pair within 250 m by haversine must be present
        ids = list(idx.index)
        for a in ids:
            for b in ids:
                if a != b:
                    exp = haversine_m(idx.loc[a].stop_lat, idx.loc[a].stop_lon,
                                      idx.loc[b].stop_lat, idx.loc[b].stop_lon)
                    assert ((a, b) in d) == (exp <= 250), (a, b, exp)

    def test_exactly_at_max_is_included(self):
        """<= max_m: max_m set to the pair's own distance (+1 micrometre for float noise)."""
        stops = make_stops({"A": (0, 0), "B": (173.2, 0)})
        dist = haversine_m(*pt(0, 0), *pt(173.2, 0))
        assert set(pairs_dict(walking_pairs(stops, dist + 1e-6))) == {("A", "B"), ("B", "A")}
        assert walking_pairs(stops, dist - 0.01) == []

    def test_no_self_pairs(self):
        stops = make_stops({"A": (0, 0), "B": (10, 0), "C": (20, 0)})
        d = pairs_dict(walking_pairs(stops, 250))
        assert all(a != b for a, b in d)
        assert len(d) == 6  # 3 stops, all within 250 m: 3 * 2 ordered pairs

    def test_distinct_stops_at_same_point_pair_with_zero(self):
        """Two different stop_ids at identical coordinates are distinct stops: 0 m apart."""
        stops = make_stops({"A": (0, 0), "B": (0, 0)})
        d = pairs_dict(walking_pairs(stops, 250))
        assert set(d) == {("A", "B"), ("B", "A")}
        assert d[("A", "B")] == pytest.approx(0.0, abs=0.5)

    def test_empty_input(self):
        assert walking_pairs(make_stops({}), 250) == []

    def test_single_stop(self):
        assert walking_pairs(make_stops({"A": (0, 0)}), 250) == []

    def test_types_and_ids_stay_text(self):
        """'0042' must not become 42; alphanumeric ids kept; distances plain float."""
        stops = make_stops({"0042": (0, 0), "WFSCS": (50, 0), "7": (100, 0)})
        pairs = walking_pairs(stops, 250)
        assert isinstance(pairs, list)
        assert {a for a, _, _ in pairs} == {"0042", "WFSCS", "7"}
        for p in pairs:
            assert isinstance(p, tuple) and len(p) == 3
            a, b, m = p
            assert type(a) is str and type(b) is str
            assert type(m) is float

    def test_does_not_mutate_input(self):
        stops = make_stops({"A": (0, 0), "B": (100, 0)})
        before = stops.copy(deep=True)
        walking_pairs(stops, 250)
        pd.testing.assert_frame_equal(stops, before)

    # --- decision 11 ------------------------------------------------------
    def test_non_finite_coordinates_ignored_without_warnings(self):
        """Rows with NaN lat or inf lon pair with nothing (and raise no RuntimeWarning);
        A <-> B (100 m) unchanged."""
        a, b = pt(0, 0), pt(100, 0)
        stops = stops_latlon([
            ("A", *a), ("B", *b),
            ("NANLAT", float("nan"), a[1]),
            ("INFLON", a[0], float("inf")),
        ])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d = pairs_dict(walking_pairs(stops, 250))
        assert set(d) == {("A", "B"), ("B", "A")}
        assert d[("A", "B")] == pytest.approx(100.0, abs=0.5)

    def test_rows_sharing_a_stop_id_never_pair_with_each_other(self):
        """Two rows 'a' 100 m apart, 'b' 50 m from both: no ('a', 'a', ...) pair, but a <-> b
        is present (whether once or per row is not specified)."""
        stops = stops_latlon([("a", *pt(0, 0)), ("a", *pt(100, 0)), ("b", *pt(50, 0))])
        pairs = walking_pairs(stops, 250)
        assert not any(x == y for x, y, _ in pairs)
        keys = {(x, y) for x, y, _ in pairs}
        assert keys == {("a", "b"), ("b", "a")}
        assert all(m == pytest.approx(50.0, abs=0.5) for _, _, m in pairs)

    def test_matches_brute_force_on_random_stops(self):
        """3,000 random stops in a 10 km box, max_m=250: exactly the brute-force pair set
        (catches grid-bucket boundary bugs)."""
        rng = np.random.default_rng(7)
        n = 3000
        lat = LAT0 + rng.uniform(0, 10_000 / M_PER_DEG_LAT, n)
        lon = LON0 + rng.uniform(0, 10_000 / 72_600, n)
        ids = [f"s{i}" for i in range(n)]
        stops = stops_latlon(list(zip(ids, lat, lon)))

        expected = set()
        la, lo = np.radians(lat), np.radians(lon)
        for i0 in range(0, n, 500):
            sl = slice(i0, i0 + 500)
            dp = la[None, :] - la[sl, None]
            dl = lo[None, :] - lo[sl, None]
            a = np.sin(dp / 2) ** 2 + np.cos(la[sl, None]) * np.cos(la[None, :]) * np.sin(dl / 2) ** 2
            dist = 2 * R_EARTH * np.arcsin(np.sqrt(a))
            ii, jj = np.nonzero(dist <= 250)
            for i, j in zip(ii + i0, jj):
                if i != j:
                    expected.add((ids[i], ids[j]))

        got = pairs_dict(walking_pairs(stops, 250))
        # tolerate pairs within 1 mm of the cut-off only (float noise)
        diff = set(got) ^ expected
        for a, b in diff:
            i, j = int(a[1:]), int(b[1:])
            assert abs(haversine_m(lat[i], lon[i], lat[j], lon[j]) - 250) < 1e-3, (a, b)
        assert len(expected) > 100, "fixture sanity: should have many pairs"

    def test_performance_real_sized_network(self):
        """8,729 stops in a 50 km box, max_m=250 must finish < 2 s (not O(n^2) Python)."""
        rng = np.random.default_rng(42)
        n = 8729
        lat = LAT0 + rng.uniform(0, 50_000 / M_PER_DEG_LAT, n)
        lon = LON0 + rng.uniform(0, 50_000 / 72_600, n)
        stops = stops_latlon([(str(i), a, b) for i, (a, b) in enumerate(zip(lat, lon))])
        t0 = time.perf_counter()
        pairs = walking_pairs(stops, 250)
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"walking_pairs took {elapsed:.2f}s"
        assert all(m <= 250 + 1e-6 for _, _, m in pairs)


# ===========================================================================
# commute_from_all_stops
# ===========================================================================
EMPTY_TRIPS: list = []


class TestCampusWalk:
    def test_stop_500m_from_campus_walks(self):
        """S is exactly 500 m north of campus, no transit at all: 500 / 1.4 / 60 = 5.95 -> 6.0.
        FAR (1500 m) has no transit and is beyond the 1000 m radius -> absent."""
        stops = make_stops({"S": (500, 0), "FAR": (1500, 0)})
        got = run(stops, [], EMPTY_TRIPS)
        assert got == {"S": 6.0}

    def test_stop_exactly_on_campus_is_zero(self):
        stops = make_stops({"Z": (0, 0)})
        assert run(stops, [], EMPTY_TRIPS) == {"Z": 0.0}

    def test_campus_radius_parameter(self):
        """Same 500 m stop: radius 400 -> absent, radius 600 -> present."""
        stops = make_stops({"S": (500, 0)})
        assert run(stops, [], EMPTY_TRIPS, campus_radius_m=400) == {}
        assert run(stops, [], EMPTY_TRIPS, campus_radius_m=600) == {"S": 6.0}

    def test_walk_speed_parameter(self):
        """walk_mps=1.0: 500 m -> 500 s = 8.33 -> 8.3 min."""
        stops = make_stops({"S": (500, 0)})
        assert run(stops, [], EMPTY_TRIPS, walk_mps=1.0) == {"S": 8.3}


class TestNoWalkOnlyJourneys:
    def test_walk_to_unserved_campus_stop_is_not_a_journey(self):
        """Decision 4: no walk-only journeys except the direct campus walk.
        K is 900 m from campus (inside radius); OUT is 1100 m (outside), 200 m from K.
        K has no service. OUT -> K (walk 200 m) -> campus is NOT allowed: OUT absent.
        K walks directly: 900 / 1.4 / 60 = 10.7."""
        stops = make_stops({"K": (900, 0), "OUT": (1100, 0)})
        got = run(stops, [], EMPTY_TRIPS)
        assert got == {"K": round(900 / 1.4 / 60, 1)}


class TestDaytimeWindow:
    """Decision 8: a ride hop counts only if the trip leaves A at 07:00 <= departure_s < 19:00."""

    @pytest.mark.parametrize(
        "dep, counts",
        [
            ((6, 59, 59), False),
            ((7, 0, 0), True),
            ((18, 59, 59), True),
            ((19, 0, 0), False),
        ],
        ids=["06:59:59-ignored", "07:00:00-counts", "18:59:59-counts", "19:00:00-ignored"],
    )
    def test_departure_window_boundaries(self, dep, counts):
        """Single trip A -> C taking 10 min, leaving A at `dep`. Counted: A = 10 + 1.19 = 11.2;
        ignored: A has no other way -> absent. (C walks to campus either way.)"""
        stops = make_stops(STD)
        d = at(*dep)
        rows = trip_rows("T1", call("A", d), call("C", d + 10))
        got = run(stops, rows, [("T1", "R1", "WK", "0")])
        w = walk_min(stops, "C", CAMPUS)
        if counts:
            assert got["A"] == approx(10 + w)
        else:
            assert "A" not in got
        assert got["C"] == approx(w)

    def test_night_only_pattern_adds_no_edges(self):
        """R2 runs only at 25:00 (1 AM NightBus): D -> C in 5 min. No daytime hop -> D absent.
        R1 (daytime) A -> C 10 min is unaffected: A = 11.2."""
        stops = make_stops({**STD, "D": (0, -6000)})
        rows = (trip_rows("T1", call("A", 0), call("C", 10))
                + trip_rows("N1", call("D", at(25)), call("C", at(25) + 5))
                + trip_rows("N2", call("D", at(26)), call("C", at(26) + 5)))
        trips = [("T1", "R1", "WK", "0"), ("N1", "R2", "WK", "0"), ("N2", "R2", "WK", "0")]
        got = run(stops, rows, trips)
        assert "D" not in got
        assert got["A"] == approx(10 + walk_min(stops, "C", CAMPUS))

    def test_night_trip_does_not_affect_daytime_median(self):
        """Same pattern A -> C: daytime trips take 10, 12, 14 min; a 5-min trip at 25:00.
        Median of daytime only = 12 (with the night trip it would be 11). A = 12 + 1.19 = 13.2."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("C", 10))
                + trip_rows("T2", call("A", 60), call("C", 72))
                + trip_rows("T3", call("A", 120), call("C", 134))
                + trip_rows("N1", call("A", at(25)), call("C", at(25) + 5)))
        trips = [(tid, "R1", "WK", "0") for tid in ("T1", "T2", "T3", "N1")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(12 + walk_min(stops, "C", CAMPUS))

    def test_window_is_per_hop_departure(self):
        """One trip A 18:50 -> B 18:58 -> C 19:08. A->B leaves 18:50 (counts), B->C leaves
        18:58 (counts) -> A = 18 + 1.19 = 19.2 even though the bus reaches C after 19:00.
        A second trip X 18:55 -> Y 19:00 -> C 19:10: Y->C leaves at 19:00 -> ignored, so Y
        and X cannot reach campus (absent)."""
        stops = make_stops({**STD, "X": (0, 12000), "Y": (0, 10000)})
        rows = (trip_rows("T1", call("A", at(18, 50)), call("B", at(18, 58)), call("C", at(19, 8)))
                + trip_rows("T2", call("X", at(18, 55)), call("Y", at(19)), call("C", at(19, 10))))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0")]
        got = run(stops, rows, trips)
        w = walk_min(stops, "C", CAMPUS)
        assert got["A"] == approx(18 + w)
        assert got["B"] == approx(10 + w)
        assert "X" not in got and "Y" not in got


class TestDirectRide:
    TRIPS = [("T1", "R1", "WK", "0")]

    def test_first_boarding_is_free(self):
        """A -> B -> C on one trip (0, 10, 20 min). C is 100 m from campus (1.19 min walk).
        A = 20 + 1.19 = 21.2 (NOT 26.2: the first boarding has no penalty).
        B = 10 + 1.19 = 11.2; C = 1.2 (walk only)."""
        stops = make_stops(STD)
        rows = trip_rows("T1", call("A", 0), call("B", 10), call("C", 20))
        got = run(stops, rows, self.TRIPS)
        w = walk_min(stops, "C", CAMPUS)
        assert got["A"] == approx(20 + w)
        assert got["B"] == approx(10 + w)
        assert got["C"] == approx(w)
        assert "M" not in got  # unserved, nothing within walking distance

    def test_hop_uses_departure_then_arrival(self):
        """A arr 0 / dep 1, C arr 12 / dep 14: hop = C.arrival - A.departure = 11 min.
        A = 11 + 1.19 = 12.2."""
        stops = make_stops(STD)
        rows = trip_rows("T1", call("A", 0, 1), call("C", 12, 14))
        got = run(stops, rows, self.TRIPS)
        assert got["A"] == approx(11 + walk_min(stops, "C", CAMPUS))

    def test_median_hop_time_over_trips(self):
        """Three trips of the same pattern A -> C taking 4, 6, 8 min: median 6.
        A = 6 + 1.19 = 7.2."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("C", 8))
                + trip_rows("T2", call("A", 30), call("C", 34))
                + trip_rows("T3", call("A", 60), call("C", 66)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "0"), ("T3", "R1", "WK", "0")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(6 + walk_min(stops, "C", CAMPUS))


class TestIgnoredData:
    def test_inactive_trips_ignored(self):
        """T1 (WK, active) A -> C 10 min; T2 (SAT, inactive) A -> C 2 min and D -> C.
        A = 10 + 1.19 = 11.2 (not 3.2); D only has Saturday service -> absent."""
        stops = make_stops({**STD, "D": (0, -6000)})
        rows = (trip_rows("T1", call("A", 0), call("C", 10))
                + trip_rows("T2", call("A", 0), call("C", 2))
                + trip_rows("T3", call("D", 0), call("C", 5)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "SAT", "0"), ("T3", "R2", "SAT", "0")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(10 + walk_min(stops, "C", CAMPUS))
        assert "D" not in got

    def test_missing_times_ignored(self):
        """T1 A -> C 10 min. T2 A (departure <NA>) -> C. If <NA> were treated as anything
        the median would move. A = 11.2. E's only hop has <NA> arrival -> E absent."""
        stops = make_stops({**STD, "E": (0, -6000)})
        rows = (trip_rows("T1", call("A", 0), call("C", 10))
                + trip_rows("T2", call("A", None, None), call("C", 3))
                + trip_rows("T3", call("E", 0), call("C", None, None)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "0"), ("T3", "R2", "WK", "0")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(10 + walk_min(stops, "C", CAMPUS))
        assert "E" not in got

    def test_negative_durations_ignored(self):
        """T1 A -> C 10 min, T2 A dep 30 -> C arr 28 (-2 min). Median of {10} = 10, not
        median {10, -2} = 4. A = 11.2. F's only hop is negative -> F absent."""
        stops = make_stops({**STD, "F": (0, -6000)})
        rows = (trip_rows("T1", call("A", 0), call("C", 10))
                + trip_rows("T2", call("A", 30), call("C", 28))
                + trip_rows("T3", call("F", 50), call("C", 45)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "0"), ("T3", "R2", "WK", "0")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(10 + walk_min(stops, "C", CAMPUS))
        assert "F" not in got


class TestStopSequence:
    def test_numeric_not_lexicographic_and_row_order_irrelevant(self):
        """Trip X(seq '1', 0 min) -> A(seq '9', 20) -> C(seq '10', 30); rows reversed.
        Numeric order: X -> A -> C, so A = 10 + 1.19 = 11.2 and X = 30 + 1.19 = 31.2.
        (Lexicographic '1' < '10' < '9' would give X -> C -> A and leave A unreachable.)"""
        stops = make_stops({"X": (0, 12000), **STD})
        rows = trip_rows("T1", call("X", 0), call("A", 20), call("C", 30), seqs=[1, 9, 10])
        rows = rows[::-1]
        got = run(stops, rows, [("T1", "R1", "WK", "0")])
        w = walk_min(stops, "C", CAMPUS)
        assert got["A"] == approx(10 + w)
        assert got["X"] == approx(30 + w)


class TestTransfers:
    def test_same_stop_transfer_costs_one_penalty(self):
        """R1: A -> M (10 min). R2: M -> C (10 min). Change at M costs 5 min once.
        A = 10 + 5 + 10 + 1.19 = 26.2. M = 10 + 1.19 = 11.2 (its first boarding is free)."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("M", 10))
                + trip_rows("T2", call("M", 20), call("C", 30)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0")]
        got = run(stops, rows, trips)
        w = walk_min(stops, "C", CAMPUS)
        assert got["A"] == approx(25 + w)
        assert got["M"] == approx(10 + w)

    def _walk_net(self, gap_m):
        stops = make_stops({"A": (0, 8000), "M1": (0, 4000), "M2": (gap_m, 4000), "C": (100, 0)})
        rows = (trip_rows("T1", call("A", 0), call("M1", 10))
                + trip_rows("T2", call("M2", 20), call("C", 30)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0")]
        return stops, rows, trips

    def test_walking_transfer_200m(self):
        """R1: A -> M1 (10). Walk M1 -> M2 = 200 m (2.38 min). R2: M2 -> C (10), +5 penalty.
        A = 10 + 2.38 + 5 + 10 + 1.19 = 28.6.
        M1 = 2.38 + 10 + 1.19 = 13.6 (walk then FIRST boarding: no penalty)."""
        stops, rows, trips = self._walk_net(200)
        got = run(stops, rows, trips)
        w = walk_min(stops, "C", CAMPUS)
        walk = 200 / 1.4 / 60
        assert got["A"] == approx(10 + walk + 5 + 10 + w)
        assert got["M1"] == approx(walk + 10 + w)
        assert got["M2"] == approx(10 + w)

    def test_no_transfer_beyond_transfer_m(self):
        """Same but M2 is 300 m away (> 250): A and M1 cannot reach campus -> absent."""
        stops, rows, trips = self._walk_net(300)
        got = run(stops, rows, trips)
        assert "A" not in got and "M1" not in got
        assert got["M2"] == approx(10 + walk_min(stops, "C", CAMPUS))

    def test_transfer_m_parameter(self):
        """M2 300 m away but transfer_m=350: A = 10 + 3.57 + 5 + 10 + 1.19 = 29.8."""
        stops, rows, trips = self._walk_net(300)
        got = run(stops, rows, trips, transfer_m=350)
        assert got["A"] == approx(10 + 300 / 1.4 / 60 + 5 + 10 + walk_min(stops, "C", CAMPUS))


class TestFirstLegWalk:
    def _net(self):
        # P --100 m-- O --100 m-- S ; S rides to C in 10 min. P-S = 200 m.
        stops = make_stops({"P": (-100, 4000), "O": (0, 4000), "S": (100, 4000), "C": (100, 0)})
        rows = trip_rows("T1", call("S", 0), call("C", 10))
        return stops, rows, [("T1", "R1", "WK", "0")]

    def test_walk_to_served_stop_then_free_boarding(self):
        """O has no service; S (100 m away) rides to C in 10 min.
        O = 1.19 (walk) + 10 + 1.19 = 12.4, no board penalty."""
        stops, rows, trips = self._net()
        got = run(stops, rows, trips)
        w = walk_min(stops, "C", CAMPUS)
        assert got["O"] == approx(100 / 1.4 / 60 + 10 + w)
        assert got["S"] == approx(10 + w)

    def test_only_one_walk_hop_before_first_boarding(self):
        """transfer_m=150: P -> O (100 m) -> S (100 m) needs TWO walk hops before boarding
        (P -> S is 200 m > 150) -> P absent. O still reachable with one hop."""
        stops, rows, trips = self._net()
        got = run(stops, rows, trips, transfer_m=150)
        assert "P" not in got
        assert got["O"] == approx(100 / 1.4 / 60 + 10 + walk_min(stops, "C", CAMPUS))


class TestReviewerCases:
    def test_ghost_stop_in_stop_times_is_never_in_result(self):
        """Decision 10: stop_times uses 'GHOST' (not in stops) on a daytime trip to campus.
        No KeyError, 'GHOST' absent, and other results identical to the network without it."""
        stops = make_stops(STD)
        base_rows = trip_rows("T1", call("A", 0), call("B", 10), call("C", 20))
        ghost_rows = trip_rows("T2", call("GHOST", 0), call("C", 7))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0")]
        got = run(stops, base_rows + ghost_rows, trips)
        assert "GHOST" not in got
        assert got == run(stops, base_rows, trips[:1])

    def test_walk_then_two_boardings_costs_one_penalty(self):
        """O unserved; S 100 m away. R1 S -> M (10), R2 M -> C (10).
        O = 1.19 walk + 10 + 5 (second boarding only) + 10 + 1.19 = 27.4 (not 32.4)."""
        stops = make_stops({"O": (0, 4000), "S": (100, 4000), "M": (0, 8000), "C": (100, 0)})
        rows = (trip_rows("T1", call("S", 0), call("M", 10))
                + trip_rows("T2", call("M", 20), call("C", 30)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0")]
        got = run(stops, rows, trips)
        w = walk_min(stops, "C", CAMPUS)
        assert got["O"] == approx(100 / 1.4 / 60 + 10 + 5 + 10 + w)
        assert got["S"] == approx(10 + 5 + 10 + w)

    def test_walk_to_no_pickup_stop_is_not_a_first_boarding(self):
        """O unserved; S 100 m away is served only by a trip with pickup_type '1' at S.
        Neither O nor S can board anything -> both absent."""
        stops = make_stops({"O": (0, 4000), "S": (100, 4000), "C": (100, 0)})
        rows = trip_rows("T1", call("S", 0, pickup="1"), call("C", 10))
        got = run(stops, rows, [("T1", "R1", "WK", "0")])
        assert "O" not in got and "S" not in got
        assert got["C"] == approx(walk_min(stops, "C", CAMPUS))


class TestPickupDropoff:
    def test_no_pickup_means_cannot_start_there(self):
        """A -> B -> C, but pickup_type '1' at A on the only trip: A absent, B = 11.2."""
        stops = make_stops(STD)
        rows = trip_rows("T1", call("A", 0, pickup="1"), call("B", 10), call("C", 20))
        got = run(stops, rows, [("T1", "R1", "WK", "0")])
        assert "A" not in got
        assert got["B"] == approx(10 + walk_min(stops, "C", CAMPUS))

    def test_pickup_allowed_if_any_trip_of_pattern_allows(self):
        """T1 forbids pickup at A, T2 (same pattern) allows it: A boardable. Both 10 min."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0, pickup="1"), call("C", 10))
                + trip_rows("T2", call("A", 30), call("C", 40)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "0")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(10 + walk_min(stops, "C", CAMPUS))

    @pytest.mark.parametrize("pickup", ["0", "", "2", "3"])
    def test_other_pickup_types_allow_boarding(self, pickup):
        stops = make_stops(STD)
        rows = trip_rows("T1", call("A", 0, pickup=pickup), call("C", 10))
        got = run(stops, rows, [("T1", "R1", "WK", "0")])
        assert got["A"] == approx(10 + walk_min(stops, "C", CAMPUS))

    @pytest.mark.parametrize("drop, expected_extra", [("1", "ride_on"), ("0", "alight")])
    def test_no_drop_off_at_campus_stop_rides_on(self, drop, expected_extra):
        """Campus point at C (0 m), D 800 m north (still within 1000 m).
        Trip A(0) -> C(10) -> D(15). drop_off_type '1' at C: must ride on to D:
        A = 15 + 800/1.4/60 (9.52) = 24.5. With drop '0': A = 10 + 0 = 10.0.
        C itself is at campus either way: 0.0."""
        stops = make_stops({"A": (0, 8000), "C": (0, 0), "D": (800, 0)})
        rows = trip_rows("T1", call("A", 0), call("C", 10, drop=drop), call("D", 15))
        got = run(stops, rows, [("T1", "R1", "WK", "0")])
        if expected_extra == "ride_on":
            assert got["A"] == approx(15 + 800 / 1.4 / 60)
        else:
            assert got["A"] == 10.0
        assert got["C"] == 0.0

    def test_missing_pickup_and_drop_columns_mean_allowed(self):
        """Direct-ride network without pickup_type/drop_off_type columns: A = 21.2."""
        stops = make_stops(STD)
        rows = trip_rows("T1", call("A", 0), call("B", 10), call("C", 20))
        got = run(stops, rows, [("T1", "R1", "WK", "0")], pickup_drop=False)
        w = walk_min(stops, "C", CAMPUS)
        assert got["A"] == approx(20 + w)
        assert got["B"] == approx(10 + w)


class TestPatterns:
    def test_opposite_direction_is_not_a_free_continuation(self):
        """Route R1 direction 0 runs A -> M; R1 direction 1 runs M -> C. Different patterns,
        so continuing costs a boarding penalty: A = 10 + 5 + 10 + 1.19 = 26.2 (not 21.2)."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("M", 10))
                + trip_rows("T2", call("M", 30), call("C", 40)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "1")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(25 + walk_min(stops, "C", CAMPUS))

    def test_same_pattern_hops_chain_without_penalty(self):
        """Pattern = (route, direction): hops from two trips of R1/0 (A -> M, M -> C) chain
        as one ride with no penalty: A = 10 + 10 + 1.19 = 21.2."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("M", 10))
                + trip_rows("T2", call("M", 30), call("C", 40)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "0")]
        got = run(stops, rows, trips)
        assert got["A"] == approx(20 + walk_min(stops, "C", CAMPUS))

    @pytest.mark.parametrize(
        "penalty_s, expected_ride",
        [
            (0, 20),      # transfer path 10 + 0 + 10 = 20 beats direct 40
            (300, 25),    # 10 + 5 + 10 = 25 beats direct 40
            (1800, 40),   # 10 + 30 + 10 = 50 loses to direct 40
        ],
    )
    def test_picks_cheapest_of_direct_vs_transfer(self, penalty_s, expected_ride):
        """R1 direct A -> C in 40 min. R2 A -> M (10) + R3 M -> C (10) with one transfer."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("C", 40))
                + trip_rows("T2", call("A", 0), call("M", 10))
                + trip_rows("T3", call("M", 20), call("C", 30)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0"), ("T3", "R3", "WK", "0")]
        got = run(stops, rows, trips, board_penalty_s=penalty_s)
        w = walk_min(stops, "C", CAMPUS)
        assert got["A"] == approx(expected_ride + w)
        assert got["M"] == approx(10 + w)


class TestResultContract:
    def _net(self, ids=("A", "B", "C")):
        a, b, c = ids
        stops = make_stops({a: (0, 8000), b: (0, 5000), c: (100, 0), "LONE": (0, -9000)})
        rows = (trip_rows("T1", call(a, 0), call(b, 7), call(c, 13))
                + trip_rows("T2", call(a, 20), call(b, 26), call(c, 35)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R1", "WK", "0")]
        return stops, rows, trips

    def test_plain_float_rounded_str_keys(self):
        stops, rows, trips = self._net()
        got = run(stops, rows, trips)
        assert type(got) is dict
        assert set(got) == {"A", "B", "C"}
        for k, v in got.items():
            assert type(k) is str
            assert type(v) is float, f"{k}: {type(v)}"
            assert v == round(v, 1)
            assert math.isfinite(v) and v >= 0

    def test_ids_stay_text(self):
        stops, rows, trips = self._net(ids=("0042", "007", "WFSCS"))
        got = run(stops, rows, trips)
        assert set(got) == {"0042", "007", "WFSCS"}

    def test_keys_subset_of_stops(self):
        stops, rows, trips = self._net()
        got = run(stops, rows, trips)
        assert set(got) <= set(stops["stop_id"])

    def test_deterministic_and_row_order_independent(self):
        stops, rows, trips = self._net()
        first = run(stops, rows, trips)
        second = run(stops, rows, trips)
        shuffled = run(stops.iloc[::-1].reset_index(drop=True), rows[::-1], trips[::-1])
        assert first == second == shuffled

    def test_inputs_not_mutated(self):
        stops, rows, trips = self._net()
        st = make_stop_times(rows)
        tr = make_trips(trips)
        sids = {"WK"}
        routes = pd.DataFrame(columns=["route_id", "route_short_name", "route_long_name"])
        before = (stops.copy(deep=True), st.copy(deep=True), tr.copy(deep=True), copy.deepcopy(sids))
        commute_from_all_stops(stops, st, tr, routes, sids, CAMPUS)
        pd.testing.assert_frame_equal(stops, before[0])
        pd.testing.assert_frame_equal(st, before[1])
        pd.testing.assert_frame_equal(tr, before[2])
        assert sids == before[3]

    def test_empty_service_ids_only_walkers(self):
        """No active service: only stops within the campus radius remain (C, walk only)."""
        stops, rows, trips = self._net()
        got = run(stops, rows, trips, service_ids=frozenset())
        assert got == {"C": round(walk_min(stops, "C", CAMPUS), 1)}

    def test_uses_module_constants_as_defaults(self):
        """Defaults equal the module constants (spot check via board penalty)."""
        stops = make_stops(STD)
        rows = (trip_rows("T1", call("A", 0), call("M", 10))
                + trip_rows("T2", call("M", 20), call("C", 30)))
        trips = [("T1", "R1", "WK", "0"), ("T2", "R2", "WK", "0")]
        assert run(stops, rows, trips) == run(stops, rows, trips, board_penalty_s=graph.BOARD_PENALTY_S,
                                               campus_radius_m=graph.CAMPUS_RADIUS_M,
                                               transfer_m=graph.TRANSFER_RADIUS_M,
                                               walk_mps=graph.WALK_MPS)
