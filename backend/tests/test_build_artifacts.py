"""Tests for scripts/build_artifacts.py: pick_service_date, build, main.

Spec: CONTRACT.md, sections "Build-time: `scripts/build_artifacts.py`" (Phase C) and
"Build-time: commute to campus" -> "scripts/build_artifacts.py (Phase D additions)".
Real feed (data/PROFILE.md): feed_info valid 20260907 (a Monday) -> 20270103 (a Sunday),
feed_version '26SEP_20261002'.

Offline: the tiny feed below is built in tmp_path. main() is always run with `build`
monkeypatched, so it never reads or writes the real backend/data/ directory.
Real-data tests build into tmp_path (never data/) and are marked @pytest.mark.real.

Phase D: fixture builds pass campuses=CAMPUSES (one campus 'testu' sitting on stop 2016) so
the output set is deterministic: stops.json, stop_stats.json, commute_testu.json, manifest.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import zipfile
import zlib
from pathlib import Path

import pytest

import config
import service.graph as graph
import service.gtfs as gtfs
from scripts import build_artifacts
from scripts.build_artifacts import build, main, pick_service_date
from scripts.fetch_gtfs import UnsafeZipError

BACKEND = Path(__file__).resolve().parent.parent
REAL_ZIP = BACKEND / "data" / "raw" / "google_transit.zip"
# Test campus placed exactly on fixture stop 2016 (Metrotown Bay 3).
CAMPUSES = {"testu": (49.2260, -123.0041)}
OUTPUTS = {"stops.json", "stop_stats.json", "commute_testu.json", "manifest.json"}
MANIFEST_KEYS = {
    "feed_version", "feed_start", "feed_end", "service_date",
    "source_sha256", "built_at", "counts", "campuses",
}
COUNT_KEYS = {"stops", "stop_stats", "trips_on_service_date", "commute"}


def is_wednesday(yyyymmdd: str) -> bool:
    return dt.datetime.strptime(yyyymmdd, "%Y%m%d").weekday() == 2


# ===========================================================================
# pick_service_date
# ===========================================================================
FEED_START, FEED_END = "20260907", "20270103"  # real feed: Monday .. Sunday


class TestPickServiceDate:
    @pytest.mark.parametrize(
        "start, end, today, expected, why",
        [
            (FEED_START, FEED_END, "20260801", "20260909",
             "today before feed_start -> first Wed on/after feed_start (0907 is a Monday)"),
            (FEED_START, FEED_END, "20260907", "20260909", "today == feed_start"),
            (FEED_START, FEED_END, "20261003", "20261007", "today inside (Sat) -> next Wed"),
            (FEED_START, FEED_END, "20261007", "20261007", "today is a Wednesday -> today itself"),
            (FEED_START, FEED_END, "20261008", "20261014", "today Thu -> following Wed"),
            (FEED_START, FEED_END, "20261230", "20261230", "last Wednesday in the real feed"),
            ("20260909", FEED_END, "20260101", "20260909", "feed_start itself is a Wed"),
            (FEED_START, "20261230", "20261224", "20261230", "Wed == feed_end is allowed"),
        ],
    )
    def test_case_table(self, start, end, today, expected, why):
        got = pick_service_date(start, end, today)
        assert got == expected, why
        assert type(got) is str and is_wednesday(got)

    @pytest.mark.parametrize(
        "start, end, today, why",
        [
            (FEED_START, FEED_END, "20261231", "next Wed is 20270106, after feed_end"),
            (FEED_START, FEED_END, "20270201", "today after feed_end"),
            ("20261008", "20261013", "20261001", "Thu..Tue window contains no Wednesday"),
            (FEED_START, "20261229", "20261224", "feed_end one day before the Wed"),
        ],
    )
    def test_no_wednesday_left_raises_value_error(self, start, end, today, why):
        with pytest.raises(ValueError):
            pick_service_date(start, end, today)


# ===========================================================================
# A tiny but complete GTFS feed
# ===========================================================================
# Service '1' Mon-Fri, '2' Sat. Built with today=20261003 (Sat) -> service date 20261007 (Wed).
FEED = {
    "feed_info.txt": (
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
        "TransLink,https://example.invalid,en,20260907,20270103,TEST_V1\n"
    ),
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nTL,TransLink,https://example.invalid,America/Vancouver\n",
    "stops.txt": (
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
        "1173,51234,Metrotown Station @ Bay 2,49.2259,-123.0039,0,\n"
        "8068,,Metrotown Station Platform 1,49.2258,-123.0040,0,99941\n"
        "2016,51235,Metrotown Station @ Bay 3,49.2260,-123.0041,0,\n"
        "555,50555,Quiet St @ Nowhere Ave,49.2500,-123.0100,0,\n"
        "99941,,Metrotown Station,49.225825,-123.003920,1,\n"
        "WFSCS,,Some Station Entrance,49.2856,-123.1115,2,\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R1,TL,49,Metrotown/UBC,3\nR2,TL,19,Metrotown/Stanley Park,3\n"
    ),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "1,1,1,1,1,1,0,0,20260907,20270103\n"
        "2,0,0,0,0,0,1,0,20260907,20270103\n"
    ),
    "calendar_dates.txt": "service_id,date,exception_type\n1,20261012,2\n",
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id\n"
        "R1,1,T1,UBC,0,B1,S1\n"
        "R1,1,T2,Metrotown,1,B1,S2\n"
        "R2,2,T3,Stanley Park,0,B2,S3\n"
    ),
    # Space-padded hours like TransLink. 2016 is only a drop-off terminus (pickup_type 1).
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,drop_off_type\n"
        "T1, 8:00:00, 8:00:00,1173,1,,0,0\n"
        "T1, 8:10:00, 8:10:00,8068,2,,0,0\n"
        "T1, 8:20:00, 8:20:00,2016,3,,1,0\n"
        "T2,23:30:00,23:30:00,8068,1,,0,0\n"
        "T2,25:30:00,25:30:00,1173,2,,0,0\n"
        "T3, 9:00:00, 9:00:00,1173,1,,0,0\n"
    ),
}

EXPECTED_STOPS = {
    "1173": ["Metrotown Station @ Bay 2", 49.2259, -123.0039],
    "8068": ["Metrotown Station Platform 1", 49.2258, -123.0040],
    "2016": ["Metrotown Station @ Bay 3", 49.2260, -123.0041],
    "555": ["Quiet St @ Nowhere Ave", 49.2500, -123.0100],
}

EXPECTED_STOP_STATS = {
    "1173": {  # 08:00 (R1 dir 0) and 25:30 (R1 dir 1); T3 is Saturday-only
        "headway_min": 720.0,
        "trips_per_day": 2,
        "last_departure_min": 1530,
        "last_departure_label": "1:30 AM",
        "late_trips_after_23": 1,
        "departures_per_hour": 0.1,  # 1 daytime departure / 12 h = 0.083 -> 0.1
    },
    "8068": {  # 08:10 (dir 0) and 23:30 (dir 1)
        "headway_min": 720.0,
        "trips_per_day": 2,
        "last_departure_min": 1410,
        "last_departure_label": "11:30 PM",
        "late_trips_after_23": 1,
        "departures_per_hour": 0.1,  # 1 daytime departure / 12 h = 0.083 -> 0.1
    },
    # 2016: drop-off only -> absent. 555: no service -> absent.
}

# commute to 'testu' (49.2260, -123.0041), walking at 1.4 m/s; every stop within 1 km walks:
#   1173 is 18.3 m away -> 0.22 min -> 0.2;  8068 is 23.4 m -> 0.28 -> 0.3;  2016 is on it -> 0.0
#   555 is 2.7 km away with no service -> absent. (Riding is never faster than these walks.)
EXPECTED_COMMUTE_TESTU = {"1173": 0.2, "8068": 0.3, "2016": 0.0}


def write_feed(path: Path, members: dict[str, str] = FEED, extra: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in {**members, **(extra or {})}.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), text)
    return path


def write_corrupt_stop_times(path: Path) -> Path:
    """FEED with a larger stop_times.txt whose DEFLATE bytes are overwritten mid-stream."""
    rows = "".join(f"T1,{8 + i // 60:2d}:{i % 60:02d}:00,{8 + i // 60:2d}:{i % 60:02d}:00,1173,{i + 1},,0,0\n"
                   for i in range(600))
    members = {**FEED, "stop_times.txt": FEED["stop_times.txt"] + rows}
    write_feed(path, members)
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("stop_times.txt")
    raw = bytearray(path.read_bytes())
    off = info.header_offset
    name_len = int.from_bytes(raw[off + 26:off + 28], "little")
    extra_len = int.from_bytes(raw[off + 28:off + 30], "little")
    data_start = off + 30 + name_len + extra_len
    mid = data_start + info.compress_size // 2
    raw[mid:mid + 16] = bytes(b ^ 0xFF for b in raw[mid:mid + 16])
    path.write_bytes(bytes(raw))
    return path


@pytest.fixture
def feed_zip(tmp_path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    return write_feed(d / "google_transit.zip")


@pytest.fixture
def out_dir(tmp_path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d


def read_json_strict(path: Path):
    """Parse JSON, failing on NaN/Infinity tokens and on any object whose keys aren't sorted."""

    def no_constants(token):
        raise AssertionError(f"{path.name} contains non-JSON token {token}")

    def sorted_pairs(pairs):
        keys = [k for k, _ in pairs]
        assert keys == sorted(keys), f"{path.name}: keys not sorted: {keys[:5]}..."
        return dict(pairs)

    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=no_constants, object_pairs_hook=sorted_pairs)


