"""Tests for service/gtfs.py Phase C: active_service_ids, load_trips, build_stop_stats.

Spec: CONTRACT.md, section "Build-time: service days + stop stats".
Real-feed facts: data/PROFILE.md (calendar structure, holiday removals of service '1',
pickup_type=1 terminus rows, NightBus departures after midnight).

Read these as the spec. Times in build_stop_stats are SECONDS since the service day's
midnight; 07:00 = 25200, 19:00 = 68400, 23:00 = 82800, 25:30 = 91800.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from service.gtfs import active_service_ids, build_stop_stats, load_trips

REAL_ZIP = Path(__file__).resolve().parent.parent / "data" / "raw" / "google_transit.zip"

STATS_KEYS = {
    "headway_min",
    "trips_per_day",
    "last_departure_min",
    "last_departure_label",
    "late_trips_after_23",
    "departures_per_hour",  # decision 15
}


def hms(h: int, m: int = 0, s: int = 0) -> int:
    """Clock time -> seconds since service-day midnight (h may be >= 24)."""
    return h * 3600 + m * 60 + s


def zip_with(tmp_path: Path, members: dict[str, str], name: str = "feed.zip") -> Path:
    """Write a zip holding exactly `members` ({member name: CSV text})."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for member, text in members.items():
            zf.writestr(member, text)
    return path


# ===========================================================================
# active_service_ids
# ===========================================================================
# Modeled on the real feed: '1' = Mon-Fri, '2' = Sat, '3' = Sun, '-999' = every day
# (HandyDART), all valid 20260907-20270103. Thanksgiving Monday 20261012 removes '1'.
CALENDAR = """\
service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
1,1,1,1,1,1,0,0,20260907,20270103
2,0,0,0,0,0,1,0,20260907,20270103
3,0,0,0,0,0,0,1,20260907,20270103
-999,1,1,1,1,1,1,1,20260907,20270103
WEDONLY,0,0,1,0,0,0,0,20260907,20270103
"""

CALENDAR_DATES = """\
service_id,date,exception_type
1,20261012,2
101,20261007,1
2,20261007,1
ONLYCD,20261008,1
5,20261007,1
5,20261007,2
101,20261014,1
"""


@pytest.fixture
def cal_zip(tmp_path):
    """Opener: cal_zip(calendar=..., calendar_dates=...) -> open ZipFile. None = member absent."""
    opened: list[zipfile.ZipFile] = []

    def _open(calendar: str | None = CALENDAR, calendar_dates: str | None = CALENDAR_DATES):
        members = {}
        if calendar is not None:
            members["calendar.txt"] = calendar
        if calendar_dates is not None:
            members["calendar_dates.txt"] = calendar_dates
        path = zip_with(tmp_path, members, name=f"cal{len(opened)}.zip")
        zf = zipfile.ZipFile(path)
        opened.append(zf)
        return zf

    yield _open
    for zf in opened:
        zf.close()


