"""Tests for scripts/build_artifacts.py: pick_service_date, build, main.

Spec: CONTRACT.md, section "Build-time: `scripts/build_artifacts.py`".
Real feed (data/PROFILE.md): feed_info valid 20260907 (a Monday) -> 20270103 (a Sunday),
feed_version '26SEP_20261002'.

Offline: the tiny feed below is built in tmp_path. main() is always run with `build`
monkeypatched, so it never reads or writes the real backend/data/ directory.
Real-data tests build into tmp_path (never data/) and are marked @pytest.mark.real.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import zipfile
import zlib
from pathlib import Path

import pytest

import service.gtfs as gtfs
from scripts import build_artifacts
from scripts.build_artifacts import build, main, pick_service_date
from scripts.fetch_gtfs import UnsafeZipError

BACKEND = Path(__file__).resolve().parent.parent
REAL_ZIP = BACKEND / "data" / "raw" / "google_transit.zip"
OUTPUTS = {"stops.json", "stop_stats.json", "manifest.json"}
MANIFEST_KEYS = {
    "feed_version", "feed_start", "feed_end", "service_date",
    "source_sha256", "built_at", "counts",
}
COUNT_KEYS = {"stops", "stop_stats", "trips_on_service_date"}


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


# ===========================================================================
# build
# ===========================================================================
class TestBuildOutputs:
    def test_writes_exactly_the_three_files(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003")
        assert {p.name for p in out_dir.iterdir()} == OUTPUTS

    def test_stops_json_shape(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003")
        stops = read_json_strict(out_dir / "stops.json")
        assert set(stops) == set(EXPECTED_STOPS), "boardable stops only (no stations/entrances)"
        for stop_id, (name, lat, lon) in EXPECTED_STOPS.items():
            got = stops[stop_id]
            assert type(got) is list and len(got) == 3
            assert got[0] == name
            assert type(got[1]) is float and got[1] == pytest.approx(lat)
            assert type(got[2]) is float and got[2] == pytest.approx(lon)

    def test_stop_stats_json_content(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003")
        assert read_json_strict(out_dir / "stop_stats.json") == EXPECTED_STOP_STATS

    def test_manifest(self, feed_zip, out_dir):
        before = dt.datetime.now(dt.timezone.utc)
        build(feed_zip, out_dir, today="20261003")
        after = dt.datetime.now(dt.timezone.utc)
        m = read_json_strict(out_dir / "manifest.json")

        assert set(m) == MANIFEST_KEYS
        assert m["feed_version"] == "TEST_V1"
        assert m["feed_start"] == "20260907"
        assert m["feed_end"] == "20270103"
        assert m["service_date"] == "20261007"
        assert is_wednesday(m["service_date"])
        assert m["source_sha256"] == hashlib.sha256(feed_zip.read_bytes()).hexdigest()
        assert m["counts"] == {"stops": 4, "stop_stats": 2, "trips_on_service_date": 2}

        built_at = dt.datetime.fromisoformat(m["built_at"])
        assert built_at.utcoffset() == dt.timedelta(0), "built_at must be UTC with an explicit offset"
        assert before - dt.timedelta(seconds=1) <= built_at <= after + dt.timedelta(seconds=1)

    def test_returns_the_manifest(self, feed_zip, out_dir):
        returned = build(feed_zip, out_dir, today="20261003")
        assert returned == read_json_strict(out_dir / "manifest.json")

    def test_counts_are_plain_ints(self, feed_zip, out_dir):
        returned = build(feed_zip, out_dir, today="20261003")
        assert all(type(v) is int for v in returned["counts"].values())
        assert set(returned["counts"]) == COUNT_KEYS

    @pytest.mark.parametrize("name", sorted(OUTPUTS))
    def test_json_has_sorted_keys_and_no_nan(self, feed_zip, out_dir, name):
        build(feed_zip, out_dir, today="20261003")
        text = (out_dir / name).read_text(encoding="utf-8")
        for token in ("NaN", "Infinity"):
            assert token not in text
        read_json_strict(out_dir / name)  # asserts sorted keys at every level

    def test_service_date_follows_today(self, feed_zip, out_dir):
        """today=20261008 (Thu) -> service date 20261014 (next Wed): service '1' runs, 2 trips."""
        m = build(feed_zip, out_dir, today="20261008")
        assert m["service_date"] == "20261014"
        assert m["counts"]["trips_on_service_date"] == 2


class TestBuildSafety:
    def test_unsafe_zip_rejected_before_any_output(self, tmp_path, out_dir):
        bad = write_feed(tmp_path / "evil.zip", extra={"../evil.txt": "pwned"})
        with pytest.raises(UnsafeZipError):
            build(bad, out_dir, today="20261003")
        assert list(out_dir.iterdir()) == []
        assert not (tmp_path / "evil.txt").exists()

    def test_failure_midway_leaves_no_outputs_or_temp_files(self, feed_zip, out_dir, monkeypatch):
        patch_build_stop_stats(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003")
        assert list(out_dir.iterdir()) == [], "no outputs, no *.tmp leftovers"

    def test_failure_leaves_existing_good_files_untouched(self, feed_zip, out_dir, monkeypatch):
        good = {
            "stops.json": b'{"1": ["Old stop", 49.0, -123.0]}',
            "stop_stats.json": b'{"1": {"trips_per_day": 1}}',
            "manifest.json": b'{"feed_version": "OLD"}',
        }
        for name, data in good.items():
            (out_dir / name).write_bytes(data)

        patch_build_stop_stats(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003")

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
            build(feed_zip, out_dir, today="20261003")

        names = {p.name for p in out_dir.iterdir()}
        assert "manifest.json" not in names
        assert names <= OUTPUTS - {"manifest.json"}, f"temp files left behind: {names - OUTPUTS}"

    def test_successful_build_leaves_manifest(self, feed_zip, out_dir):
        for name in OUTPUTS:
            (out_dir / name).write_text('{"old": true}', encoding="utf-8")
        build(feed_zip, out_dir, today="20261003")
        assert read_json_strict(out_dir / "manifest.json")["feed_version"] == "TEST_V1"

    # --- D11: no leftovers of any name (temp names are not fixed) ----------
    def test_no_leftovers_after_success_including_hidden(self, feed_zip, out_dir):
        build(feed_zip, out_dir, today="20261003")
        assert sorted(p.name for p in out_dir.iterdir()) == sorted(OUTPUTS)

    def test_no_leftovers_after_failure_including_hidden(self, feed_zip, out_dir, monkeypatch):
        patch_build_stop_stats(monkeypatch, boom)
        with pytest.raises(Boom):
            build(feed_zip, out_dir, today="20261003")
        assert [p.name for p in out_dir.iterdir()] == []

    # --- D9: bad feed contents --------------------------------------------
    def test_empty_feed_info_raises_value_error(self, tmp_path, out_dir):
        members = {**FEED, "feed_info.txt": FEED["feed_info.txt"].splitlines()[0] + "\n"}
        bad = write_feed(tmp_path / "empty_feed_info.zip", members)
        with pytest.raises(ValueError, match="feed_info"):
            build(bad, out_dir, today="20261003")
        assert list(out_dir.iterdir()) == []

    def test_corrupt_member_data_raises_zip_error(self, tmp_path, out_dir):
        """Zip structure intact (validate_zip passes) but stop_times.txt's compressed bytes
        are garbage -> BadZipFile (CRC) or zlib.error, and nothing is written."""
        bad = write_corrupt_stop_times(tmp_path / "corrupt.zip")
        from scripts.fetch_gtfs import validate_zip
        validate_zip(bad)  # precondition: the corruption is invisible to validate_zip
        with pytest.raises((zipfile.BadZipFile, zlib.error)):
            build(bad, out_dir, today="20261003")
        assert list(out_dir.iterdir()) == []

    def test_does_not_modify_the_source_zip(self, feed_zip, out_dir):
        before = feed_zip.read_bytes()
        build(feed_zip, out_dir, today="20261003")
        assert feed_zip.read_bytes() == before


# ===========================================================================
# main
# ===========================================================================
FAKE_MANIFEST = {
    "feed_version": "TEST_V1", "feed_start": "20260907", "feed_end": "20270103",
    "service_date": "20261007", "source_sha256": "0" * 64,
    "built_at": "2026-10-03T00:00:00+00:00",
    "counts": {"stops": 4, "stop_stats": 2, "trips_on_service_date": 2},
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
                manifest = build(REAL_ZIP, out, today="20261003")
                stats = json.loads((out / "stop_stats.json").read_text(encoding="utf-8"))
                stops = json.loads((out / "stops.json").read_text(encoding="utf-8"))
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
