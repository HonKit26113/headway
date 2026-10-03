"""Download and validate the TransLink GTFS static feed. See CONTRACT.md."""
import hashlib
import os
import sys
import zipfile
from pathlib import Path

import requests

GTFS_URL = os.getenv("GTFS_URL", "https://gtfs-static.translink.ca/gtfs/google_transit.zip")
REQUIRED_MEMBERS = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")
CALENDAR_MEMBERS = ("calendar.txt", "calendar_dates.txt")
DEST = Path(__file__).resolve().parent.parent / "data" / "raw" / "google_transit.zip"
CHUNK_BYTES = 64 * 1024


class UnsafeZipError(Exception):
    pass


class DownloadError(Exception):
    pass


def _unsafe_name(name: str) -> bool:
    """True if a member name is absolute, has a backslash, or a '..' part."""
    return name.startswith("/") or "\\" in name or ".." in name.split("/")


def validate_zip(
    path: Path,
    *,
    max_member_bytes: int = 500 * 1024**2,
    max_ratio: float = 100.0,
    max_total_bytes: int = 1 * 1024**3,
) -> None:
    """Raise UnsafeZipError unless the zip looks like a safe GTFS feed. Reads metadata only."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError) as e:
        raise UnsafeZipError(f"not a readable zip: {e}") from e

    names = {i.filename for i in infos}
    missing = [m for m in REQUIRED_MEMBERS if m not in names]
    if missing:
        raise UnsafeZipError(f"missing required members: {', '.join(missing)}")
    if not any(m in names for m in CALENDAR_MEMBERS):
        raise UnsafeZipError("missing calendar.txt and calendar_dates.txt")

    for info in infos:
        if _unsafe_name(info.filename):
            raise UnsafeZipError(f"unsafe member name {info.filename!r}")
        if info.file_size > max_member_bytes:
            raise UnsafeZipError(f"member {info.filename!r} too large ({info.file_size} bytes)")
        if info.compress_size == 0 and info.file_size > 0:
            raise UnsafeZipError(f"member {info.filename!r} has zero compressed size")
        if info.compress_size > 0 and info.file_size / info.compress_size > max_ratio:
            raise UnsafeZipError(f"member {info.filename!r} compression ratio too high")

    total = sum(i.file_size for i in infos)
    if total > max_total_bytes:
        raise UnsafeZipError(f"total uncompressed size too large ({total} bytes)")


def download(url: str, dest: Path, *, max_bytes: int = 200 * 1024**2, timeout: float = 30) -> str:
    """Stream url to dest (via dest + '.part'); return the hex SHA-256 of the file."""
    if not url.startswith("https://"):
        raise DownloadError("only https:// URLs are allowed")
    dest = Path(dest)
    part = Path(str(dest) + ".part")
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            final_url = getattr(resp, "url", url) or url
            if not str(final_url).startswith("https://"):
                raise DownloadError("redirected to a non-https URL")
            if not 200 <= resp.status_code < 300:
                raise DownloadError(f"HTTP {resp.status_code}")
            received = 0
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_BYTES):
                    received += len(chunk)
                    if received > max_bytes:
                        raise DownloadError(f"response exceeds {max_bytes} bytes")
                    digest.update(chunk)
                    f.write(chunk)
        os.replace(part, dest)
    except requests.RequestException as e:
        part.unlink(missing_ok=True)
        raise DownloadError(f"request failed: {type(e).__name__}") from e
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def main() -> int:
    """CLI: download the feed to DEST + '.new', validate it, then swap it onto DEST."""
    staged = DEST.with_name(DEST.name + ".new")
    try:
        DEST.parent.mkdir(parents=True, exist_ok=True)
        digest = download(GTFS_URL, staged)
        validate_zip(staged)
        os.replace(staged, DEST)
        size = DEST.stat().st_size
    except (DownloadError, UnsafeZipError, OSError) as e:
        staged.unlink(missing_ok=True)
        print(f"fetch_gtfs: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"sha256={digest} size={size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