class TestActiveServiceIds:
    @pytest.mark.parametrize(
        "date, expected, why",
        [
            ("20261007", {"1", "-999", "WEDONLY", "101", "2"},
             "Wed: weekday services + calendar_dates adds ('101' only in cd, '2' added on a weekday)"),
            ("20261008", {"1", "-999", "ONLYCD"},
             "Thu: WEDONLY's weekday flag is 0; ONLYCD exists only in calendar_dates"),
            ("20261010", {"2", "-999"}, "Saturday"),
            ("20261011", {"3", "-999"}, "Sunday"),
            ("20261012", {"-999"},
             "Thanksgiving Monday: exception_type 2 removes '1' even though calendar.txt says it runs"),
            ("20261014", {"1", "-999", "WEDONLY", "101"},
             "next Wed: '2' is NOT added (its add was only for 20261007)"),
            ("20260907", {"1", "-999"}, "start_date is inclusive (Monday 20260907)"),
            ("20270103", {"3", "-999"}, "end_date is inclusive (Sunday 20270103)"),
            ("20260906", set(), "the day before start_date: nothing runs"),
            ("20270104", set(), "the day after end_date: nothing runs"),
        ],
    )
    def test_case_table(self, cal_zip, date, expected, why):
        assert active_service_ids(cal_zip(), date) == expected, why

    def test_returns_a_set_of_str(self, cal_zip):
        got = active_service_ids(cal_zip(), "20261007")
        assert type(got) is set
        assert all(type(s) is str for s in got)

    def test_negative_style_id_kept_as_text(self, cal_zip):
        """'-999' must stay the string '-999' (never int -999, never '-999.0')."""
        got = active_service_ids(cal_zip(), "20261010")
        assert "-999" in got
        assert -999 not in got

    def test_remove_beats_add_on_same_date(self, cal_zip):
        """Service '5' is both added and removed on 20261007: removals are applied last."""
        assert "5" not in active_service_ids(cal_zip(), "20261007")

    def test_missing_calendar_txt_uses_only_adds(self, cal_zip):
        zf = cal_zip(calendar=None)
        assert active_service_ids(zf, "20261007") == {"101", "2"}  # "5" added then removed
        assert active_service_ids(zf, "20261008") == {"ONLYCD"}
        assert active_service_ids(zf, "20261010") == set()

    def test_missing_calendar_dates_txt_uses_only_base(self, cal_zip):
        zf = cal_zip(calendar_dates=None)
        assert active_service_ids(zf, "20261007") == {"1", "-999", "WEDONLY"}
        # no holiday removal without calendar_dates
        assert active_service_ids(zf, "20261012") == {"1", "-999"}

    @pytest.mark.parametrize(
        "start, end",
        [("", "20270103"), ("20260907", ""), ("", "")],
        ids=["blank-start", "blank-end", "both-blank"],
    )
    @pytest.mark.parametrize("date", ["20260101", "20261007", "20270103", "20991231"])
    def test_blank_calendar_dates_never_run(self, cal_zip, start, end, date):
        """D13: a calendar.txt row with a blank start_date or end_date is never active
        (a blank must not compare as 'before every date' / 'after every date')."""
        cal = (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            f"BLANK,1,1,1,1,1,1,1,{start},{end}\n"
            "OK,1,1,1,1,1,1,1,20260907,20270103\n"
        )
        got = active_service_ids(cal_zip(calendar=cal, calendar_dates=None), date)
        assert "BLANK" not in got

    def test_leading_zero_ids_kept(self, cal_zip):
        cd = "service_id,date,exception_type\n0042,20261007,1\n"
        assert active_service_ids(cal_zip(calendar=None, calendar_dates=cd), "20261007") == {"0042"}

    @pytest.mark.parametrize(
        "bad",
        ["2026-10-07", "20261340", "20260230", "2026107", "", "abcdefgh", "202610070"],
    )
    def test_bad_date_raises_value_error(self, cal_zip, bad):
        with pytest.raises(ValueError):
            active_service_ids(cal_zip(), bad)


# ===========================================================================
# load_trips
# ===========================================================================
TRIPS_TXT = """\
route_id,service_id,trip_id,trip_headsign,trip_short_name,direction_id,block_id,shape_id,wheelchair_accessible,bikes_allowed
6658,1,0123,SFU,,0,NA,1,1,1
30053,-999,T2,Waterfront,,1,B2,2,1,1
HD,-999,NA,,,,NA,3,0,0
"""


class TestLoadTrips:
    def _load(self, tmp_path, text: str) -> pd.DataFrame:
        with zipfile.ZipFile(zip_with(tmp_path, {"trips.txt": text})) as zf:
            return load_trips(zf)

    def test_exact_columns_in_order(self, tmp_path):
        df = self._load(tmp_path, TRIPS_TXT)
        assert list(df.columns) == ["trip_id", "route_id", "service_id", "direction_id"]

    def test_values_are_text_unchanged(self, tmp_path):
        df = self._load(tmp_path, TRIPS_TXT)
        rows = set(map(tuple, df.itertuples(index=False, name=None)))
        assert rows == {
            ("0123", "6658", "1", "0"),   # leading zero kept
            ("T2", "30053", "-999", "1"),  # '-999' stays text
            ("NA", "HD", "-999", ""),      # 'NA' is NOT NaN; blank stays ''
        }

    def test_every_cell_is_python_str(self, tmp_path):
        df = self._load(tmp_path, TRIPS_TXT)
        assert len(df) == 3
        for col in df.columns:
            assert all(type(v) is str for v in df[col]), col

    def test_missing_direction_id_column_becomes_empty_string(self, tmp_path):
        text = "route_id,service_id,trip_id\nR1,1,T1\nR2,2,T2\n"
        df = self._load(tmp_path, text)
        assert list(df.columns) == ["trip_id", "route_id", "service_id", "direction_id"]
        assert list(df["direction_id"]) == ["", ""]
        assert all(type(v) is str for v in df["direction_id"])


