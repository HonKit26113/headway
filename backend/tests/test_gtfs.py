"""Tests for service/gtfs.py: parse_gtfs_time, parse_gtfs_times, load_stops.

Spec: CONTRACT.md, section "Build-time: `service/gtfs.py`".
Real-feed quirks: data/PROFILE.md (space-padded hours, hours up to 29,
alphanumeric stop_ids, stations/entrances mixed in with stops).

These tests double as the spec: read the case table below first.
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from service.gtfs import load_stops, parse_gtfs_time, parse_gtfs_times

# ---------------------------------------------------------------------------
# One shared case table: (input, expected seconds or None, why).
# Both parse_gtfs_time and parse_gtfs_times are held to exactly these rules.
# ---------------------------------------------------------------------------
TIME_CASES = [
    # --- valid ---
    ("08:05:00", 29100, "zero-padded hour"),
    ("8:05:00", 29100, "single-digit hour, no padding"),
    (" 5:05:00", 18300, "TransLink pads hours with a SPACE, not a zero"),
    ("  5:05:00  ", 18300, "surrounding whitespace is ignored"),
    ("00:00:00", 0, "midnight of the service day"),
    ("23:59:59", 86399, "last second before 24h"),
    ("24:00:00", 86400, "hours >= 24 are legal: midnight at the END of the service day"),
    ("25:10:00", 90600, "1:10 AM the next calendar day, same service day"),
    ("29:57:00", 107820, "latest time in the real TransLink feed"),
    ("47:59:59", 172799, "largest allowed value (hours <= 47)"),
    ("8:5:0", 29100, "3 integer parts with min/sec < 60 is enough; no zero-padding required"),
    # --- invalid -> None ---
    ("48:00:00", None, "hours > 47 rejected"),
    ("", None, "blank"),
    ("   ", None, "whitespace only is blank"),
    ("5:05", None, "only 2 parts"),
    ("5:05:00:00", None, "4 parts"),
    ("ab:cd:ef", None, "parts must be integers"),
    ("08:60:00", None, "minutes must be < 60"),
    ("08:00:60", None, "seconds must be < 60"),
    ("-1:00:00", None, "negative parts rejected"),
    ("+5:05:00", None, "each part must be plain digits: no sign, even '+' (decided 2026-10-03)"),
    ("05: 05:00", None, "whitespace INSIDE the time is rejected; only surrounding whitespace is stripped"),
    ("0" * 5000 + "1:00:00", None, "absurdly long digit part -> None, never an exception (decided 2026-10-03)"),
    ("9" * 5000 + ":00:00", None, "huge hour -> None, never an exception (decided 2026-10-03)"),
    ("\u0665:05:00", None, "Arabic-Indic digit 5: 'plain digits' means ASCII 0-9 only"),
    ("\uff15:05:00", None, "full-width digit 5: ASCII 0-9 only"),
]

VALID_CASES = [c for c in TIME_CASES if c[1] is not None]
INVALID_CASES = [c for c in TIME_CASES if c[1] is None]


def _ids(cases):
    """Readable test ids; very long inputs are shortened to 'head...(N chars)'."""
    out = []
    for s, expected, _ in cases:
        shown = repr(s) if len(s) <= 20 else f"{s[:6]!r}...({len(s)} chars)"
        out.append(f"{shown}->{expected}")
    return out


# ===========================================================================
# parse_gtfs_time (scalar)
# ===========================================================================
class TestParseGtfsTime:
    @pytest.mark.parametrize("s, expected, why", TIME_CASES, ids=_ids(TIME_CASES))
    def test_case_table(self, s, expected, why):
        assert parse_gtfs_time(s) == expected, why

    @pytest.mark.parametrize("s, expected, why", INVALID_CASES, ids=_ids(INVALID_CASES))
    def test_invalid_returns_none_not_zero_or_nan(self, s, expected, why):
        """Invalid must be exactly None (not 0, not NaN, not an exception)."""
        assert parse_gtfs_time(s) is None, why

    @pytest.mark.parametrize("s, expected, why", VALID_CASES, ids=_ids(VALID_CASES))
    def test_valid_returns_plain_python_int(self, s, expected, why):
        """Plain int: not numpy.int64, not float, not bool."""
        result = parse_gtfs_time(s)
        assert type(result) is int

    def test_next_day_time_sorts_after_late_evening(self):
        """Why we convert to seconds: as strings ' 9:00:00' > '10:00:00' is False only
        by luck of the space, and '9:00:00' > '10:00:00' is True. Integers sort right."""
        assert parse_gtfs_time("25:10:00") > parse_gtfs_time("23:59:59")
        assert parse_gtfs_time("9:00:00") < parse_gtfs_time("10:00:00")
        assert parse_gtfs_time(" 9:00:00") < parse_gtfs_time("10:00:00")


# ===========================================================================
# parse_gtfs_times (vectorized column version)
# ===========================================================================
class TestParseGtfsTimes:
    def test_mixed_series_dtype_index_and_na(self):
        """Result is nullable Int32, keeps the input index, invalid -> <NA>."""
        s = pd.Series([" 5:05:00", "bad", "25:10:00"], index=[10, 20, 30])
        out = parse_gtfs_times(s)

        assert isinstance(out, pd.Series)
        assert out.dtype == "Int32"
        assert list(out.index) == [10, 20, 30]
        assert out.loc[10] == 18300
        assert out.loc[20] is pd.NA
        assert out.loc[30] == 90600

    def test_matches_scalar_rules_on_full_case_table(self):
        """Element-wise identical to the case table used for parse_gtfs_time."""
        inputs = [c[0] for c in TIME_CASES]
        expected = pd.array([c[1] for c in TIME_CASES], dtype="Int32")
        out = parse_gtfs_times(pd.Series(inputs))

        assert out.dtype == "Int32"
        pd.testing.assert_series_equal(
            out.reset_index(drop=True),
            pd.Series(expected),
            check_names=False,
        )

    @pytest.mark.parametrize("s, expected, why", TIME_CASES, ids=_ids(TIME_CASES))
    def test_each_case_alone(self, s, expected, why):
        """One-element Series per case, so a failure names the exact input."""
        out = parse_gtfs_times(pd.Series([s]))
        if expected is None:
            assert out.iloc[0] is pd.NA, why
        else:
            assert out.iloc[0] == expected, why

    def test_does_not_mutate_input(self):
        s = pd.Series([" 5:05:00", "25:10:00"])
        before = s.copy()
        parse_gtfs_times(s)
        pd.testing.assert_series_equal(s, before)

    def test_nan_and_none_elements_become_na(self):
        """Input may be object dtype mixing strings with float('nan') and None
        (e.g. a CSV read without keep_default_na=False). Missing -> <NA>, no crash."""
        s = pd.Series([" 5:05:00", float("nan"), None, "25:10:00"], dtype=object, index=[1, 2, 3, 4])
        out = parse_gtfs_times(s)

        assert out.dtype == "Int32"
        assert list(out.index) == [1, 2, 3, 4]
        assert out.loc[1] == 18300
        assert out.loc[2] is pd.NA
        assert out.loc[3] is pd.NA
        assert out.loc[4] == 90600

    def test_all_nan_series(self):
        out = parse_gtfs_times(pd.Series([np.nan, np.nan]))
        assert out.dtype == "Int32"
        assert out.isna().all()

    def test_keeps_series_name(self):
        """The result keeps the input's name, so it drops straight back into a DataFrame."""
        s = pd.Series([" 5:05:00", "bad"], name="departure_time")
        out = parse_gtfs_times(s)
        assert out.name == "departure_time"

    def test_duplicate_index_kept_in_positional_order(self):
        """A duplicate, unsorted index must come back exactly as given, values in
        row order (no reindexing, sorting or de-duplication)."""
        s = pd.Series(["08:05:00", "bad", "25:10:00"], index=[5, 5, 3])
        out = parse_gtfs_times(s)
        assert list(out.index) == [5, 5, 3]
        assert out.iloc[0] == 29100
        assert out.iloc[1] is pd.NA
        assert out.iloc[2] == 90600

    @pytest.mark.parametrize("dtype", ["category", "string"])
    def test_categorical_and_string_dtype_match_object(self, dtype):
        """Same answers whether the column is object, categorical or pandas 'string'.
        (Short inputs only; the 5000-digit cases are covered by the case table.)"""
        values = [c[0] for c in TIME_CASES if len(c[0]) <= 20]
        expected = parse_gtfs_times(pd.Series(values, dtype=object))
        out = parse_gtfs_times(pd.Series(values, dtype=dtype))
        pd.testing.assert_series_equal(out, expected)

    def test_empty_series(self):
        out = parse_gtfs_times(pd.Series([], dtype=object))
        assert len(out) == 0
        assert out.dtype == "Int32"

    def test_perf_one_million_rows_is_vectorized(self):
        """PERF GUARD: the real stop_times has ~1.8M rows, so a plain Python loop
        calling parse_gtfs_time per row is likely too slow. Any approach that beats
        the (deliberately generous) threshold is fine."""
        n = 1_000_000
        s = pd.Series(np.tile(np.array([" 5:05:00", "25:10:00"], dtype=object), n // 2))

        t0 = time.perf_counter()
        out = parse_gtfs_times(s)
        elapsed = time.perf_counter() - t0

        assert len(out) == n
        assert out.dtype == "Int32"
        assert out.iloc[0] == 18300 and out.iloc[1] == 90600
        assert elapsed < 3.0, f"took {elapsed:.2f}s for 1M rows; vectorize it"

    def test_perf_one_million_rows_many_distinct_values(self):
        """PERF GUARD: ~100,000 DISTINCT valid times in 1M rows, so tricks that only
        parse a handful of unique strings don't get a free pass. Generous threshold."""
        n, distinct = 1_000_000, 100_000
        secs = np.arange(distinct)  # 0 .. 99,999 seconds (hours 0..27)
        uniq = np.array(
            [f"{x // 3600:2d}:{x // 60 % 60:02d}:{x % 60:02d}" for x in secs], dtype=object
        )  # TransLink style: ' 5:05:00'
        s = pd.Series(np.tile(uniq, n // distinct))

        t0 = time.perf_counter()
        out = parse_gtfs_times(s)
        elapsed = time.perf_counter() - t0

        assert len(out) == n
        assert out.dtype == "Int32"
        assert out.iloc[:distinct].tolist() == secs.tolist()
        assert elapsed < 3.0, f"took {elapsed:.2f}s for 1M rows with 100k distinct values"


# ===========================================================================
# load_stops
# ===========================================================================
STOPS_HEADER = (
    "stop_id,stop_code,stop_name,stop_desc,stop_lat,stop_lon,zone_id,"
    "stop_url,location_type,parent_station,wheelchair_boarding"
)
# Mirrors real TransLink rows (see data/PROFILE.md). Comment = expected fate.
STOPS_ROWS = [
    "1173,52975,Metrotown Station @ Bay 2,,49.226085,-123.002888,BUS ZN,,0,,1",           # keep
    "99941,,Metrotown Station,,49.225825,-123.003920,BUS ZN,,1,,1",                        # drop: station
    "MTSEE,,Metrotown Station East Entrance,,49.225900,-123.003100,,,2,99941,",            # drop: entrance
    "8068,59999,Metrotown Station @ Platform 1,,49.225600,-123.004100,ZN 1,,0,99941,1",    # keep: platform has a parent but is boardable
    "12109,61935,Metrotown Station @ Bay 15,,49.225500,-123.003000,BUS ZN,,0,,1",          # keep
    "1875,51862,SFU Transit Exchange @ Bay 1,,49.278518,-122.912940,BUS ZN,,,,1",          # keep: blank location_type = boardable
    "2836,52390,SFU Transit Exchange @ Bay 3,,,-122.912681,BUS ZN,,0,,1",                  # drop: blank lat
    "12972,61989,SFU Transit Exchange @ Bay 4,,49.278146,abc,BUS ZN,,0,,1",                # drop: non-numeric lon
    "WCE1,,Waterfront Station @ WCE Platform,,49.285900,-123.111700,ZN 1,,0,,1",           # keep: alphanumeric boardable id
    "0123,,Leading Zero Test Stop,,49.250000,-123.100000,BUS ZN,,0,,1",                    # keep: '0123' stays text
    "NA,,Stop Whose Id Is NA,,49.260000,-123.110000,BUS ZN,,0,,1",                          # keep: 'NA' must not become NaN
    "77777,,Generic Node,,49.270000,-123.120000,,,3,,",                                     # drop: location_type 3 (other)
    "3129,52391,SFU Transit Exchange @ Bay 2,,nan,-122.912790,BUS ZN,,0,,1",               # drop: lat 'nan' parses as float but is not a number
    "1873,51860,SFU Transportation Centre @ Bay 2,,49.279954,inf,BUS ZN,,0,,1",           # drop: lon 'inf'
    "2717,52976,Metrotown Station @ Bay 1,,-inf,-123.003000,BUS ZN,,0,,1",                 # drop: lat '-inf'
    "1877,51861,SFU Transportation Centre @ Bay 1,,49.279957,-122.920119,BUS ZN,,0,,1",    # keep
]
STOPS_TXT = STOPS_HEADER + "\n" + "\n".join(STOPS_ROWS) + "\n"

EXPECTED_IDS = ["1173", "8068", "12109", "1875", "WCE1", "0123", "NA", "1877"]


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def stops_zip():
    """An open in-memory GTFS zip containing only the hand-written stops.txt."""
    with zipfile.ZipFile(io.BytesIO(_zip_bytes({"stops.txt": STOPS_TXT}))) as zf:
        yield zf


class TestLoadStops:
    def test_columns_exact_and_in_order(self, stops_zip):
        """Extra columns (stop_code, zone_id, parent_station, ...) are dropped."""
        stops = load_stops(stops_zip)
        assert list(stops.columns) == ["stop_id", "stop_name", "stop_lat", "stop_lon"]

    def test_dtypes(self, stops_zip):
        stops = load_stops(stops_zip)
        assert stops["stop_id"].dtype == object
        assert stops["stop_name"].dtype == object
        assert stops["stop_lat"].dtype == np.float64
        assert stops["stop_lon"].dtype == np.float64
        assert all(type(v) is str for v in stops["stop_id"])

    def test_keeps_exactly_boardable_rows_in_file_order(self, stops_zip):
        stops = load_stops(stops_zip)
        assert list(stops["stop_id"]) == EXPECTED_IDS

    def test_fresh_range_index(self, stops_zip):
        """Dropped rows must not leave gaps: index is 0..n-1."""
        stops = load_stops(stops_zip)
        pd.testing.assert_index_equal(stops.index, pd.RangeIndex(len(EXPECTED_IDS)))

    def test_drops_stations_and_entrances(self, stops_zip):
        """location_type 1 = station, 2 = entrance; neither appears in stop_times."""
        stops = load_stops(stops_zip)
        ids = set(stops["stop_id"])
        assert "99941" not in ids
        assert "MTSEE" not in ids

    def test_drops_other_location_types(self, stops_zip):
        stops = load_stops(stops_zip)
        assert "77777" not in set(stops["stop_id"])

    def test_platform_with_parent_station_is_kept(self, stops_zip):
        """Rail platforms have parent_station set but are still boardable (type 0)."""
        stops = load_stops(stops_zip)
        assert "8068" in set(stops["stop_id"])

    def test_blank_location_type_is_boardable(self, stops_zip):
        """GTFS: empty location_type means 0 (a stop)."""
        stops = load_stops(stops_zip)
        assert "1875" in set(stops["stop_id"])

    def test_drops_nan_and_inf_coordinates(self, stops_zip):
        """'nan', 'inf', '-inf' convert to floats but are not real coordinates
        (decided 2026-10-03): drop the row. Every kept coordinate must be finite."""
        stops = load_stops(stops_zip)
        ids = set(stops["stop_id"])
        assert "3129" not in ids, "stop_lat 'nan'"
        assert "1873" not in ids, "stop_lon 'inf'"
        assert "2717" not in ids, "stop_lat '-inf'"
        assert np.isfinite(stops["stop_lat"]).all()
        assert np.isfinite(stops["stop_lon"]).all()

    def test_drops_bad_coordinates(self, stops_zip):
        stops = load_stops(stops_zip)
        ids = set(stops["stop_id"])
        assert "2836" not in ids, "blank stop_lat"
        assert "12972" not in ids, "non-numeric stop_lon"
        assert stops["stop_lat"].notna().all()
        assert stops["stop_lon"].notna().all()

    def test_leading_zero_id_stays_text(self, stops_zip):
        """stop_id is an identifier, never a number: '0123' must not become 123."""
        stops = load_stops(stops_zip)
        assert "0123" in list(stops["stop_id"])
        assert "123" not in list(stops["stop_id"])

    def test_alphanumeric_id_preserved(self, stops_zip):
        stops = load_stops(stops_zip)
        assert "WCE1" in list(stops["stop_id"])

    def test_id_NA_is_not_turned_into_nan(self, stops_zip):
        """keep_default_na=False: the literal text 'NA' is data, not a missing value."""
        stops = load_stops(stops_zip)
        assert "NA" in list(stops["stop_id"])
        assert stops["stop_id"].notna().all()

    def test_stop_id_not_replaced_by_stop_code(self, stops_zip):
        """stop_code (public 5-digit code) differs from stop_id; we keep stop_id."""
        stops = load_stops(stops_zip)
        row = stops[stops["stop_id"] == "1173"]
        assert len(row) == 1
        assert "52975" not in list(stops["stop_id"])

    def test_values_of_a_real_row(self, stops_zip):
        stops = load_stops(stops_zip)
        row = stops[stops["stop_id"] == "1173"].iloc[0]
        assert row["stop_name"] == "Metrotown Station @ Bay 2"
        assert row["stop_lat"] == pytest.approx(49.226085)
        assert row["stop_lon"] == pytest.approx(-123.002888)

    def test_utf8_bom_header_still_gives_stop_id(self):
        """Some GTFS exports start stops.txt with a UTF-8 BOM. The first column must
        still be called 'stop_id', not '\\ufeffstop_id'."""
        data = _zip_bytes({"stops.txt": "\ufeff" + STOPS_TXT})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            stops = load_stops(zf)
        assert list(stops.columns) == ["stop_id", "stop_name", "stop_lat", "stop_lon"]
        assert list(stops["stop_id"]) == EXPECTED_IDS

    def test_missing_stops_txt_raises_keyerror(self):
        data = _zip_bytes({"routes.txt": "route_id\nR1\n"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(KeyError):
                load_stops(zf)


REAL_ZIP = Path(__file__).resolve().parent.parent / "data" / "raw" / "google_transit.zip"


@pytest.mark.real
def test_load_stops_real_feed():
    """Real TransLink feed: 8,729 boardable stops (PROFILE.md). Read-only."""
    if not REAL_ZIP.exists():
        pytest.skip(f"{REAL_ZIP} not present")
    with zipfile.ZipFile(REAL_ZIP, "r") as zf:
        stops = load_stops(zf)

    assert len(stops) == 8729
    assert stops["stop_lat"].between(49.0, 49.5).all()
    assert stops["stop_lon"].between(-123.5, -122.3).all()
    ids = set(stops["stop_id"])
    assert "1173" in ids
    assert "99941" not in ids
    assert "MTSEE" not in ids
    assert stops["stop_id"].is_unique
