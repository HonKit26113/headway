"""Turn the raw GTFS zip into small JSON artifacts the server loads. See CONTRACT.md."""
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:  # allow `python scripts/build_artifacts.py` from anywhere
    sys.path.insert(0, str(BACKEND))

from scripts.fetch_gtfs import UnsafeZipError, validate_zip  # noqa: E402
from service import gtfs  # noqa: E402

RAW_ZIP = BACKEND / "data" / "raw" / "google_transit.zip"
OUT_DIR = BACKEND / "data"
OUTPUTS = ("stops.json", "stop_stats.json", "manifest.json")  # manifest last = set is complete
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
        (out_dir / OUTPUTS[-1]).unlink(missing_ok=True)
        for name in OUTPUTS:
            os.replace(temps[name], out_dir / name)
    finally:
        for tmp in temps.values():
            tmp.unlink(missing_ok=True)


def build(zip_path: Path, out_dir: Path, *, today: str | None = None) -> dict:
    """Validate the feed, compute stops + per-stop stats, write the JSON artifacts."""
    zip_path, out_dir = Path(zip_path), Path(out_dir)
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
        service_ids = gtfs.active_service_ids(zf, service_date)
        wanted = {"trip_id", "stop_id", "departure_time", "pickup_type"}
        stop_times = gtfs.read_table(zf, "stop_times.txt", usecols=lambda c: c in wanted)
        stop_times["departure_s"] = gtfs.parse_gtfs_times(stop_times.pop("departure_time"))
        stats = gtfs.build_stop_stats(stop_times, trips, service_ids)

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
        "counts": {
            "stops": len(stops_doc),
            "stop_stats": len(stats),
            "trips_on_service_date": int(trips["service_id"].isin(service_ids).sum()),
        },
    }
    _write_all(out_dir, {"stops.json": stops_doc, "stop_stats.json": stats, "manifest.json": manifest})
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