# ===========================================================================
# build_stop_stats
# ===========================================================================
def make_stop_times(rows) -> pd.DataFrame:
    """rows: (trip_id, stop_id, departure_s or None, pickup_type)."""
    rows = list(rows)
    return pd.DataFrame(
        {
            "trip_id": pd.Series([r[0] for r in rows], dtype=object),
            "stop_id": pd.Series([r[1] for r in rows], dtype=object),
            "departure_s": pd.array([r[2] for r in rows], dtype="Int32"),
            "pickup_type": pd.Series([r[3] for r in rows], dtype=object),
        }
    )


def make_trips(rows) -> pd.DataFrame:
    """rows: (trip_id, route_id, service_id, direction_id)."""
    return pd.DataFrame(
        list(rows), columns=["trip_id", "route_id", "service_id", "direction_id"], dtype=object
    )


def one_trip_per_departure(stop_id, times, route="R1", direction="0", service="1", prefix=None):
    """Each departure is its own trip (typical: one trip passes a stop once)."""
    prefix = prefix or f"{stop_id}-{route}-{direction}-"
    st = [(f"{prefix}{i}", stop_id, t, "0") for i, t in enumerate(times)]
    tr = [(f"{prefix}{i}", route, service, direction) for i in range(len(times))]
    return st, tr


def stats_for(st_rows, trip_rows, service_ids=frozenset({"1"})):
    return build_stop_stats(make_stop_times(st_rows), make_trips(trip_rows), set(service_ids))


def every(minutes: int, start_s: int, end_s: int) -> list[int]:
    """Departures every `minutes` from start_s (inclusive) up to end_s (exclusive)."""
    return list(range(start_s, end_s, minutes * 60))


class TestWhatCountsAsADeparture:
    def test_only_active_service_trips_count(self):
        st = [("A", "S1", hms(8), "0"), ("B", "S1", hms(9), "0")]
        tr = [("A", "R1", "1", "0"), ("B", "R1", "2", "0")]  # B runs on service '2' only
        got = stats_for(st, tr, {"1"})
        assert got["S1"]["trips_per_day"] == 1

    def test_trip_missing_from_trips_does_not_count(self):
        st = [("A", "S1", hms(8), "0"), ("ORPHAN", "S1", hms(9), "0")]
        tr = [("A", "R1", "1", "0")]
        assert stats_for(st, tr)["S1"]["trips_per_day"] == 1

    def test_pickup_type_1_is_not_a_departure(self):
        """A terminus row (pickup_type '1', you cannot board) at 1:30 AM must NOT
        become the stop's last departure."""
        st = [
            ("A", "S1", hms(22), "0"),
            ("B", "S1", hms(25, 30), "1"),  # drop-off only, after midnight
        ]
        tr = [("A", "R1", "1", "0"), ("B", "R1", "1", "0")]
        s1 = stats_for(st, tr)["S1"]
        assert s1["trips_per_day"] == 1
        assert s1["last_departure_min"] == 22 * 60
        assert s1["last_departure_label"] == "10:00 PM"
        assert s1["late_trips_after_23"] == 0

    @pytest.mark.parametrize("pickup", ["0", "", "2", "3"])
    def test_other_pickup_types_are_departures(self, pickup):
        st = [("A", "S1", hms(8), pickup)]
        tr = [("A", "R1", "1", "0")]
        assert stats_for(st, tr)["S1"]["trips_per_day"] == 1

    def test_na_departure_is_ignored(self):
        st = [("A", "S1", hms(8), "0"), ("B", "S1", None, "0")]
        tr = [("A", "R1", "1", "0"), ("B", "R1", "1", "0")]
        s1 = stats_for(st, tr)["S1"]
        assert s1["trips_per_day"] == 1
        assert s1["last_departure_min"] == 8 * 60

    def test_stops_with_zero_departures_are_absent(self):
        st = [
            ("A", "BOARD", hms(8), "0"),
            ("A", "DROPONLY", hms(8, 10), "1"),
            ("B", "INACTIVE", hms(8), "0"),
            ("A", "NOTIME", None, "0"),
        ]
        tr = [("A", "R1", "1", "0"), ("B", "R1", "2", "0")]
        assert set(stats_for(st, tr)) == {"BOARD"}

    def test_nothing_active_gives_empty_dict(self):
        st = [("A", "S1", hms(8), "0")]
        tr = [("A", "R1", "2", "0")]
        assert stats_for(st, tr, {"1"}) == {}

    def test_stop_ids_kept_as_text(self):
        st = [("A", "WFSCS", hms(8), "0"), ("A", "0123", hms(8, 5), "0")]
        tr = [("A", "R1", "1", "0")]
        assert set(stats_for(st, tr)) == {"WFSCS", "0123"}


