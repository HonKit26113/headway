"""Tests for service/transit.py (Phase E runtime loader), from CONTRACT.md
"Runtime: service/transit.py (Phase E)".

Every test writes its own tiny artifact set into tmp_path and calls transit.load(tmp).
Module state is global, so an autouse fixture calls the public transit.reset() (T5) at
teardown; importlib.reload is never used.
Real-data tests (@pytest.mark.real) only READ backend/data/; nothing ever writes there.
"""
from __future__ import annotations

import builtins
import io
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest

import config
import service.transit as transit

BACKEND = Path(__file__).resolve().parent.parent
REAL_DATA = BACKEND / "data"

R_EARTH = 6371000.0
M_PER_DEG_LAT = R_EARTH * math.pi / 180.0


def hav(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def lon_offset(lat: float, meters: float) -> float:
    """Degrees of longitude for `meters` due east at `lat` (exact under hav)."""
    # solve hav(lat, 0, lat, d) == meters
    c = meters / R_EARTH
    s = math.sin(c / 2) / math.cos(math.radians(lat))
    return math.degrees(2 * math.asin(s))


# Origin and stops at known distances.
O_LAT, O_LON = 49.25, -123.10
STOPS = {
    "A": ["Alpha St @ Origin", O_LAT, O_LON],                                  # 0 m
    "T-b": ["Tie North", O_LAT + 100 / M_PER_DEG_LAT, O_LON],                  # 100 m (inserted first)
    "T-a": ["Tie South", O_LAT - 100 / M_PER_DEG_LAT, O_LON],                  # 100 m, wins the tie
    "D": ["Delta Ave", O_LAT, O_LON + lon_offset(O_LAT, 900)],                 # 900 m
    "E": ["Echo Rd", O_LAT, O_LON - lon_offset(O_LAT, 1500)],                  # 1500 m
    "F": ["Foxtrot Way", O_LAT + 2500 / M_PER_DEG_LAT, O_LON],                 # 2500 m
}
STATS = {
    "A": {"headway_min": 4.5, "departures_per_hour": 13.3, "trips_per_day": 160,
          "last_departure_min": 1510, "last_departure_label": "1:10 AM", "late_trips_after_23": 7},
    "T-b": {"headway_min": None, "departures_per_hour": 0.0, "trips_per_day": 3,
            "last_departure_min": 1093, "last_departure_label": "6:13 PM", "late_trips_after_23": 0},
    "D": {"headway_min": 15.0, "departures_per_hour": 4.0, "trips_per_day": 60,
          "last_departure_min": 1380, "last_departure_label": "11:00 PM", "late_trips_after_23": 0},
}
COMMUTE = {
    "sfu": {"A": 45.5, "T-b": 50.0, "D": 52.3},
    "ubc": {"A": 70.2},
    "bcit": {"A": 12.0, "T-a": 14.3},
}
FEED_VERSION = "TESTFEED_20261002"
SERVICE_DATE = "20261007"


def write_set(d: Path, *, stops=None, stats=None, commute=None, campuses=None) -> Path:
    """Write a COMPLETE artifact set (manifest last, like build_artifacts)."""
    d.mkdir(parents=True, exist_ok=True)
    stops = STOPS if stops is None else stops
    stats = STATS if stats is None else stats
    commute = COMMUTE if commute is None else commute
    campuses = ({k: list(v) for k, v in config.CAMPUS_COORDS.items()}
                if campuses is None else campuses)
    (d / "stops.json").write_text(json.dumps(stops, sort_keys=True))
    (d / "stop_stats.json").write_text(json.dumps(stats, sort_keys=True))
    for name in campuses:
        (d / f"commute_{name}.json").write_text(json.dumps(commute.get(name, {}), sort_keys=True))
    manifest = {
        "feed_version": FEED_VERSION,
        "feed_start": "20260907",
        "feed_end": "20270103",
        "service_date": SERVICE_DATE,
        "source_sha256": "0" * 64,
        "built_at": "2026-10-03T00:00:00+00:00",
        "campuses": campuses,
        "counts": {"stops": len(stops), "stop_stats": len(stats),
                   "trips_on_service_date": 1,
                   "commute": {n: len(commute.get(n, {})) for n in campuses}},
    }
    (d / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    return d


def fallback_commute(stop_id: str, campus: str, stops=STOPS) -> float:
    _, lat, lon = stops[stop_id]
    clat, clon = config.CAMPUS_COORDS[campus]
    return round(hav(lat, lon, clat, clon) / 1000 / transit.FALLBACK_KMH * 60, 1)


@pytest.fixture(autouse=True)
def restore_transit_state():
    """Never leak module state between tests: back to 'never loaded' at teardown."""
    yield
    transit.reset()


@pytest.fixture
def complete(tmp_path) -> Path:
    """Write a complete set; each test calls transit.load(complete) itself."""
    return write_set(tmp_path / "complete")


def ids(results):
    return [s.stop_id for s, _ in results]


# ---------------------------------------------------------------- complete set

class TestCompleteSet:
    def test_data_status_complete(self, complete):
        transit.load(complete)
        st = transit.data_status()
        assert st == {
            "gtfs_loaded": True,
            "fallback": False,
            "feed_version": FEED_VERSION,
            "service_date": SERVICE_DATE,
            "stops": len(STOPS),
        }
        assert type(st["stops"]) is int

    def test_load_accepts_str_path(self, tmp_path):
        d = write_set(tmp_path / "s")
        transit.load(str(d))
        assert transit.data_status()["gtfs_loaded"] is True

    def test_stop_stats_exact_values_and_types(self, complete):
        transit.load(complete)
        s = transit.stop_stats("A")
        assert isinstance(s, transit.StopStats)
        assert s == transit.StopStats(
            headway_min=4.5, departures_per_hour=13.3, trips_per_day=160,
            last_departure_min=1510, last_departure_label="1:10 AM", late_trips_after_23=7)
        assert type(s.headway_min) is float
        assert type(s.departures_per_hour) is float
        assert type(s.trips_per_day) is int
        assert type(s.last_departure_min) is int
        assert type(s.last_departure_label) is str
        assert type(s.late_trips_after_23) is int

    def test_stop_stats_headway_none_and_zero_dph(self, complete):
        transit.load(complete)
        s = transit.stop_stats("T-b")
        assert s.headway_min is None
        assert s.departures_per_hour == 0.0 and type(s.departures_per_hour) is float

    def test_stop_stats_float_fields_from_int_json(self, tmp_path):
        stats = {"A": dict(STATS["A"], headway_min=5, departures_per_hour=12)}
        transit.load(write_set(tmp_path / "s", stats=stats))
        s = transit.stop_stats("A")
        assert s.headway_min == 5.0 and type(s.headway_min) is float
        assert s.departures_per_hour == 12.0 and type(s.departures_per_hour) is float

    def test_stop_stats_unknown_stop_none(self, complete):
        transit.load(complete)
        assert transit.stop_stats("NOPE") is None
        assert transit.stop_stats("") is None

    def test_stop_stats_known_stop_absent_from_stats_none(self, complete):
        transit.load(complete)
        assert "T-a" in STOPS and "T-a" not in STATS
        assert transit.stop_stats("T-a") is None

    @pytest.mark.parametrize("campus,stop_id,expected", [
        ("sfu", "A", 45.5), ("sfu", "T-b", 50.0), ("sfu", "D", 52.3),
        ("ubc", "A", 70.2), ("bcit", "A", 12.0), ("bcit", "T-a", 14.3),
    ])
    def test_commute_minutes_per_campus(self, complete, campus, stop_id, expected):
        transit.load(complete)
        v = transit.commute_minutes(stop_id, campus)
        assert v == expected
        assert type(v) is float

    def test_commute_minutes_int_json_is_float(self, tmp_path):
        transit.load(write_set(tmp_path / "s", commute={"sfu": {"A": 45}}))
        v = transit.commute_minutes("A", "sfu")
        assert v == 45.0 and type(v) is float

    def test_commute_minutes_unknown_stop_none(self, complete):
        transit.load(complete)
        assert transit.commute_minutes("NOPE", "sfu") is None

    def test_commute_minutes_unreachable_stop_none(self, complete):
        transit.load(complete)
        assert "E" in STOPS
        assert transit.commute_minutes("E", "sfu") is None
        assert transit.commute_minutes("T-b", "ubc") is None

    @pytest.mark.parametrize("campus", ["mit", "../x", "SFU", "", "commute_sfu"])
    def test_commute_minutes_bad_campus_value_error(self, complete, campus):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.commute_minutes("A", campus)


# ---------------------------------------------------------------- nearest_stops

class TestNearestStops:
    def test_every_stop_within_radius_closest_first_ties_by_id(self, complete):
        transit.load(complete)
        res = transit.nearest_stops(O_LAT, O_LON, radius_m=1000)
        assert ids(res) == ["A", "T-a", "T-b", "D"]

    def test_walk_m_meters_matches_haversine(self, complete):
        transit.load(complete)
        res = transit.nearest_stops(O_LAT, O_LON, radius_m=2000)
        for stop, walk in res:
            _, lat, lon = STOPS[stop.stop_id]
            assert walk == pytest.approx(hav(O_LAT, O_LON, lat, lon), abs=0.5)
        walks = dict((s.stop_id, w) for s, w in res)
        assert walks["A"] == pytest.approx(0.0, abs=0.5)
        assert walks["D"] == pytest.approx(900, abs=0.5)
        assert walks["E"] == pytest.approx(1500, abs=0.5)

    def test_sorted_by_distance(self, complete):
        transit.load(complete)
        q_lat, q_lon = O_LAT + 0.003, O_LON - 0.004
        res = transit.nearest_stops(q_lat, q_lon, radius_m=2000)
        walks = [w for _, w in res]
        assert walks == sorted(walks)
        expected = sorted(
            (sid for sid, (_, la, lo) in STOPS.items() if hav(q_lat, q_lon, la, lo) <= 2000),
            key=lambda sid: (hav(q_lat, q_lon, STOPS[sid][1], STOPS[sid][2]), sid))
        assert ids(res) == expected

    def test_default_radius_is_1000(self, complete):
        transit.load(complete)
        assert transit.DEFAULT_RADIUS_M == 1000
        res = transit.nearest_stops(O_LAT, O_LON)
        assert ids(res) == ["A", "T-a", "T-b", "D"]
        assert res == transit.nearest_stops(O_LAT, O_LON, radius_m=1000)

    def test_small_radius_excludes_farther(self, complete):
        transit.load(complete)
        assert ids(transit.nearest_stops(O_LAT, O_LON, radius_m=150)) == ["A", "T-a", "T-b"]

    def test_radius_2000_includes_1500(self, complete):
        transit.load(complete)
        assert ids(transit.nearest_stops(O_LAT, O_LON, radius_m=2000)) == ["A", "T-a", "T-b", "D", "E"]

    @pytest.mark.parametrize("radius", [2001, 2499, 3000, 10_000, 1e9])
    def test_radius_clamped_to_max(self, complete, radius):
        transit.load(complete)
        assert transit.MAX_RADIUS_M == 2000
        res = transit.nearest_stops(O_LAT, O_LON, radius_m=radius)
        assert "F" not in ids(res)  # 2,500 m away: never returned
        assert ids(res) == ["A", "T-a", "T-b", "D", "E"]

    def test_radius_zero_only_exact_location(self, complete):
        transit.load(complete)
        res = transit.nearest_stops(O_LAT, O_LON, radius_m=0)
        assert ids(res) == ["A"]
        assert res[0][1] == pytest.approx(0.0, abs=1e-6)

    def test_radius_zero_off_stop_empty(self, complete):
        transit.load(complete)
        assert transit.nearest_stops(O_LAT + 0.0005, O_LON, radius_m=0) == []

    @pytest.mark.parametrize("radius", [-1, -500, -1e9])
    def test_negative_radius_empty(self, complete, radius):
        transit.load(complete)
        # query point ~50 m from A, so clamping to 0 yields nothing
        assert transit.nearest_stops(O_LAT + 50 / M_PER_DEG_LAT, O_LON, radius_m=radius) == []

    def test_no_stop_within_radius_empty(self, complete):
        transit.load(complete)
        assert transit.nearest_stops(49.0, -122.3, radius_m=1000) == []

    @pytest.mark.parametrize("k,expected", [
        (1, ["A"]), (2, ["A", "T-a"]), (3, ["A", "T-a", "T-b"]),
        (4, ["A", "T-a", "T-b", "D"]), (100, ["A", "T-a", "T-b", "D"]),
        (None, ["A", "T-a", "T-b", "D"]),
    ])
    def test_k_caps(self, complete, k, expected):
        transit.load(complete)
        assert ids(transit.nearest_stops(O_LAT, O_LON, radius_m=1000, k=k)) == expected

    @pytest.mark.parametrize("k", [0, -1, -100])
    def test_k_below_one_value_error(self, complete, k):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.nearest_stops(O_LAT, O_LON, k=k)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                     "49.25", True, False, None])
    def test_bad_lat_value_error(self, complete, bad):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.nearest_stops(bad, O_LON)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                     "-123.1", True, False, None])
    def test_bad_lon_value_error(self, complete, bad):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.nearest_stops(O_LAT, bad)

    def test_int_lat_lon_accepted(self, tmp_path):
        stops = {"Z": ["Integer Point", 49.0, -123.0]}
        transit.load(write_set(tmp_path / "s", stops=stops, stats={}, commute={}))
        assert ids(transit.nearest_stops(49, -123, radius_m=10)) == ["Z"]

    def test_returns_typed_tuples(self, complete):
        transit.load(complete)
        res = transit.nearest_stops(O_LAT, O_LON, radius_m=2000)
        assert isinstance(res, list) and res
        for item in res:
            assert isinstance(item, tuple) and len(item) == 2
            stop, walk = item
            assert isinstance(stop, transit.Stop)
            assert type(stop.stop_id) is str
            assert type(stop.name) is str
            assert isinstance(stop.lat, float) and not isinstance(stop.lat, bool)
            assert isinstance(stop.lon, float) and not isinstance(stop.lon, bool)
            assert isinstance(walk, float) and not isinstance(walk, bool)
            assert math.isfinite(walk) and walk >= 0
            name, lat, lon = STOPS[stop.stop_id]
            assert stop == transit.Stop(stop.stop_id, name, lat, lon)

    def test_performance_vectorized(self, tmp_path):
        stops = {}
        n = 0
        for i in range(90):
            for j in range(100):
                stops[f"S{n:05d}"] = [f"Stop {n}", 49.0 + i * 0.006, -123.3 + j * 0.01]
                n += 1
        assert len(stops) == 9000
        transit.load(write_set(tmp_path / "big", stops=stops, stats={}, commute={}))
        assert transit.data_status()["stops"] == 9000

        # correctness spot-check against brute force
        q = (49.25, -123.0)
        res = transit.nearest_stops(*q, radius_m=1000)
        brute = sorted((hav(*q, la, lo), sid) for sid, (_, la, lo) in stops.items()
                       if hav(*q, la, lo) <= 1000 - 0.01)
        assert {sid for _, sid in brute} <= set(ids(res))

        pts = [(49.01 + (i % 50) * 0.01, -123.29 + (i // 50) * 0.04) for i in range(1000)]
        transit.nearest_stops(*pts[0])  # warm-up
        t0 = time.perf_counter()
        for lat, lon in pts:
            transit.nearest_stops(lat, lon, radius_m=1000)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"1,000 calls took {elapsed:.2f}s (not vectorized?)"


# ---------------------------------------------------------------- fallback

def _rm(d: Path, name: str):
    (d / name).unlink()


def _corrupt(d: Path, name: str, text: str = "{not json"):
    (d / name).write_text(text)


BREAKERS = {
    "manifest_missing": lambda d: _rm(d, "manifest.json"),
    "manifest_corrupt": lambda d: _corrupt(d, "manifest.json"),
    "manifest_not_object": lambda d: _corrupt(d, "manifest.json", "[1, 2, 3]"),
    "stop_stats_missing": lambda d: _rm(d, "stop_stats.json"),
    "stop_stats_corrupt": lambda d: _corrupt(d, "stop_stats.json"),
    "commute_ubc_missing": lambda d: _rm(d, "commute_ubc.json"),
    "commute_sfu_corrupt": lambda d: _corrupt(d, "commute_sfu.json"),
    "stops_missing": lambda d: _rm(d, "stops.json"),
    "stops_corrupt": lambda d: _corrupt(d, "stops.json"),
    "stops_list_shape": lambda d: _corrupt(d, "stops.json", json.dumps([["A", "x", 49.0, -123.0]])),
    "stops_short_value": lambda d: _corrupt(d, "stops.json", json.dumps({"A": ["x", 49.0]})),
    "stops_value_not_list": lambda d: _corrupt(d, "stops.json", json.dumps({"A": "x"})),
}

# breakers that leave stops.json readable and well-formed
STOPS_OK = ["manifest_missing", "manifest_corrupt", "manifest_not_object", "stop_stats_missing",
            "stop_stats_corrupt", "commute_ubc_missing", "commute_sfu_corrupt"]


@pytest.fixture
def broken(tmp_path):
    def _make(kind: str) -> Path:
        d = write_set(tmp_path / kind)
        BREAKERS[kind](d)
        return d
    return _make


class TestFallback:
    @pytest.mark.parametrize("kind", sorted(BREAKERS))
    def test_flags_and_never_raises(self, broken, kind):
        transit.load(broken(kind))  # must not raise
        st = transit.data_status()
        assert st["gtfs_loaded"] is False
        assert st["fallback"] is True
        assert set(st) == {"gtfs_loaded", "fallback", "feed_version", "service_date", "stops"}
        assert type(st["stops"]) is int
        # queries must not raise either
        assert isinstance(transit.nearest_stops(O_LAT, O_LON), list)
        assert transit.stop_stats("A") is None

    def test_nonexistent_dir_fallback(self, tmp_path):
        transit.load(tmp_path / "does_not_exist")
        st = transit.data_status()
        assert st["gtfs_loaded"] is False and st["fallback"] is True
        assert st["stops"] == 0
        assert st["feed_version"] is None and st["service_date"] is None

    @pytest.mark.parametrize("kind", ["manifest_missing", "manifest_corrupt"])
    def test_no_manifest_feed_version_none(self, broken, kind):
        transit.load(broken(kind))
        st = transit.data_status()
        assert st["feed_version"] is None and st["service_date"] is None
        assert st["stops"] == len(STOPS)

    @pytest.mark.parametrize("kind", STOPS_OK)
    def test_stop_stats_none_for_all(self, broken, kind):
        transit.load(broken(kind))
        for sid in STATS:
            assert transit.stop_stats(sid) is None

    @pytest.mark.parametrize("kind", STOPS_OK)
    @pytest.mark.parametrize("campus", sorted(config.CAMPUS_COORDS))
    def test_commute_straight_line(self, broken, kind, campus):
        transit.load(broken(kind))
        for sid in STOPS:
            v = transit.commute_minutes(sid, campus)
            exp = fallback_commute(sid, campus)
            assert v is not None and type(v) is float
            assert v == pytest.approx(exp, abs=0.1 + 1e-9)
            assert round(v, 1) == v

    def test_commute_straight_line_exact_value(self, broken):
        # A (49.25, -123.10) -> SFU (49.2766, -122.9156) is ~13.6 km -> ~40.9 min at 20 km/h
        transit.load(broken("manifest_missing"))
        assert transit.FALLBACK_KMH == 20
        v = transit.commute_minutes("A", "sfu")
        assert v == pytest.approx(fallback_commute("A", "sfu"), abs=0.1 + 1e-9)
        assert 35 < v < 45

    def test_commute_fallback_ignores_existing_file(self, broken):
        """A missing ubc file makes the WHOLE set fallback: sfu is straight-line too."""
        transit.load(broken("commute_ubc_missing"))
        assert transit.commute_minutes("A", "sfu") != 45.5
        assert transit.commute_minutes("E", "sfu") is not None  # unreachable in file, but fallback

    @pytest.mark.parametrize("campus", ["mit", "../x"])
    def test_bad_campus_value_error_in_fallback(self, broken, campus):
        transit.load(broken("manifest_missing"))
        with pytest.raises(ValueError):
            transit.commute_minutes("A", campus)

    def test_commute_unknown_stop_none_in_fallback(self, broken):
        transit.load(broken("manifest_missing"))
        assert transit.commute_minutes("NOPE", "sfu") is None

    @pytest.mark.parametrize("kind", STOPS_OK)
    def test_nearest_stops_works_from_stops_json(self, broken, kind):
        transit.load(broken(kind))
        res = transit.nearest_stops(O_LAT, O_LON, radius_m=1000)
        assert ids(res) == ["A", "T-a", "T-b", "D"]
        assert res[3][1] == pytest.approx(900, abs=0.5)

    def test_stops_missing_nearest_empty(self, broken):
        transit.load(broken("stops_missing"))
        assert transit.nearest_stops(O_LAT, O_LON, radius_m=2000) == []
        assert transit.data_status()["stops"] == 0
        assert transit.commute_minutes("A", "sfu") is None

    def test_only_stops_json_present(self, tmp_path):
        d = tmp_path / "only_stops"
        d.mkdir()
        (d / "stops.json").write_text(json.dumps(STOPS))
        transit.load(d)
        st = transit.data_status()
        assert st["fallback"] is True and st["gtfs_loaded"] is False
        assert st["stops"] == len(STOPS)
        assert ids(transit.nearest_stops(O_LAT, O_LON)) == ["A", "T-a", "T-b", "D"]


# ---------------------------------------------------------------- atomic swap

class TestAtomicSwap:
    def test_good_then_fallback_reflects_only_second(self, tmp_path):
        transit.load(write_set(tmp_path / "A"))
        assert transit.data_status()["gtfs_loaded"] is True

        b = tmp_path / "B"
        b.mkdir()
        other = {"Z": ["Zulu Stn", 49.20, -123.05]}
        (b / "stops.json").write_text(json.dumps(other))
        (b / "stop_stats.json").write_text(json.dumps(STATS))  # no manifest -> fallback
        transit.load(b)

        st = transit.data_status()
        assert st == {"gtfs_loaded": False, "fallback": True, "feed_version": None,
                      "service_date": None, "stops": 1}
        assert transit.stop_stats("A") is None
        assert transit.stop_stats("Z") is None
        assert transit.commute_minutes("A", "sfu") is None  # A unknown in B
        assert transit.commute_minutes("Z", "sfu") == pytest.approx(
            fallback_commute("Z", "sfu", other), abs=0.1 + 1e-9)
        assert transit.nearest_stops(O_LAT, O_LON, radius_m=2000) == []
        assert ids(transit.nearest_stops(49.20, -123.05, radius_m=10)) == ["Z"]

    def test_good_then_missing_dir_clears_everything(self, tmp_path):
        transit.load(write_set(tmp_path / "A"))
        transit.load(tmp_path / "missing")
        assert transit.data_status()["stops"] == 0
        assert transit.nearest_stops(O_LAT, O_LON) == []
        assert transit.stop_stats("A") is None
        assert transit.commute_minutes("A", "sfu") is None

    def test_good_then_partial_set_no_mix(self, tmp_path):
        transit.load(write_set(tmp_path / "A"))
        b = write_set(tmp_path / "B", stops={"Y": ["Yankee", 49.21, -123.06]},
                      stats={"Y": STATS["A"]}, commute={"sfu": {"Y": 33.3}})
        (b / "commute_bcit.json").unlink()
        transit.load(b)
        st = transit.data_status()
        assert st["fallback"] is True and st["gtfs_loaded"] is False and st["stops"] == 1
        assert transit.stop_stats("Y") is None
        assert transit.stop_stats("A") is None
        assert transit.commute_minutes("Y", "sfu") != 33.3

    def test_fallback_then_good(self, tmp_path):
        transit.load(tmp_path / "missing")
        transit.load(write_set(tmp_path / "A"))
        assert transit.data_status()["gtfs_loaded"] is True
        assert transit.stop_stats("A") is not None
        assert transit.commute_minutes("A", "sfu") == 45.5

    def test_reload_same_dir_picks_up_new_content(self, tmp_path):
        d = write_set(tmp_path / "A")
        transit.load(d)
        write_set(d, commute={"sfu": {"A": 10.0}, "ubc": {}, "bcit": {}})
        transit.load(d)
        assert transit.commute_minutes("A", "sfu") == 10.0
        assert transit.commute_minutes("A", "ubc") is None


# ---------------------------------------------------------------- auto-load

class TestAutoLoad:
    def test_functions_auto_load_default_dir(self, tmp_path, monkeypatch):
        d = write_set(tmp_path / "default")
        transit.reset()
        monkeypatch.setattr(transit, "DATA_DIR", d)
        res = transit.nearest_stops(O_LAT, O_LON)
        assert ids(res) == ["A", "T-a", "T-b", "D"]
        assert transit.data_status()["gtfs_loaded"] is True

    @pytest.mark.parametrize("call", [
        lambda: transit.data_status(),
        lambda: transit.stop_stats("A"),
        lambda: transit.commute_minutes("A", "sfu"),
    ])
    def test_each_entry_point_auto_loads(self, tmp_path, monkeypatch, call):
        d = write_set(tmp_path / "default")
        transit.reset()
        monkeypatch.setattr(transit, "DATA_DIR", d)
        assert call() is not None
        assert transit.data_status()["feed_version"] == FEED_VERSION


# ---------------------------------------------------------------- real data (read-only)

real_skip = pytest.mark.skipif(not (REAL_DATA / "manifest.json").exists(),
                               reason="backend/data/manifest.json missing")


@pytest.mark.real
@real_skip
class TestRealData:
    def test_loaded(self):
        transit.load(REAL_DATA)  # read-only
        st = transit.data_status()
        assert st["gtfs_loaded"] is True and st["fallback"] is False
        assert st["stops"] >= 8000
        assert isinstance(st["feed_version"], str) and st["feed_version"]
        assert isinstance(st["service_date"], str) and len(st["service_date"]) == 8

    def test_nearest_metrotown(self):
        transit.load(REAL_DATA)  # read-only
        res = transit.nearest_stops(49.2262, -123.0029, radius_m=300)
        got = ids(res)
        assert got[0] in {"1173", "12109"}
        assert "1173" in got and "12109" in got
        assert all(w <= 300 for _, w in res)
        assert [w for _, w in res] == sorted(w for _, w in res)

    def test_commute_metrotown_sfu(self):
        transit.load(REAL_DATA)  # read-only
        assert 42 <= transit.commute_minutes("8068", "sfu") <= 58

    def test_stop_stats_metrotown(self):
        transit.load(REAL_DATA)  # read-only
        s = transit.stop_stats("8068")
        assert s is not None and 2 <= s.headway_min <= 6


# ---------------------------------------------------------------- T5: reset

class TestReset:
    def test_reset_then_auto_loads_data_dir(self, tmp_path, monkeypatch):
        transit.load(tmp_path / "missing")
        assert transit.data_status()["fallback"] is True
        d = write_set(tmp_path / "default")
        monkeypatch.setattr(transit, "DATA_DIR", d)
        transit.reset()
        assert transit.data_status()["gtfs_loaded"] is True
        assert transit.commute_minutes("A", "sfu") == 45.5

    def test_reset_keeps_classes(self):
        stop_cls, stats_cls = transit.Stop, transit.StopStats
        transit.reset()
        assert transit.Stop is stop_cls and transit.StopStats is stats_cls


# ---------------------------------------------------------------- T1: manifest campuses

def _set_manifest_campuses(d: Path, campuses: dict):
    m = json.loads((d / "manifest.json").read_text())
    m["campuses"] = campuses
    (d / "manifest.json").write_text(json.dumps(m))


def _assert_fallback():
    st = transit.data_status()
    assert st["fallback"] is True and st["gtfs_loaded"] is False


CFG = {k: list(v) for k, v in config.CAMPUS_COORDS.items()}


class TestManifestCampuses:
    def test_missing_one_config_campus_fallback(self, tmp_path):
        d = write_set(tmp_path / "s", campuses={k: v for k, v in CFG.items() if k != "bcit"})
        transit.load(d)
        _assert_fallback()
        v = transit.commute_minutes("A", "bcit")
        assert v == pytest.approx(fallback_commute("A", "bcit"), abs=0.1 + 1e-9)

    def test_missing_campus_even_if_file_present_fallback(self, tmp_path):
        d = write_set(tmp_path / "s")  # all three commute files on disk
        _set_manifest_campuses(d, {k: v for k, v in CFG.items() if k != "ubc"})
        transit.load(d)
        _assert_fallback()

    def test_empty_campuses_fallback(self, tmp_path):
        d = write_set(tmp_path / "s")
        _set_manifest_campuses(d, {})
        transit.load(d)
        _assert_fallback()

    def test_extra_campus_not_in_config_fallback(self, tmp_path):
        d = write_set(tmp_path / "s", campuses={**CFG, "douglas": [49.2034, -122.9127]},
                      commute={**COMMUTE, "douglas": {"A": 20.0}})
        assert (d / "commute_douglas.json").exists()
        transit.load(d)
        _assert_fallback()
        with pytest.raises(ValueError):
            transit.commute_minutes("A", "douglas")

    @pytest.mark.parametrize("bad", ["../x", "x/../../sentinel", "/etc/passwd", "..", "sfu/../ubc"])
    def test_traversal_campus_fallback_and_no_outside_open(self, tmp_path, monkeypatch, bad):
        d = write_set(tmp_path / "data")
        # make each traversal path resolvable to a file that WOULD parse fine
        good = json.dumps({"A": 1.0})
        (d / "commute_..").mkdir()
        (d / "commute_.." / "x.json").write_text(good)
        (d / "commute_x").mkdir()
        (tmp_path / "sentinel.json").write_text(good)
        (d / "commute_sfu").mkdir()
        _set_manifest_campuses(d, {**CFG, bad: [49.0, -123.0]})

        opened: list[Path] = []
        real_open, real_io_open, real_path_open = builtins.open, io.open, Path.open

        def rec(file, *a, **k):
            if isinstance(file, (str, bytes, Path)):
                opened.append(Path(file if not isinstance(file, bytes) else file.decode()))
            return real_open(file, *a, **k)

        def rec_path(self, *a, **k):
            opened.append(Path(self))
            return real_path_open(self, *a, **k)

        monkeypatch.setattr(builtins, "open", rec)
        monkeypatch.setattr(io, "open", rec)
        monkeypatch.setattr(Path, "open", rec_path)
        transit.load(d)
        monkeypatch.undo()

        _assert_fallback()
        root = d.resolve()
        for p in opened:
            rp = Path(p).resolve()
            assert rp == root or root in rp.parents, f"opened outside data dir: {rp}"
            assert ".." not in Path(p).parts
            assert rp.name in {"manifest.json", "stops.json", "stop_stats.json"} or (
                rp.name.startswith("commute_") and rp.parent == root
                and rp.name[len("commute_"):-len(".json")] in config.CAMPUS_COORDS), rp


# ---------------------------------------------------------------- T2: non-finite numbers

def _raw_set(tmp_path: Path, kind: str) -> Path:
    stops = {k: list(v) for k, v in STOPS.items()}
    stats = {k: dict(v) for k, v in STATS.items()}
    commute = {k: dict(v) for k, v in COMMUTE.items()}
    if kind == "stop_lat_nan":
        stops["A"][1] = float("nan")
    elif kind == "stop_lon_inf":
        stops["D"][2] = float("inf")
    elif kind == "stop_lat_neg_inf":
        stops["T-a"][1] = float("-inf")
    elif kind == "headway_nan":
        stats["A"]["headway_min"] = float("nan")
    elif kind == "dph_inf":
        stats["D"]["departures_per_hour"] = float("inf")
    elif kind == "commute_nan":
        commute["sfu"]["A"] = float("nan")
    elif kind == "commute_neg_inf":
        commute["ubc"]["A"] = float("-inf")
    elif kind == "commute_negative":
        commute["bcit"]["A"] = -5.0
    d = write_set(tmp_path / kind, stops=stops, stats=stats, commute=commute)  # json.dumps emits NaN/Infinity
    if kind == "stop_lat_1e999":  # parses to inf
        txt = (d / "stops.json").read_text()
        (d / "stops.json").write_text(txt.replace(json.dumps(STOPS["E"][1]), "1e999", 1))
    return d


NONFINITE = ["stop_lat_nan", "stop_lon_inf", "stop_lat_neg_inf", "stop_lat_1e999", "headway_nan",
             "dph_inf", "commute_nan", "commute_neg_inf", "commute_negative"]


def _assert_all_finite():
    for campus in config.CAMPUS_COORDS:
        for sid in STOPS:
            v = transit.commute_minutes(sid, campus)
            assert v is None or (math.isfinite(v) and v >= 0), (sid, campus, v)
    for sid in STOPS:
        s = transit.stop_stats(sid)
        if s is not None:
            assert s.headway_min is None or math.isfinite(s.headway_min)
            assert math.isfinite(s.departures_per_hour)
    for lat, lon in [(O_LAT, O_LON), (O_LAT + 0.01, O_LON - 0.01)]:
        for stop, walk in transit.nearest_stops(lat, lon, radius_m=2000):
            assert math.isfinite(walk)
            assert math.isfinite(stop.lat) and math.isfinite(stop.lon)


class TestNonFinite:
    def test_raw_text_really_has_literals(self, tmp_path):
        assert "NaN" in (_raw_set(tmp_path, "commute_nan") / "commute_sfu.json").read_text()
        assert "1e999" in (_raw_set(tmp_path, "stop_lat_1e999") / "stops.json").read_text()

    @pytest.mark.parametrize("kind", NONFINITE)
    def test_fallback(self, tmp_path, kind):
        transit.load(_raw_set(tmp_path, kind))
        _assert_fallback()

    @pytest.mark.parametrize("kind", NONFINITE)
    def test_no_lookup_returns_nonfinite(self, tmp_path, kind):
        transit.load(_raw_set(tmp_path, kind))
        _assert_all_finite()
        st = transit.data_status()
        assert isinstance(st["stops"], int)


# ---------------------------------------------------------------- T3: hostile content

class TestHostileContent:
    @pytest.mark.parametrize("name", ["stops.json", "manifest.json", "stop_stats.json", "commute_sfu.json"])
    def test_deeply_nested_json_fallback(self, tmp_path, name):
        d = write_set(tmp_path / "s")
        (d / name).write_text("[" * 100_000)
        transit.load(d)  # must not raise (RecursionError)
        _assert_fallback()

    @pytest.mark.parametrize("name", ["stops.json", "manifest.json"])
    def test_deeply_nested_closed_json_fallback(self, tmp_path, name):
        d = write_set(tmp_path / "s")
        (d / name).write_text("[" * 100_000 + "]" * 100_000)
        transit.load(d)
        _assert_fallback()

    @pytest.mark.parametrize("raw", [b"\xff\xfe\x00garbage", b"", b"null", b"\x00" * 64])
    def test_binary_or_null_manifest_fallback(self, tmp_path, raw):
        d = write_set(tmp_path / "s")
        (d / "manifest.json").write_bytes(raw)
        transit.load(d)
        _assert_fallback()

    def test_stops_json_is_directory_fallback(self, tmp_path):
        d = write_set(tmp_path / "s")
        (d / "stops.json").unlink()
        (d / "stops.json").mkdir()
        transit.load(d)
        _assert_fallback()
        assert transit.nearest_stops(O_LAT, O_LON) == []


# ---------------------------------------------------------------- T4: argument types

class TestArgTypes:
    @pytest.mark.parametrize("radius", [float("nan"), float("inf"), float("-inf"), None, "500", True,
                                        False, [500], np.float64("nan")])
    def test_bad_radius_value_error(self, complete, radius):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.nearest_stops(O_LAT, O_LON, radius_m=radius)

    @pytest.mark.parametrize("k", [2.5, 1.0, True, False, "3", [2], np.float64(2.0)])
    def test_bad_k_value_error(self, complete, k):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.nearest_stops(O_LAT, O_LON, k=k)

    @pytest.mark.parametrize("conv", [np.float32, np.float64, np.int64, np.int32])
    def test_numpy_lat_lon_accepted(self, tmp_path, conv):
        stops = {"Z": ["Integer Point", 49.0, -123.0], "Y": ["Far", 49.1, -123.0]}
        transit.load(write_set(tmp_path / "s", stops=stops, stats={}, commute={}))
        res = transit.nearest_stops(conv(49), conv(-123), radius_m=10)
        assert ids(res) == ["Z"]
        assert isinstance(res[0][1], float)

    @pytest.mark.parametrize("conv", [np.float32, np.float64, np.int64, np.int32])
    def test_numpy_radius_accepted(self, complete, conv):
        transit.load(complete)
        assert ids(transit.nearest_stops(O_LAT, O_LON, radius_m=conv(1000))) == ["A", "T-a", "T-b", "D"]

    def test_numpy_float32_origin(self, complete):
        transit.load(complete)
        lat32, lon32 = np.float32(O_LAT), np.float32(O_LON)  # lon32 != O_LON (not exactly representable)
        res = transit.nearest_stops(lat32, lon32, radius_m=1000)
        # float32 input behaves exactly like its float64 value (the tie can break either way)
        assert res == transit.nearest_stops(float(lat32), float(lon32), radius_m=1000)
        assert set(ids(res)) == {"A", "T-a", "T-b", "D"}

    @pytest.mark.parametrize("bad", [np.float64("nan"), np.float32("inf")])
    def test_numpy_nonfinite_lat_value_error(self, complete, bad):
        transit.load(complete)
        with pytest.raises(ValueError):
            transit.nearest_stops(bad, O_LON)
