"""Turn the raw GTFS zip into small JSON artifacts the server loads. See CONTRACT.md."""
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:  # allow `python scripts/build_artifacts.py` from anywhere
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from scripts.fetch_gtfs import UnsafeZipError, validate_zip  # noqa: E402
from service import graph, gtfs  # noqa: E402

RAW_ZIP = BACKEND / "data" / "raw" / "google_transit.zip"
OUT_DIR = BACKEND / "data"
MANIFEST = "manifest.json"  # written last: present = complete set
CAMPUS_NAME = re.compile(r"[a-z0-9_]+")  # campus names become file names
WEDNESDAY = 2
LOCAL_TZ = ZoneInfo("America/Vancouver")


def _day(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y%m%d").date()


def pick_service_date(feed_start: str, feed_end: str, today: str) -> str:
    """First Wednesday on/after max(today, feed_start) that is still inside the feed."""
    start = max(_day(today), _day(feed_start))
    wednesday = start + dt.timedelta(days=(WEDNESDAY - start.weekday()) % 7)
    if wednesday > _day(feed_end):
        raise ValueError(f"no Wednesday left between {start:%Y%m%d} and {feed_end}")
    return f"{wednesday:%Y%m%d}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_all(out_dir: Path, docs: dict[str, object]) -> None:
    """Write every doc to a unique temp file, then swap them in with the manifest last.

    The old manifest is removed before the first swap, so a manifest on disk always
    vouches for a complete, matching set (no manifest = building or broken).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    temps: dict[str, Path] = {}
    try:
        for name, doc in docs.items():
            fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{name}.", suffix=".tmp")
            temps[name] = Path(tmp)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, allow_nan=False, sort_keys=True)
            os.chmod(tmp, 0o644)
        (out_dir / MANIFEST).unlink(missing_ok=True)
        for name in [n for n in docs if n != MANIFEST]:
            os.replace(temps[name], out_dir / name)
        for stale in out_dir.glob("commute_*.json"):  # campuses no longer in the set
            if stale.name not in docs:
                stale.unlink()
        os.replace(temps[MANIFEST], out_dir / MANIFEST)
    finally:
        for tmp in temps.values():
            tmp.unlink(missing_ok=True)


def _check_campuses(campuses: dict) -> None:
    """Names become file names and coordinates drive the search, so reject bad ones up front."""
    for name, latlon in campuses.items():
        if not (isinstance(name, str) and CAMPUS_NAME.fullmatch(name)):
            raise ValueError(f"invalid campus name {name!r}: use a-z, 0-9, _")
        if isinstance(latlon, (str, bytes)) or len(latlon) != 2:
            raise ValueError(f"campus {name}: need a (lat, lon) pair")
        lat, lon = latlon
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (lat, lon)):
            raise ValueError(f"campus {name}: lat/lon must be numbers")
        if not (math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180):
            raise ValueError(f"campus {name}: lat/lon out of range")


def build(zip_path: Path, out_dir: Path, *, today: str | None = None, campuses: dict | None = None) -> dict:
    """Validate the feed, compute stops, per-stop stats and commute times, write the JSON artifacts."""
    zip_path, out_dir = Path(zip_path), Path(out_dir)
    campuses = dict(config.CAMPUS_COORDS if campuses is None else campuses)
    _check_campuses(campuses)
    validate_zip(zip_path)
    today = today or f"{dt.datetime.now(LOCAL_TZ):%Y%m%d}"

    with zipfile.ZipFile(zip_path) as zf:
        feed_info = gtfs.read_table(zf, "feed_info.txt")
        if feed_info.empty:
            raise ValueError("feed_info.txt has no rows")
        info = feed_info.iloc[0]
        service_date = pick_service_date(info["feed_start_date"], info["feed_end_date"], today)
        stops = gtfs.load_stops(zf)
        trips = gtfs.load_trips(zf)
        routes = gtfs.read_table(zf, "routes.txt") # <--- Add this!
        service_ids = gtfs.active_service_ids(zf, service_date)
        wanted = {"trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time",
                  "pickup_type", "drop_off_type"}
        stop_times = gtfs.read_table(zf, "stop_times.txt", usecols=lambda c: c in wanted)
        stop_times["arrival_s"] = gtfs.parse_gtfs_times(stop_times.pop("arrival_time"))
        stop_times["departure_s"] = gtfs.parse_gtfs_times(stop_times.pop("departure_time"))
        stats = gtfs.build_stop_stats(stop_times, trips, service_ids)
        commutes = {
            name: graph.commute_from_all_stops(stops, stop_times, trips, routes, service_ids, tuple(latlon))
            for name, latlon in campuses.items()
        }

    stops_doc = {
        sid: [name, lat, lon]
        for sid, name, lat, lon in zip(
            stops["stop_id"], stops["stop_name"], stops["stop_lat"].tolist(), stops["stop_lon"].tolist()
        )
    }
    manifest = {
        "feed_version": info["feed_version"],
        "feed_start": info["feed_start_date"],
        "feed_end": info["feed_end_date"],
        "service_date": service_date,
        "source_sha256": _sha256(zip_path),
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "campuses": {name: [float(lat), float(lon)] for name, (lat, lon) in campuses.items()},
        "counts": {
            "stops": len(stops_doc),
            "stop_stats": len(stats),
            "trips_on_service_date": int(trips["service_id"].isin(service_ids).sum()),
            "commute": {name: len(c) for name, c in commutes.items()},
        },
    }
    docs = {"stops.json": stops_doc, "stop_stats.json": stats}
    docs.update({f"commute_{name}.json": c for name, c in commutes.items()})
    docs[MANIFEST] = manifest
    _write_all(out_dir, docs)
    return manifest


def main() -> int:
    """CLI: build data/raw/google_transit.zip into data/*.json and print a one-line summary."""
    try:
        m = build(RAW_ZIP, OUT_DIR)
    except (UnsafeZipError, zipfile.BadZipFile, zlib.error, ValueError, OSError, LookupError) as e:
        first_line = (str(e).splitlines() or [""])[0]
        print(f"build_artifacts: {type(e).__name__}: {first_line}", file=sys.stderr)
        return 1
    counts = m.get("counts", {})
    print(
        f"built {m.get('feed_version')} for {m.get('service_date')}: "
        f"{counts.get('stops')} stops, {counts.get('stop_stats')} with stats, "
        f"{counts.get('trips_on_service_date')} trips"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