class TestHeadway:
    @pytest.mark.parametrize(
        "count, expected",
        [
            (48, 15.0),   # every 15 min for 12 h
            (7, 102.9),   # 720/7 = 102.857... -> 1 decimal
            (1, 720.0),
            (11, 65.5),   # 65.4545...
            (240, 3.0),   # SkyTrain-like
        ],
    )
    def test_720_over_count_rounded_to_1_decimal(self, count, expected):
        times = [hms(7) + i * (43200 // count) for i in range(count)]
        st, tr = one_trip_per_departure("S1", times)
        assert stats_for(st, tr)["S1"]["headway_min"] == expected

    def test_window_starts_at_0700_inclusive_and_ends_at_1900_exclusive(self):
        times = [hms(6, 59, 59), hms(7), hms(18, 59, 59), hms(19)]
        st, tr = one_trip_per_departure("S1", times)
        s1 = stats_for(st, tr)["S1"]
        assert s1["headway_min"] == 360.0  # only 07:00:00 and 18:59:59 are in the window
        assert s1["trips_per_day"] == 4

    def test_best_route_direction_group_is_used(self):
        """Stop served by R1 every 60 min and R2 every 15 min: headway is R2's (15.0),
        NOT the two routes merged (720/60 = 12.0)."""
        st1, tr1 = one_trip_per_departure("S1", every(60, hms(7), hms(19)), route="R1")
        st2, tr2 = one_trip_per_departure("S1", every(15, hms(7), hms(19)), route="R2")
        s1 = stats_for(st1 + st2, tr1 + tr2)["S1"]
        assert s1["headway_min"] == 15.0
        assert s1["trips_per_day"] == 12 + 48

    def test_directions_are_not_merged(self):
        """Same route both directions, 6 each: 720/6 = 120.0, not 720/12 = 60.0."""
        st0, tr0 = one_trip_per_departure("S1", every(120, hms(7), hms(19)), direction="0")
        st1, tr1 = one_trip_per_departure("S1", every(120, hms(8), hms(19)), direction="1")
        assert len(st0) == 6 and len(st1) == 6
        assert stats_for(st0 + st1, tr0 + tr1)["S1"]["headway_min"] == 120.0

    def test_only_active_departures_count_toward_headway(self):
        st1, tr1 = one_trip_per_departure("S1", every(60, hms(7), hms(19)), service="1")
        st2, tr2 = one_trip_per_departure("S1", every(15, hms(7), hms(19)), route="R1",
                                          service="2", prefix="sat-")
        assert stats_for(st1 + st2, tr1 + tr2, {"1"})["S1"]["headway_min"] == 60.0

    def test_no_daytime_departures_gives_none_but_stop_present(self):
        """NightBus-only stop: present, with headway None."""
        st, tr = one_trip_per_departure("N1", [hms(1), hms(2), hms(25, 30)], route="N19")
        n1 = stats_for(st, tr)["N1"]
        assert n1["headway_min"] is None
        assert n1["trips_per_day"] == 3

    def test_per_stop_groups(self):
        """Headway groups are (stop, route, direction): another stop's trips don't leak in."""
        st1, tr1 = one_trip_per_departure("A", every(15, hms(7), hms(19)))
        st2, tr2 = one_trip_per_departure("B", every(60, hms(7), hms(19)))
        got = stats_for(st1 + st2, tr1 + tr2)
        assert got["A"]["headway_min"] == 15.0
        assert got["B"]["headway_min"] == 60.0


class TestCountsAndLastDeparture:
    def test_trips_per_day_counts_all_departures_any_hour(self):
        times = [hms(5), hms(8), hms(12), hms(20), hms(23, 30), hms(25)]
        st, tr = one_trip_per_departure("S1", times)
        assert stats_for(st, tr)["S1"]["trips_per_day"] == 6

    def test_last_departure_after_midnight(self):
        st, tr = one_trip_per_departure("S1", [hms(8), hms(25, 30), hms(22)])
        s1 = stats_for(st, tr)["S1"]
        assert s1["last_departure_min"] == 1530
        assert s1["last_departure_label"] == "1:30 AM"

    def test_last_departure_min_floors_seconds(self):
        st, tr = one_trip_per_departure("S1", [hms(21, 14, 59)])
        assert stats_for(st, tr)["S1"]["last_departure_min"] == 21 * 60 + 14

    @pytest.mark.parametrize(
        "minute, label",
        [
            (1530, "1:30 AM"),
            (720, "12:00 PM"),
            (0, "12:00 AM"),
            (1439, "11:59 PM"),
            (1440, "12:00 AM"),
            (780, "1:00 PM"),
            (1505, "1:05 AM"),   # minutes zero-padded, hour not
            (545, "9:05 AM"),
            (1380, "11:00 PM"),
            (1797, "5:57 AM"),   # 29:57, latest time in the real feed
        ],
    )
    def test_label_12_hour_clock(self, minute, label):
        st, tr = one_trip_per_departure("S1", [minute * 60])
        s1 = stats_for(st, tr)["S1"]
        assert s1["last_departure_min"] == minute
        assert s1["last_departure_label"] == label

    def test_late_trips_after_23_boundary_inclusive(self):
        times = [hms(22, 59, 59), hms(23), hms(23, 30), hms(25, 30), hms(12)]
        st, tr = one_trip_per_departure("S1", times)
        assert stats_for(st, tr)["S1"]["late_trips_after_23"] == 3

    def test_full_stats_dict(self):
        times = every(30, hms(7), hms(19)) + [hms(6), hms(23, 15), hms(24, 45)]
        st, tr = one_trip_per_departure("S1", times)
        assert stats_for(st, tr) == {
            "S1": {
                "headway_min": 30.0,
                "trips_per_day": 27,
                "last_departure_min": 1485,
                "last_departure_label": "12:45 AM",
                "late_trips_after_23": 2,
                "departures_per_hour": 2.0,  # 24 daytime departures / 12 h
            }
        }


class TestOutputIsPlainJson:
    @staticmethod
    def compute():
        st1, tr1 = one_trip_per_departure("DAY", every(15, hms(7), hms(19)) + [hms(25, 30)])
        st2, tr2 = one_trip_per_departure("NIGHT", [hms(2)], route="N19")
        return stats_for(st1 + st2, tr1 + tr2)

    def test_exact_stat_keys(self):
        result = self.compute()
        for stats in result.values():
            assert set(stats) == STATS_KEYS

    def test_plain_python_types(self):
        result = self.compute()
        assert type(result) is dict
        for stop_id, s in result.items():
            assert type(stop_id) is str
            assert type(s["headway_min"]) in (float, type(None))
            assert type(s["trips_per_day"]) is int
            assert type(s["last_departure_min"]) is int
            assert type(s["last_departure_label"]) is str
            assert type(s["late_trips_after_23"]) is int
            assert type(s["departures_per_hour"]) is float
        assert type(result["DAY"]["headway_min"]) is float
        assert result["NIGHT"]["headway_min"] is None

    def test_json_dumps_without_nan(self):
        result = self.compute()
        text = json.dumps(result, allow_nan=False)
        assert json.loads(text) == result


# ===========================================================================
# Hardening (CONTRACT.md decision 12)
# ===========================================================================
class TestHardening:
    def test_duplicate_trip_ids_in_trips_raise_value_error(self):
        """Each trip must map to exactly one service/route; a duplicate would silently
        double-count departures. pandas MergeError is a ValueError subclass."""
        st = [("A", "S1", hms(8), "0")]
        tr = [("A", "R1", "1", "0"), ("A", "R2", "1", "0")]
        with pytest.raises(ValueError):
            stats_for(st, tr)

    def test_categorical_stop_id_same_as_text(self):
        st1, tr1 = one_trip_per_departure("S1", every(15, hms(7), hms(19)) + [hms(25)])
        st2, tr2 = one_trip_per_departure("S2", [hms(9), hms(23, 30)], route="R2")
        stop_times, trips = make_stop_times(st1 + st2), make_trips(tr1 + tr2)
        expected = build_stop_stats(stop_times, trips, {"1"})

        cat = stop_times.copy()
        cat["stop_id"] = pd.Categorical(cat["stop_id"], categories=["S1", "S2", "UNUSED"])
        got = build_stop_stats(cat, trips, {"1"})

        assert got == expected
        assert "UNUSED" not in got
        assert all(type(k) is str for k in got)

    @pytest.mark.parametrize("missing", [None, float("nan")], ids=["None", "NaN"])
    def test_missing_direction_id_still_counts_toward_headway(self, missing):
        st, tr = one_trip_per_departure("S1", every(30, hms(7), hms(19)), direction=missing)
        s1 = stats_for(st, tr)["S1"]
        assert s1["headway_min"] == 30.0
        assert s1["trips_per_day"] == 24

    @pytest.mark.parametrize("missing", [None, float("nan")], ids=["None", "NaN"])
    def test_missing_direction_id_groups_with_blank(self, missing):
        """Decision 14: None/NaN direction_id is the same group as ''.
        24 '' + 24 missing daytime departures on R1 -> ONE group of 48 -> 15.0 (not 30.0)."""
        st1, tr1 = one_trip_per_departure("S1", every(30, hms(7), hms(19)), direction="", prefix="blank-")
        st2, tr2 = one_trip_per_departure("S1", every(30, hms(7, 15), hms(19)), direction=missing,
                                          prefix="missing-")
        assert len(st1) == 24 and len(st2) == 24
        assert stats_for(st1 + st2, tr1 + tr2)["S1"]["headway_min"] == 15.0

    def test_missing_direction_id_not_merged_with_real_direction(self):
        """Control: '0' and None stay separate groups (24 each -> 30.0)."""
        st1, tr1 = one_trip_per_departure("S1", every(30, hms(7), hms(19)), direction="0", prefix="d0-")
        st2, tr2 = one_trip_per_departure("S1", every(30, hms(7, 15), hms(19)), direction=None,
                                          prefix="none-")
        assert stats_for(st1 + st2, tr1 + tr2)["S1"]["headway_min"] == 30.0


# ===========================================================================
# departures_per_hour (decision 15): ALL routes/directions, [07:00, 19:00) / 12
# ===========================================================================
class TestDeparturesPerHour:
    def test_sums_all_routes_and_directions(self):
        """24 + 24 + 12 + 12 = 72 daytime departures / 12 h = 6.0.
        headway_min stays the best SINGLE group (24 -> 30.0)."""
        parts = [
            one_trip_per_departure("S1", every(30, hms(7), hms(19)), route="R1", direction="0"),
            one_trip_per_departure("S1", every(30, hms(7), hms(19)), route="R1", direction="1"),
            one_trip_per_departure("S1", every(60, hms(7), hms(19)), route="R2", direction="0"),
            one_trip_per_departure("S1", every(60, hms(7), hms(19)), route="R2", direction="1"),
        ]
        st = [r for p in parts for r in p[0]]
        tr = [r for p in parts for r in p[1]]
        s1 = stats_for(st, tr)["S1"]
        assert s1["departures_per_hour"] == 6.0
        assert s1["headway_min"] == 30.0

    def test_window_0700_inclusive_1900_exclusive(self):
        """In window: 07:00, 12:00, 13:00, 18:59:59 -> 4 / 12 = 0.333 -> 0.3.
        (Counts avoid x.x5 ties so the rounding mode doesn't matter.)"""
        times = [hms(6, 59, 59), hms(7), hms(12), hms(13), hms(18, 59, 59), hms(19), hms(25)]
        st, tr = one_trip_per_departure("S1", times)
        assert stats_for(st, tr)["S1"]["departures_per_hour"] == 0.3

    @pytest.mark.parametrize("count, expected", [(7, 0.6), (25, 2.1), (12, 1.0), (240, 20.0), (1, 0.1)])
    def test_rounded_to_1_decimal(self, count, expected):
        times = [hms(7) + i * (43200 // count) for i in range(count)]
        st, tr = one_trip_per_departure("S1", times)
        assert stats_for(st, tr)["S1"]["departures_per_hour"] == expected

    def test_pickup_type_1_and_inactive_trips_excluded(self):
        st = [
            ("A", "S1", hms(8), "0"),   # counts
            ("B", "S1", hms(9), "1"),   # drop-off only
            ("C", "S1", hms(10), "0"),  # Saturday service, inactive
            ("D", "S1", None, "0"),     # no time
        ] + [(f"E{i}", "S1", hms(11), "0") for i in range(11)]  # 11 more -> 12 total
        tr = [("A", "R1", "1", "0"), ("B", "R1", "1", "0"), ("C", "R1", "2", "0"),
              ("D", "R1", "1", "0")] + [(f"E{i}", "R1", "1", "0") for i in range(11)]
        assert stats_for(st, tr)["S1"]["departures_per_hour"] == 1.0

    def test_type_is_float(self):
        st, tr = one_trip_per_departure("S1", every(5, hms(7), hms(19)))
        v = stats_for(st, tr)["S1"]["departures_per_hour"]
        assert type(v) is float and v == 12.0

    def test_night_only_stop_is_zero_with_headway_none(self):
        st, tr = one_trip_per_departure("N1", [hms(1), hms(2), hms(25, 30)], route="N19")
        n1 = stats_for(st, tr)["N1"]
        assert n1["departures_per_hour"] == 0.0
        assert type(n1["departures_per_hour"]) is float
        assert n1["headway_min"] is None


def test_inputs_not_mutated():
    st_rows, tr_rows = one_trip_per_departure("S1", every(20, hms(6), hms(26)))
    st_rows.append(("X", "S2", None, "1"))
    st, tr = make_stop_times(st_rows), make_trips(tr_rows)
    st_before, tr_before = st.copy(deep=True), tr.copy(deep=True)
    ids = {"1"}

    build_stop_stats(st, tr, ids)

    pd.testing.assert_frame_equal(st, st_before)
    pd.testing.assert_frame_equal(tr, tr_before)
    assert ids == {"1"}


# ===========================================================================
# Real feed (read-only; cheap: calendar + trips only)
# ===========================================================================
real = pytest.mark.skipif(not REAL_ZIP.exists(), reason="data/raw/google_transit.zip missing")


@pytest.mark.real
@real
def test_real_active_services_wednesday():
    with zipfile.ZipFile(REAL_ZIP) as zf:
        assert active_service_ids(zf, "20261007") == {
            "-999", "1", "101", "1101", "152201", "155601", "2001", "259801", "401", "62201", "801",
        }


@pytest.mark.real
@real
def test_real_thanksgiving_removes_service_1():
    with zipfile.ZipFile(REAL_ZIP) as zf:
        got = active_service_ids(zf, "20261012")
    assert "1" not in got
    assert "-999" in got


@pytest.mark.real
@real
def test_real_load_trips():
    with zipfile.ZipFile(REAL_ZIP) as zf:
        df = load_trips(zf)
    assert len(df) == 63_023
    assert df["trip_id"].is_unique
    assert set(df["direction_id"]) == {"0", "1"}
    assert (df["service_id"] == "1").sum() == 25_089