class Boom(Exception):
    """Injected failure (deliberately NOT a RuntimeError: NotImplementedError is one)."""


def boom(*a, **k):
    raise Boom("stop stats exploded")


def patch_build_stop_stats(monkeypatch, fn):
    """Replace build_stop_stats wherever build() might look it up."""
    monkeypatch.setattr(gtfs, "build_stop_stats", fn)
    monkeypatch.setattr(build_artifacts, "build_stop_stats", fn, raising=False)


def patch_commute(monkeypatch, fn):
    """Replace commute_from_all_stops wherever build() might look it up."""
    monkeypatch.setattr(graph, "commute_from_all_stops", fn)
    monkeypatch.setattr(build_artifacts, "commute_from_all_stops", fn, raising=False)


# ===========================================================================
# build
# ===========================================================================
class TestBuildOutputs:
    def test_writes_exactly_the_four_files(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert {p.name for p in out_dir.iterdir()} == OUTPUTS

    def test_stops_json_shape(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        stops = read_json_strict(out_dir / "stops.json")
        assert set(stops) == set(EXPECTED_STOPS), "boardable stops only (no stations/entrances)"
        for stop_id, (name, lat, lon) in EXPECTED_STOPS.items():
            got = stops[stop_id]
            assert type(got) is list and len(got) == 3
            assert got[0] == name
            assert type(got[1]) is float and got[1] == pytest.approx(lat)
            assert type(got[2]) is float and got[2] == pytest.approx(lon)

    def test_stop_stats_json_content(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert read_json_strict(out_dir / "stop_stats.json") == EXPECTED_STOP_STATS

    def test_manifest(self, feed_zip, out_dir):
        before = dt.datetime.now(dt.timezone.utc)
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        after = dt.datetime.now(dt.timezone.utc)
        m = read_json_strict(out_dir / "manifest.json")

        assert set(m) == MANIFEST_KEYS
        assert m["feed_version"] == "TEST_V1"
        assert m["feed_start"] == "20260907"
        assert m["feed_end"] == "20270103"
        assert m["service_date"] == "20261007"
        assert is_wednesday(m["service_date"])
        assert m["source_sha256"] == hashlib.sha256(feed_zip.read_bytes()).hexdigest()
        assert m["counts"] == {"stops": 4, "stop_stats": 2, "trips_on_service_date": 2,
                               "commute": {"testu": 3}}
        assert m["campuses"] == {"testu": [49.2260, -123.0041]}

        built_at = dt.datetime.fromisoformat(m["built_at"])
        assert built_at.utcoffset() == dt.timedelta(0), "built_at must be UTC with an explicit offset"
        assert before - dt.timedelta(seconds=1) <= built_at <= after + dt.timedelta(seconds=1)

    def test_returns_the_manifest(self, feed_zip, out_dir):
        returned = build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert returned == read_json_strict(out_dir / "manifest.json")

    def test_counts_are_plain_ints(self, feed_zip, out_dir):
        returned = build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        counts = returned["counts"]
        assert set(counts) == COUNT_KEYS
        assert all(type(v) is int for k, v in counts.items() if k != "commute")
        assert type(counts["commute"]) is dict
        assert all(type(k) is str and type(v) is int for k, v in counts["commute"].items())

    @pytest.mark.parametrize("name", sorted(OUTPUTS))
    def test_json_has_sorted_keys_and_no_nan(self, feed_zip, out_dir, name):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        text = (out_dir / name).read_text(encoding="utf-8")
        for token in ("NaN", "Infinity"):
            assert token not in text
        read_json_strict(out_dir / name)  # asserts sorted keys at every level

    def test_service_date_follows_today(self, feed_zip, out_dir):
        """today=20261008 (Thu) -> service date 20261014 (next Wed): service '1' runs, 2 trips."""
        m = build(feed_zip, out_dir, today="20261008", campuses=CAMPUSES)
        assert m["service_date"] == "20261014"
        assert m["counts"]["trips_on_service_date"] == 2


class TestBuildCommute:
    """Phase D: commute_<name>.json per campus + manifest campuses / counts.commute."""

    def test_commute_file_content(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert read_json_strict(out_dir / "commute_testu.json") == EXPECTED_COMMUTE_TESTU

    def test_commute_values_are_floats(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        data = read_json_strict(out_dir / "commute_testu.json")
        assert all(type(k) is str and type(v) is float for k, v in data.items())

    def test_counts_commute_matches_file_lengths(self, feed_zip, out_dir):
        m = build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        for name in CAMPUSES:
            assert m["counts"]["commute"][name] == len(read_json_strict(out_dir / f"commute_{name}.json"))

    def test_multiple_campuses_one_file_each(self, feed_zip, out_dir):
        """'far' is ~100 km from every fixture stop: its file exists and is empty, count 0."""
        campuses = {**CAMPUSES, "far": (49.9, -122.0)}
        m = build(feed_zip, out_dir, today="20261003", campuses=campuses)
        names = {p.name for p in out_dir.iterdir()}
        assert names == OUTPUTS | {"commute_far.json"}
        assert read_json_strict(out_dir / "commute_far.json") == {}
        assert read_json_strict(out_dir / "commute_testu.json") == EXPECTED_COMMUTE_TESTU
        assert m["counts"]["commute"] == {"testu": 3, "far": 0}
        assert m["campuses"] == {"testu": [49.2260, -123.0041], "far": [49.9, -122.0]}

    def test_default_campuses_come_from_config(self, feed_zip, out_dir):
        """campuses=None -> config.CAMPUS_COORDS (sfu, ubc, bcit)."""
        m = build(feed_zip, out_dir, today="20261003")
        names = {p.name for p in out_dir.iterdir()}
        expected_files = {f"commute_{n}.json" for n in config.CAMPUS_COORDS}
        assert names == {"stops.json", "stop_stats.json", "manifest.json"} | expected_files
        assert m["campuses"] == {n: [lat, lon] for n, (lat, lon) in config.CAMPUS_COORDS.items()}
        assert set(m["counts"]["commute"]) == set(config.CAMPUS_COORDS)
        for n in config.CAMPUS_COORDS:
            read_json_strict(out_dir / f"commute_{n}.json")

    def test_commute_called_with_service_day_inputs(self, feed_zip, out_dir, monkeypatch):
        """Wiring: one call per campus with the parsed stops / stop_times / trips, the active
        service ids of the picked date (20261007 Wed -> {'1'}) and that campus's (lat, lon).
        Whatever it returns is what lands in commute_<name>.json."""
        calls = []

        def spy(stops, stop_times, trips, routes, service_ids, campus_latlon, **kw):
            calls.append((stops.copy(), stop_times.copy(), trips.copy(), routes.copy(), set(service_ids),
                          tuple(campus_latlon)))
            return {"1173": 12.3}

        patch_commute(monkeypatch, spy)
        m = build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert len(calls) == 1
        stops, stop_times, trips, routes, sids, latlon = calls[0]
        assert sids == {"1"}
        assert latlon == pytest.approx((49.2260, -123.0041))
        assert set(stops["stop_id"]) == set(EXPECTED_STOPS)
        assert {"trip_id", "stop_id", "stop_sequence", "arrival_s", "departure_s"} <= set(stop_times.columns)
        assert {"trip_id", "route_id", "service_id", "direction_id"} <= set(trips.columns)
        assert read_json_strict(out_dir / "commute_testu.json") == {"1173": 12.3}
        assert m["counts"]["commute"] == {"testu": 1}


class TestBuildSafety:
    def test_unsafe_zip_rejected_before_any_output(self, tmp_path, out_dir):
        bad = write_feed(tmp_path / "evil.zip", extra={"../evil.txt": "pwned"})
        with pytest.raises(UnsafeZipError):
            build(bad, out_dir, today="20261003", campuses=CAMPUSES)
        assert list(out_dir.iterdir()) == []
        assert not (tmp_path / "evil.txt").exists()

    def test_failure_midway_leaves_no_outputs_or_temp_files(self, feed_zip, out_dir, monkeypatch):
        patch_build_stop_stats(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert list(out_dir.iterdir()) == [], "no outputs, no *.tmp leftovers"

    def test_failure_leaves_existing_good_files_untouched(self, feed_zip, out_dir, monkeypatch):
        good = {
            "stops.json": b'{"1": ["Old stop", 49.0, -123.0]}',
            "stop_stats.json": b'{"1": {"trips_per_day": 1}}',
            "commute_testu.json": b'{"1": 42.0}',
            "manifest.json": b'{"feed_version": "OLD"}',
        }
        for name, data in good.items():
            (out_dir / name).write_bytes(data)

        patch_build_stop_stats(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)

        assert {p.name for p in out_dir.iterdir()} == OUTPUTS, "no temp files left"
        for name, data in good.items():
            assert (out_dir / name).read_bytes() == data, f"{name} was modified"

    # --- D10: manifest present = complete set ------------------------------
    def test_failed_swap_removes_old_manifest(self, feed_zip, out_dir, monkeypatch):
        """If swapping in the new manifest fails, the OLD manifest must be gone too:
        it would otherwise vouch for a mix of new stops/stop_stats and stale metadata."""
        for name in OUTPUTS:
            (out_dir / name).write_text('{"old": true}', encoding="utf-8")

        real_replace = build_artifacts.os.replace

        def flaky_replace(src, dst, *a, **k):
            if Path(dst).name == "manifest.json":
                raise OSError("disk full while writing manifest")
            return real_replace(src, dst, *a, **k)

        monkeypatch.setattr(build_artifacts.os, "replace", flaky_replace)
        with pytest.raises(OSError):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)

        names = {p.name for p in out_dir.iterdir()}
        assert "manifest.json" not in names
        assert names <= OUTPUTS - {"manifest.json"}, f"temp files left behind: {names - OUTPUTS}"

    def test_successful_build_leaves_manifest(self, feed_zip, out_dir):
        for name in OUTPUTS:
            (out_dir / name).write_text('{"old": true}', encoding="utf-8")
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert read_json_strict(out_dir / "manifest.json")["feed_version"] == "TEST_V1"

    # --- Phase D: commute files are part of the same atomic set -----------
    def test_commute_failure_leaves_no_outputs(self, feed_zip, out_dir, monkeypatch):
        patch_commute(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert [p.name for p in out_dir.iterdir()] == []

    def test_commute_failure_leaves_existing_good_files_untouched(self, feed_zip, out_dir, monkeypatch):
        good = {name: f'{{"old": "{name}"}}'.encode() for name in OUTPUTS}
        for name, data in good.items():
            (out_dir / name).write_bytes(data)
        patch_commute(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert {p.name for p in out_dir.iterdir()} == OUTPUTS, "no temp files left"
        for name, data in good.items():
            assert (out_dir / name).read_bytes() == data, f"{name} was modified"

    def test_manifest_replaced_last_after_commute_files(self, feed_zip, out_dir, monkeypatch):
        order = []
        real_replace = build_artifacts.os.replace

        def recording_replace(src, dst, *a, **k):
            order.append(Path(dst).name)
            return real_replace(src, dst, *a, **k)

        monkeypatch.setattr(build_artifacts.os, "replace", recording_replace)
        campuses = {**CAMPUSES, "far": (49.9, -122.0)}
        build(feed_zip, out_dir, today="20261003", campuses=campuses)
        assert order[-1] == "manifest.json"
        assert order.count("manifest.json") == 1
        for name in ("stops.json", "stop_stats.json", "commute_testu.json", "commute_far.json"):
            assert name in order[:-1], f"{name} not swapped in before the manifest"

    def test_failed_commute_swap_removes_old_manifest(self, feed_zip, out_dir, monkeypatch):
        """Swapping in commute_testu.json fails -> old manifest gone, no temp files left."""
        for name in OUTPUTS:
            (out_dir / name).write_text('{"old": true}', encoding="utf-8")

        real_replace = build_artifacts.os.replace

        def flaky_replace(src, dst, *a, **k):
            if Path(dst).name == "commute_testu.json":
                raise OSError("disk full while writing commute file")
            return real_replace(src, dst, *a, **k)

        monkeypatch.setattr(build_artifacts.os, "replace", flaky_replace)
        with pytest.raises(OSError):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        names = {p.name for p in out_dir.iterdir()}
        assert "manifest.json" not in names
        assert names <= OUTPUTS - {"manifest.json"}, f"temp files left behind: {names - OUTPUTS}"

    # --- Phase D decision 6: campus names become file names -------------
    BAD_CAMPUS_NAMES = ["../x", "SFU", "a b", "", "sfu.json", "x/y"]

    @pytest.mark.parametrize("bad", BAD_CAMPUS_NAMES)
    def test_invalid_campus_name_rejected_before_any_output(self, feed_zip, out_dir, bad):
        """Names must match ^[a-z0-9_]+$ -> ValueError before anything is written."""
        with pytest.raises(ValueError):
            build(feed_zip, out_dir, today="20261003", campuses={bad: (49.2260, -123.0041)})
        assert list(out_dir.iterdir()) == []
        assert not (out_dir.parent / "x.json").exists()
        assert not (out_dir.parent / "commute_..").exists()

    @pytest.mark.parametrize("bad", BAD_CAMPUS_NAMES)
    def test_invalid_campus_name_leaves_existing_files_untouched(self, feed_zip, out_dir, bad):
        good = {name: f'{{"old": "{name}"}}'.encode() for name in OUTPUTS}
        for name, data in good.items():
            (out_dir / name).write_bytes(data)
        with pytest.raises(ValueError):
            build(feed_zip, out_dir, today="20261003",
                  campuses={**CAMPUSES, bad: (49.2260, -123.0041)})
        assert {p.name for p in out_dir.iterdir()} == OUTPUTS, "no new files"
        for name, data in good.items():
            assert (out_dir / name).read_bytes() == data, f"{name} was modified"

    def test_valid_campus_name_with_digit_and_underscore(self, feed_zip, out_dir):
        m = build(feed_zip, out_dir, today="20261003", campuses={"ubc_2": (49.2260, -123.0041)})
        assert read_json_strict(out_dir / "commute_ubc_2.json") == EXPECTED_COMMUTE_TESTU
        assert m["campuses"] == {"ubc_2": [49.2260, -123.0041]}

    # --- Phase D decision 7: stale commute files are removed --------------
    def test_stale_commute_file_removed_on_success(self, feed_zip, out_dir):
        (out_dir / "commute_oldcampus.json").write_text('{"1": 5.0}', encoding="utf-8")
        (out_dir / "notes.txt").write_bytes(b"keep me\n")
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        names = {p.name for p in out_dir.iterdir()}
        assert "commute_oldcampus.json" not in names
        assert names == OUTPUTS | {"notes.txt"}
        assert (out_dir / "notes.txt").read_bytes() == b"keep me\n"
        assert read_json_strict(out_dir / "commute_testu.json") == EXPECTED_COMMUTE_TESTU
        assert read_json_strict(out_dir / "manifest.json")["campuses"] == {"testu": [49.2260, -123.0041]}

    def test_stale_commute_file_kept_on_failed_build(self, feed_zip, out_dir, monkeypatch):
        (out_dir / "commute_oldcampus.json").write_text('{"1": 5.0}', encoding="utf-8")
        (out_dir / "notes.txt").write_bytes(b"keep me\n")
        patch_commute(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert (out_dir / "commute_oldcampus.json").read_text(encoding="utf-8") == '{"1": 5.0}'
        assert (out_dir / "notes.txt").read_bytes() == b"keep me\n"
        assert {p.name for p in out_dir.iterdir()} == {"commute_oldcampus.json", "notes.txt"}

    # --- Phase D decision 9: campus values validated before anything else --
    BAD_CAMPUS_VALUES = [
        "ab",
        ("49", "-123"),
        (True, 1),
        (1, 2, 3),
        (49,),
        (float("nan"), 0),
        (0, float("inf")),
        (91, 0),
        (0, 181),
    ]
    BAD_VALUE_IDS = ["str", "str-pair", "bools", "triple", "single", "nan-lat", "inf-lon",
                     "lat-91", "lon-181"]

    @staticmethod
    def _spy_never_called(monkeypatch):
        """Patch validate_zip and commute_from_all_stops with spies that record calls."""
        calls = []

        def spy_validate(*a, **k):
            calls.append("validate_zip")

        def spy_commute(*a, **k):
            calls.append("commute_from_all_stops")
            return {}

        monkeypatch.setattr(build_artifacts, "validate_zip", spy_validate, raising=False)
        import scripts.fetch_gtfs as fetch_gtfs
        monkeypatch.setattr(fetch_gtfs, "validate_zip", spy_validate)
        patch_commute(monkeypatch, spy_commute)
        return calls

    @pytest.mark.parametrize("bad", BAD_CAMPUS_VALUES, ids=BAD_VALUE_IDS)
    def test_invalid_campus_value_rejected_first_empty_dir(self, feed_zip, out_dir, monkeypatch, bad):
        calls = self._spy_never_called(monkeypatch)
        with pytest.raises(ValueError):
            build(feed_zip, out_dir, today="20261003", campuses={"testu": bad})
        assert calls == [], "validation must run before validate_zip / commute"
        assert list(out_dir.iterdir()) == []

    @pytest.mark.parametrize("bad", BAD_CAMPUS_VALUES, ids=BAD_VALUE_IDS)
    def test_invalid_campus_value_leaves_existing_files_untouched(self, feed_zip, out_dir, monkeypatch, bad):
        good = {name: f'{{"old": "{name}"}}'.encode() for name in OUTPUTS}
        for name, data in good.items():
            (out_dir / name).write_bytes(data)
        calls = self._spy_never_called(monkeypatch)
        with pytest.raises(ValueError):
            build(feed_zip, out_dir, today="20261003", campuses={**CAMPUSES, "other": bad})
        assert calls == []
        assert {p.name for p in out_dir.iterdir()} == OUTPUTS, "no new files"
        for name, data in good.items():
            assert (out_dir / name).read_bytes() == data, f"{name} was modified"

    def test_non_str_campus_name_rejected_first(self, feed_zip, out_dir, monkeypatch):
        calls = self._spy_never_called(monkeypatch)
        with pytest.raises(ValueError):
            build(feed_zip, out_dir, today="20261003", campuses={1: (49.2, -123.0)})
        assert calls == []
        assert list(out_dir.iterdir()) == []

    def test_int_coords_accepted(self, feed_zip, out_dir):
        """(49, -123) is a pair of real numbers: accepted. Every fixture stop is > 1 km from
        it with no daytime ride there, so the file exists (contents not asserted here)."""
        m = build(feed_zip, out_dir, today="20261003", campuses={"intu": (49, -123)})
        assert (out_dir / "commute_intu.json").exists()
        assert m["campuses"] == {"intu": [49, -123]}

    # --- Phase D decision 12: every stale commute_*.json goes --------------
    def test_any_stale_commute_prefixed_file_deleted(self, feed_zip, out_dir):
        """Rule: build owns the commute_*.json namespace, even hand-made files."""
        (out_dir / "commute_notes.json").write_text('{"note": "hand made"}', encoding="utf-8")
        (out_dir / "README.md").write_bytes(b"# my notes\n")
        (out_dir / "stops.json").write_text('{"old": true}', encoding="utf-8")
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        names = {p.name for p in out_dir.iterdir()}
        assert "commute_notes.json" not in names
        assert (out_dir / "README.md").read_bytes() == b"# my notes\n"
        assert set(read_json_strict(out_dir / "stops.json")) == set(EXPECTED_STOPS)
        assert names == OUTPUTS | {"README.md"}

    # --- D11: no leftovers of any name (temp names are not fixed) ----------
    def test_no_leftovers_after_success_including_hidden(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert sorted(p.name for p in out_dir.iterdir()) == sorted(OUTPUTS)

    def test_no_leftovers_after_failure_including_hidden(self, feed_zip, out_dir, monkeypatch):
        patch_build_stop_stats(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert [p.name for p in out_dir.iterdir()] == []

    # --- D9: bad feed contents --------------------------------------------
    def test_empty_feed_info_raises_value_error(self, tmp_path, out_dir):
        members = {**FEED, "feed_info.txt": FEED["feed_info.txt"].splitlines()[0] + "\n"}
        bad = write_feed(tmp_path / "empty_feed_info.zip", members)
        with pytest.raises(ValueError, match="feed_info"):
            build(bad, out_dir, today="20261003", campuses=CAMPUSES)
        assert list(out_dir.iterdir()) == []

    def test_corrupt_member_data_raises_zip_error(self, tmp_path, out_dir):
        """Zip structure intact (validate_zip passes) but stop_times.txt's compressed bytes
        are garbage -> BadZipFile (CRC) or zlib.error, and nothing is written."""
        bad = write_corrupt_stop_times(tmp_path / "corrupt.zip")
        from scripts.fetch_gtfs import validate_zip
        validate_zip(bad)  # precondition: the corruption is invisible to validate_zip
        with pytest.raises((zipfile.BadZipFile, zlib.error)):
            build(bad, out_dir, today="20261003", campuses=CAMPUSES)
        assert list(out_dir.iterdir()) == []

    def test_does_not_modify_the_source_zip(self, feed_zip, out_dir):
        before = feed_zip.read_bytes()
        build(feed_zip, out_dir, today="20261003", campuses=CAMPUSES)
        assert feed_zip.read_bytes() == before


# ===========================================================================
# main
# ===========================================================================
FAKE_MANIFEST = {
    "feed_version": "TEST_V1", "feed_start": "20260907", "feed_end": "20270103",
    "service_date": "20261007", "source_sha256": "0" * 64,
    "built_at": "2026-10-03T00:00:00+00:00",
    "counts": {"stops": 4, "stop_stats": 2, "trips_on_service_date": 2,
               "commute": {"sfu": 3, "ubc": 2, "bcit": 1}},
    "campuses": {"sfu": [49.2766, -122.9156], "ubc": [49.2606, -123.2533], "bcit": [49.2490, -123.0010]},
}


class TestMain:
    def test_success_returns_0_and_prints_one_line(self, monkeypatch, capsys):
        calls = []

        def fake_build(zip_path, out_dir, **kw):
            calls.append((Path(zip_path), Path(out_dir)))
            return dict(FAKE_MANIFEST)

        monkeypatch.setattr(build_artifacts, "build", fake_build)
        assert main() == 0

        out, err = capsys.readouterr()
        assert out.strip() and len(out.strip().splitlines()) == 1
        assert err == ""
        assert len(calls) == 1
        zip_path, out_dir = calls[0]
        assert zip_path.resolve() == (BACKEND / "data" / "raw" / "google_transit.zip").resolve()
        assert out_dir.resolve() == (BACKEND / "data").resolve()

    def test_paths_do_not_depend_on_cwd(self, monkeypatch, capsys, tmp_path):
        calls = []

        def fake_build(zip_path, out_dir, **kw):
            calls.append((Path(zip_path), Path(out_dir)))
            return dict(FAKE_MANIFEST)

        monkeypatch.setattr(build_artifacts, "build", fake_build)
        monkeypatch.chdir(tmp_path)
        assert main() == 0
        capsys.readouterr()
        assert calls, "build was not called"
        assert calls[0][1].resolve() == (BACKEND / "data").resolve()

    @pytest.mark.parametrize(
        "exc",
        [
            UnsafeZipError("member '../evil.txt' is unsafe"),
            ValueError("no Wednesday left in feed"),
            OSError("disk full"),
            KeyError("feed_info.txt"),
            # D9 (hardening): pandas .iloc on an empty table, corrupt zip member data
            IndexError("single positional indexer is out-of-bounds"),
            zipfile.BadZipFile("Bad CRC-32 for file 'stop_times.txt'"),
            zlib.error("Error -3 while decompressing data: invalid distance too far back"),
        ],
        ids=["unsafe-zip", "value-error", "os-error", "missing-member",
             "index-error", "bad-zip-crc", "zlib-error"],
    )
    def test_failure_returns_1_with_one_line_stderr(self, monkeypatch, capsys, exc):
        def fake_build(*a, **k):
            raise exc

        monkeypatch.setattr(build_artifacts, "build", fake_build)
        assert main() == 1

        out, err = capsys.readouterr()
        assert len(err.strip().splitlines()) == 1, err
        assert "Traceback" not in err and "Traceback" not in out


# ===========================================================================
# Real feed: one build into a tmp dir, shared by every test below
# ===========================================================================
_real_cache: dict = {}


@pytest.fixture(scope="module")
def real_build(tmp_path_factory):
    """Callable that builds the real feed ONCE (into tmp, never data/) and returns
    (manifest, stop_stats). Called inside each test so a build failure shows as a test
    FAILURE rather than a fixture error; the result (or exception) is cached."""
    if not REAL_ZIP.exists():
        pytest.skip("data/raw/google_transit.zip missing")
    out = tmp_path_factory.mktemp("real_artifacts")

    def _get():
        if "result" not in _real_cache and "error" not in _real_cache:
            try:
                t0 = time.perf_counter()
                manifest = build(REAL_ZIP, out, today="20261003")  # default campuses (config)
                _real_cache["elapsed_s"] = time.perf_counter() - t0
                stats = json.loads((out / "stop_stats.json").read_text(encoding="utf-8"))
                stops = json.loads((out / "stops.json").read_text(encoding="utf-8"))
                _real_cache["out"] = out
                _real_cache["result"] = (manifest, stats)
                _real_cache["stops"] = stops
            except Exception as e:  # cached so the slow build never runs twice
                _real_cache["error"] = e
        if "error" in _real_cache:
            raise _real_cache["error"]
        return _real_cache["result"]

    return _get


@pytest.mark.real
class TestRealFeed:
    def test_manifest(self, real_build):
        manifest, _ = real_build()
        assert manifest["feed_version"] == "26SEP_20261002"
        assert manifest["feed_start"] == "20260907"
        assert manifest["feed_end"] == "20270103"
        assert manifest["service_date"] == "20261007"
        assert manifest["source_sha256"] == hashlib.sha256(REAL_ZIP.read_bytes()).hexdigest()
        # PROFILE: 25,706 trips on 20261007 (whether the stop-less HandyDART trip counts is open)
        assert 25_000 <= manifest["counts"]["trips_on_service_date"] <= 26_000
        assert manifest["counts"]["stops"] == 8_729

    def test_at_least_8000_stops_have_stats(self, real_build):
        _, stats = real_build()
        assert len(stats) >= 8_000

    @pytest.mark.parametrize("platform", ["8068", "8049"])
    def test_metrotown_skytrain_headway(self, real_build, platform):
        _, stats = real_build()
        assert 2.0 <= stats[platform]["headway_min"] <= 6.0

    def test_sfu_transportation_centre_bay_1_present(self, real_build):
        _, stats = real_build()
        assert "1877" in stats
        assert stats["1877"]["trips_per_day"] > 0

    def test_metrotown_platform_departures_per_hour(self, real_build):
        _, stats = real_build()
        assert stats["8068"]["departures_per_hour"] > 15

    def test_sfu_bay_1_departures_per_hour_beats_best_route(self, real_build):
        """1877 is served by 143/144/145/R5: all-route rate > the best single route's rate."""
        _, stats = real_build()
        s = stats["1877"]
        assert s["departures_per_hour"] > 60 / s["headway_min"]

    def test_nightbus_runs_past_midnight(self, real_build):
        _, stats = real_build()
        assert any(s["last_departure_min"] > 1440 for s in stats.values())

    def test_every_stop_stats_key_is_in_stops_json(self, real_build):
        _, stats = real_build()
        assert set(stats) <= set(_real_cache["stops"])

    def test_every_headway_in_range_or_none(self, real_build):
        _, stats = real_build()
        bad = {k: s["headway_min"] for k, s in stats.items()
               if s["headway_min"] is not None and not (1.0 <= s["headway_min"] <= 720.0)}
        assert bad == {}


def real_commute(real_build) -> dict[str, dict[str, float]]:
    """{campus: commute_<campus>.json} from the shared real build (read lazily so the
    Phase C real tests above don't depend on Phase D outputs)."""
    real_build()
    if "commute" not in _real_cache:
        out = _real_cache["out"]
        _real_cache["commute"] = {
            name: read_json_strict(out / f"commute_{name}.json") for name in config.CAMPUS_COORDS
        }
    return _real_cache["commute"]


@pytest.mark.real
class TestRealCommute:
    """Phase D validator expectations (CONTRACT.md) on the real feed, service date 20261007."""

    def test_whole_build_under_60s(self, real_build):
        real_build()
        assert _real_cache["elapsed_s"] < 60, f"build took {_real_cache['elapsed_s']:.1f}s"

    def test_manifest_campuses_match_config(self, real_build):
        manifest, _ = real_build()
        assert manifest["campuses"] == {n: [lat, lon] for n, (lat, lon) in config.CAMPUS_COORDS.items()}

    def test_manifest_commute_counts_match_files(self, real_build):
        manifest, _ = real_build()
        assert manifest["counts"]["commute"] == {n: len(d) for n, d in real_commute(real_build).items()}

    @pytest.mark.parametrize("campus", sorted(config.CAMPUS_COORDS))
    def test_at_least_7000_stops_reach_each_campus(self, real_build, campus):
        assert len(real_commute(real_build)[campus]) >= 7_000

    @pytest.mark.parametrize("campus", sorted(config.CAMPUS_COORDS))
    def test_every_value_in_range(self, real_build, campus):
        bad = {k: v for k, v in real_commute(real_build)[campus].items() if not (0 < v < 240)}
        assert bad == {}

    @pytest.mark.parametrize("campus", sorted(config.CAMPUS_COORDS))
    def test_keys_are_known_stops(self, real_build, campus):
        assert set(real_commute(real_build)[campus]) <= set(_real_cache["stops"])

    # Revised validator ranges (CONTRACT.md, after decision 8: daytime hops only).
    @pytest.mark.parametrize("platform", ["8068", "8049"])
    def test_metrotown_to_sfu(self, real_build, platform):
        assert 42 <= real_commute(real_build)["sfu"][platform] <= 58

    @pytest.mark.parametrize("platform", ["8044", "8073"])
    def test_commercial_broadway_to_sfu(self, real_build, platform):
        assert 35 <= real_commute(real_build)["sfu"][platform] <= 55

    def test_metrotown_to_bcit(self, real_build):
        assert 8 <= real_commute(real_build)["bcit"]["8068"] <= 20

    def test_sfu_exchange_to_sfu(self, real_build):
        assert real_commute(real_build)["sfu"]["1875"] < 6

    def test_ubc_exchange_to_ubc(self, real_build):
        assert real_commute(real_build)["ubc"]["11792"] < 12
