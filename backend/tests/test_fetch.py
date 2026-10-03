"""Tests for scripts/fetch_gtfs.py — written from CONTRACT.md "Build-time" section.

Offline only: HTTP is faked by monkeypatching requests.get; zips are built in tmp_path.
"""
from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest
import requests

from scripts import fetch_gtfs
from scripts.fetch_gtfs import DownloadError, UnsafeZipError, download, validate_zip


# --------------------------------------------------------------------------- helpers


def _snapshot(d: Path) -> set[str]:
    return {str(p.relative_to(d)) for p in d.rglob("*")}


def _part(dest: Path) -> Path:
    return Path(str(dest) + ".part")


class FakeResponse:
    """Minimal stand-in for requests.Response, streaming-friendly.

    Works with `with requests.get(...) as r:` and with plain assignment.
    """

    def __init__(
        self,
        body: bytes = b"",
        status_code: int = 200,
        headers=None,
        chunk: int = 1024,
        url: str = "https://example.test/feed.zip",
        raise_after: int | None = None,
    ):
        self._body = body
        self.status_code = status_code
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self._chunk = chunk
        self.closed = False
        self.url = url  # final URL after redirects (Decision 4)
        self.raw = None
        # if set: raise requests.ConnectionError after yielding this many chunks (Decision 9)
        self._raise_after = raise_after

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)

    def iter_content(self, chunk_size: int | None = 1, decode_unicode: bool = False):
        size = chunk_size or self._chunk
        for n, i in enumerate(range(0, len(self._body), size)):
            if self._raise_after is not None and n >= self._raise_after:
                raise requests.ConnectionError("connection reset mid-stream")
            yield self._body[i : i + size]
        if self._raise_after is not None:
            raise requests.ConnectionError("connection reset mid-stream")

    @property
    def content(self) -> bytes:  # in case impl reads .content (it shouldn't for big files)
        return self._body

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def fake_get(monkeypatch):
    """Install a fake requests.get. Returns a controller: set .response, read .calls."""

    class Ctl:
        response = FakeResponse(b"")
        calls: list = []
        exc: BaseException | None = None  # if set, requests.get raises it

    ctl = Ctl()
    ctl.calls = []

    def _get(url, *args, **kwargs):
        ctl.calls.append((url, args, kwargs))
        if ctl.exc is not None:
            raise ctl.exc
        return ctl.response

    monkeypatch.setattr(requests, "get", _get)
    # in case the module did `from requests import get`
    if hasattr(fetch_gtfs, "get"):
        monkeypatch.setattr(fetch_gtfs, "get", _get)
    return ctl


URL = "https://gtfs-static.example.test/gtfs/google_transit.zip"


# --------------------------------------------------------------------------- validate_zip


def test_validate_zip_accepts_valid_zip_with_both_calendars(make_gtfs_zip):
    path = make_gtfs_zip()
    assert validate_zip(path) is None


def test_validate_zip_accepts_only_calendar_dates(make_gtfs_zip):
    path = make_gtfs_zip(calendar=("calendar_dates.txt",))
    assert validate_zip(path) is None


def test_validate_zip_accepts_only_calendar(make_gtfs_zip):
    path = make_gtfs_zip(calendar=("calendar.txt",))
    assert validate_zip(path) is None


@pytest.mark.parametrize("missing", ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt"])
def test_validate_zip_rejects_missing_required_member(make_gtfs_zip, missing):
    path = make_gtfs_zip(omit=(missing,))
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


def test_validate_zip_rejects_no_calendar_member(make_gtfs_zip):
    path = make_gtfs_zip(calendar=())
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


def test_validate_zip_rejects_html_bytes(tmp_path):
    path = tmp_path / "google_transit.zip"
    path.write_bytes(b"<!DOCTYPE html><html><body>503 Service Unavailable</body></html>")
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


def test_validate_zip_rejects_empty_file(tmp_path):
    path = tmp_path / "google_transit.zip"
    path.write_bytes(b"")
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


@pytest.mark.parametrize(
    "bad_name",
    [
        "/abs.txt",
        "/etc/passwd",
        "../evil.txt",
        "data/../../evil.txt",
        "a\\b.txt",
        "..\\evil.txt",
    ],
)
def test_validate_zip_rejects_unsafe_member_name(make_gtfs_zip, bad_name):
    path = make_gtfs_zip(extra=[(bad_name, b"pwned", zipfile.ZIP_STORED)])
    # sanity: the forged name really is stored verbatim
    with zipfile.ZipFile(path) as zf:
        assert bad_name in zf.namelist()
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


def test_validate_zip_rejects_member_over_max_member_bytes(make_gtfs_zip):
    # stored (ratio 1.0) so only the size rule can trip
    path = make_gtfs_zip(extra=[("shapes.txt", b"x" * 2000, zipfile.ZIP_STORED)])
    with pytest.raises(UnsafeZipError):
        validate_zip(path, max_member_bytes=1000)


def test_validate_zip_accepts_member_under_max_member_bytes(make_gtfs_zip):
    path = make_gtfs_zip(extra=[("shapes.txt", b"x" * 500, zipfile.ZIP_STORED)])
    assert validate_zip(path, max_member_bytes=1000) is None


def test_validate_zip_rejects_high_compression_ratio(make_gtfs_zip):
    # 200 KB of '0' deflates to a few hundred bytes -> ratio in the hundreds
    path = make_gtfs_zip(extra=[("shapes.txt", b"0" * 200_000, zipfile.ZIP_DEFLATED)])
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("shapes.txt")
        assert info.file_size / info.compress_size > 50  # sanity on the fixture
    with pytest.raises(UnsafeZipError):
        validate_zip(path, max_ratio=10.0)


def test_validate_zip_rejects_zip_bomb_with_default_ratio(make_gtfs_zip):
    # ~1 MB of zeros deflates >100x; default max_ratio=100 must reject it
    path = make_gtfs_zip(extra=[("shapes.txt", b"0" * 1_000_000, zipfile.ZIP_DEFLATED)])
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("shapes.txt")
        assert info.file_size / info.compress_size > 100  # sanity on the fixture
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


def test_validate_zip_does_not_write_files_valid(make_gtfs_zip):
    path = make_gtfs_zip()
    root = path.parent.parent
    before = _snapshot(root)
    validate_zip(path)
    assert _snapshot(root) == before


def test_validate_zip_does_not_write_files_zip_slip(make_gtfs_zip):
    path = make_gtfs_zip(extra=[("../evil.txt", b"pwned", zipfile.ZIP_STORED)])
    root = path.parent.parent
    before = _snapshot(root)
    with pytest.raises(UnsafeZipError):
        validate_zip(path)
    assert _snapshot(root) == before
    assert not (path.parent.parent / "evil.txt").exists()


# --------------------------------------------------------------------------- download


def test_download_returns_sha256_and_writes_dest(tmp_path, fake_get):
    body = os.urandom(50_000)
    fake_get.response = FakeResponse(body, 200, {"Content-Length": str(len(body))})
    dest = tmp_path / "google_transit.zip"
    digest = download(URL, dest)
    assert digest == hashlib.sha256(body).hexdigest()
    assert dest.read_bytes() == body
    assert not _part(dest).exists()
    assert len(fake_get.calls) == 1
    assert fake_get.calls[0][0] == URL


def test_download_sha256_is_lowercase_hex(tmp_path, fake_get):
    fake_get.response = FakeResponse(b"hello", 200)
    digest = download(URL, tmp_path / "f.zip")
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


def test_download_passes_timeout_and_streams(tmp_path, fake_get):
    fake_get.response = FakeResponse(b"abc", 200)
    download(URL, tmp_path / "f.zip", timeout=7)
    _, _, kwargs = fake_get.calls[0]
    assert kwargs.get("timeout") == 7
    assert kwargs.get("stream") is True
    assert kwargs.get("verify", True) is not False


@pytest.mark.parametrize("status", [404, 500, 503, 301])
def test_download_non_2xx_raises_and_leaves_nothing(tmp_path, fake_get, status):
    fake_get.response = FakeResponse(b"<html>error</html>", status)
    dest = tmp_path / "google_transit.zip"
    with pytest.raises(DownloadError):
        download(URL, dest)
    assert not dest.exists()
    assert not _part(dest).exists()
    assert _snapshot(tmp_path) == set()


def test_download_over_max_bytes_raises_and_leaves_nothing(tmp_path, fake_get):
    body = b"z" * 5000
    fake_get.response = FakeResponse(body, 200)  # no Content-Length: must count bytes
    dest = tmp_path / "google_transit.zip"
    with pytest.raises(DownloadError):
        download(URL, dest, max_bytes=1000)
    assert not dest.exists()
    assert not _part(dest).exists()
    assert _snapshot(tmp_path) == set()


def test_download_over_max_bytes_with_lying_content_length(tmp_path, fake_get):
    body = b"z" * 5000
    fake_get.response = FakeResponse(body, 200, {"Content-Length": "10"})
    dest = tmp_path / "google_transit.zip"
    with pytest.raises(DownloadError):
        download(URL, dest, max_bytes=1000)
    assert not dest.exists()
    assert not _part(dest).exists()


def test_download_exactly_max_bytes_ok(tmp_path, fake_get):
    body = b"z" * 1000
    fake_get.response = FakeResponse(body, 200)
    dest = tmp_path / "f.zip"
    assert download(URL, dest, max_bytes=1000) == hashlib.sha256(body).hexdigest()
    assert dest.read_bytes() == body


def test_download_failure_does_not_modify_existing_dest(tmp_path, fake_get):
    dest = tmp_path / "google_transit.zip"
    dest.write_bytes(b"OLD GOOD ZIP")
    fake_get.response = FakeResponse(b"z" * 5000, 200)
    with pytest.raises(DownloadError):
        download(URL, dest, max_bytes=1000)
    assert dest.read_bytes() == b"OLD GOOD ZIP"
    assert not _part(dest).exists()

    fake_get.response = FakeResponse(b"nope", 500)
    with pytest.raises(DownloadError):
        download(URL, dest)
    assert dest.read_bytes() == b"OLD GOOD ZIP"
    assert not _part(dest).exists()


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://gtfs-static.translink.ca/gtfs/google_transit.zip",
        "ftp://example.test/feed.zip",
        "file:///etc/passwd",
        "HTTP://example.test/feed.zip",
        "",
    ],
)
def test_download_rejects_non_https_without_network(tmp_path, fake_get, bad_url):
    dest = tmp_path / "f.zip"
    with pytest.raises(DownloadError):
        download(bad_url, dest)
    assert fake_get.calls == []
    assert not dest.exists()
    assert not _part(dest).exists()


# --------------------------------------------------------------------------- validate_zip: Decisions 1, 2, 8


def test_validate_zip_ratio_exactly_max_ratio_passes(make_gtfs_zip):
    # Decision 1: file_size / compress_size <= max_ratio passes (boundary is inclusive)
    path = make_gtfs_zip(extra=[("shapes.txt", b"0" * 200_000, zipfile.ZIP_DEFLATED)])
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("shapes.txt")
        ratio = info.file_size / info.compress_size
    assert ratio > 1.0  # sanity: the deflated member is the max-ratio member
    assert validate_zip(path, max_ratio=ratio) is None


def test_validate_zip_ratio_exactly_one_stored_passes(make_gtfs_zip):
    # all members STORED -> ratio exactly 1.0 == max_ratio
    path = make_gtfs_zip(extra=[("shapes.txt", b"x" * 500, zipfile.ZIP_STORED)])
    assert validate_zip(path, max_ratio=1.0) is None


@pytest.mark.parametrize("ok_name", ["foo..txt", "a/..b/c.txt", "..hidden", "a/b../c.txt"])
def test_validate_zip_allows_dotdot_inside_name_part(make_gtfs_zip, ok_name):
    # Decision 2: only a '/'-separated part equal to '..' is unsafe
    path = make_gtfs_zip(extra=[(ok_name, b"fine", zipfile.ZIP_STORED)])
    with zipfile.ZipFile(path) as zf:
        assert ok_name in zf.namelist()
    assert validate_zip(path) is None


def _forge_zero_compress_size(path: Path, member: str) -> None:
    """Rewrite `member`'s compressed-size field to 0 in both its local header and its
    central-directory entry, leaving file_size untouched."""
    raw = bytearray(path.read_bytes())
    name = member.encode()
    patched = {"local": 0, "central": 0}
    # local file headers: sig PK\x03\x04, compress_size @18, fname_len @26, fname @30
    pos = 0
    while (pos := raw.find(b"PK\x03\x04", pos)) != -1:
        fn_len = int.from_bytes(raw[pos + 26 : pos + 28], "little")
        if raw[pos + 30 : pos + 30 + fn_len] == name:
            raw[pos + 18 : pos + 22] = (0).to_bytes(4, "little")
            patched["local"] += 1
        pos += 4
    # central directory: sig PK\x01\x02, compress_size @20, fname_len @28, fname @46
    pos = 0
    while (pos := raw.find(b"PK\x01\x02", pos)) != -1:
        fn_len = int.from_bytes(raw[pos + 28 : pos + 30], "little")
        if raw[pos + 46 : pos + 46 + fn_len] == name:
            raw[pos + 20 : pos + 24] = (0).to_bytes(4, "little")
            patched["central"] += 1
        pos += 4
    assert patched == {"local": 1, "central": 1}, patched
    path.write_bytes(bytes(raw))


def test_validate_zip_rejects_zero_compress_size_with_nonzero_file_size(make_gtfs_zip):
    # Decision 8a: compress_size == 0 and file_size > 0 -> UnsafeZipError
    path = make_gtfs_zip(extra=[("shapes.txt", b"x" * 10, zipfile.ZIP_STORED)])
    _forge_zero_compress_size(path, "shapes.txt")
    with zipfile.ZipFile(path) as zf:  # sanity: the forgery is what zipfile reports
        info = zf.getinfo("shapes.txt")
        assert info.compress_size == 0
        assert info.file_size == 10
    with pytest.raises(UnsafeZipError):
        validate_zip(path)


def test_validate_zip_allows_empty_member(make_gtfs_zip):
    # compress_size == 0 with file_size == 0 is a legitimately empty file
    path = make_gtfs_zip(extra=[("feed_info.txt", b"", zipfile.ZIP_STORED)])
    assert validate_zip(path) is None


def _total_size(path: Path) -> int:
    with zipfile.ZipFile(path) as zf:
        return sum(i.file_size for i in zf.infolist())


def test_validate_zip_rejects_total_over_max_total_bytes(make_gtfs_zip):
    # Decision 8b: sum(file_size) > max_total_bytes -> UnsafeZipError, even if each member is small
    path = make_gtfs_zip(
        extra=[
            ("shapes.txt", b"x" * 600, zipfile.ZIP_STORED),
            ("transfers.txt", b"y" * 600, zipfile.ZIP_STORED),
        ]
    )
    total = _total_size(path)
    assert total > 1200
    with pytest.raises(UnsafeZipError):
        validate_zip(path, max_member_bytes=10**9, max_total_bytes=1000)
    with pytest.raises(UnsafeZipError):
        validate_zip(path, max_member_bytes=10**9, max_total_bytes=total - 1)


def test_validate_zip_accepts_total_at_or_under_max_total_bytes(make_gtfs_zip):
    path = make_gtfs_zip(
        extra=[
            ("shapes.txt", b"x" * 600, zipfile.ZIP_STORED),
            ("transfers.txt", b"y" * 600, zipfile.ZIP_STORED),
        ]
    )
    total = _total_size(path)
    assert validate_zip(path, max_member_bytes=10**9, max_total_bytes=total) is None
    assert validate_zip(path, max_member_bytes=10**9, max_total_bytes=total + 10_000) is None


# --------------------------------------------------------------------------- download: Decisions 4, 9


@pytest.mark.parametrize(
    "final_url",
    ["http://gtfs-static.example.test/gtfs/google_transit.zip", "HTTP://example.test/x.zip", "ftp://x/y"],
)
def test_download_rejects_redirect_to_non_https(tmp_path, fake_get, final_url):
    # Decision 4: the FINAL response.url must also start with https://
    fake_get.response = FakeResponse(b"PK whatever", 200, url=final_url)
    dest = tmp_path / "google_transit.zip"
    with pytest.raises(DownloadError):
        download(URL, dest)
    assert not dest.exists()
    assert not _part(dest).exists()
    assert _snapshot(tmp_path) == set()


@pytest.mark.parametrize(
    "exc",
    [
        requests.ConnectionError("dns failure"),
        requests.Timeout("connect timed out"),
        requests.TooManyRedirects("loop"),
        requests.RequestException("generic"),
    ],
)
def test_download_wraps_request_exception_from_get(tmp_path, fake_get, exc):
    # Decision 9
    fake_get.exc = exc
    dest = tmp_path / "google_transit.zip"
    with pytest.raises(DownloadError):
        download(URL, dest)
    assert not dest.exists()
    assert not _part(dest).exists()
    assert _snapshot(tmp_path) == set()


def test_download_wraps_request_exception_mid_stream(tmp_path, fake_get):
    # Decision 9: error during iter_content after some bytes were written
    dest = tmp_path / "google_transit.zip"
    dest.write_bytes(b"OLD GOOD ZIP")
    fake_get.response = FakeResponse(b"z" * 10_000, 200, chunk=1000, raise_after=3)
    with pytest.raises(DownloadError):
        download(URL, dest)
    assert dest.read_bytes() == b"OLD GOOD ZIP"
    assert not _part(dest).exists()
    assert _snapshot(tmp_path) == {"google_transit.zip"}


def test_download_wraps_request_exception_mid_stream_no_existing_dest(tmp_path, fake_get):
    dest = tmp_path / "google_transit.zip"
    fake_get.response = FakeResponse(b"z" * 10_000, 200, chunk=1000, raise_after=2)
    with pytest.raises(DownloadError):
        download(URL, dest)
    assert not dest.exists()
    assert not _part(dest).exists()
    assert _snapshot(tmp_path) == set()


# --------------------------------------------------------------------------- main


def test_dest_constant_is_backend_relative():
    # Decision 6
    expected = Path(fetch_gtfs.__file__).resolve().parents[1] / "data" / "raw" / "google_transit.zip"
    assert fetch_gtfs.DEST == expected


@pytest.fixture
def no_real_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("main() must not hit the network in tests")

    monkeypatch.setattr(requests, "get", _boom)


@pytest.fixture
def tmp_dest(monkeypatch, tmp_path) -> Path:
    """Point fetch_gtfs.DEST into tmp_path so main() never touches the real backend/data/."""
    dest = tmp_path / "data" / "raw" / "google_transit.zip"
    monkeypatch.setattr(fetch_gtfs, "DEST", dest)
    return dest


def _new(dest: Path) -> Path:
    return Path(str(dest) + ".new")


def _gtfs_bytes(make_gtfs_zip, **kw) -> bytes:
    return make_gtfs_zip(**kw).read_bytes()


def test_main_success_prints_exact_line(monkeypatch, capsys, no_real_network, tmp_dest):
    body = b"PK fake zip bytes"
    calls = {"download": [], "validate": []}

    def fake_download(url, dest, *a, **k):
        dest = Path(dest)
        calls["download"].append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return hashlib.sha256(body).hexdigest()

    def fake_validate(path, *a, **k):
        calls["validate"].append(Path(path))
        return None

    monkeypatch.setattr(fetch_gtfs, "download", fake_download)
    monkeypatch.setattr(fetch_gtfs, "validate_zip", fake_validate)

    rc = fetch_gtfs.main()

    assert rc == 0
    assert len(calls["download"]) == 1
    url, downloaded_to = calls["download"][0]
    assert url == fetch_gtfs.GTFS_URL
    # whatever download wrote is what gets validated
    assert calls["validate"] == [downloaded_to]
    assert tmp_dest.read_bytes() == body
    n = tmp_dest.stat().st_size
    out = capsys.readouterr().out
    assert out.strip() == f"sha256={hashlib.sha256(body).hexdigest()} size={n}"


@pytest.mark.parametrize(
    "where,exc",
    [
        ("download", DownloadError("HTTP 503 from feed")),
        ("download", OSError(28, "No space left on device")),
        ("download", PermissionError(13, "Permission denied")),
        ("validate", UnsafeZipError("member name '../evil.txt' is unsafe")),
    ],
)
def test_main_failure_returns_1_without_traceback(
    monkeypatch, capsys, no_real_network, tmp_dest, where, exc
):
    # Decision 5: DownloadError, UnsafeZipError and OSError -> 1, stderr message, no traceback
    def fake_download(url, dest, *a, **k):
        if where == "download":
            raise exc
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"PK bytes")
        return "0" * 64

    def fake_validate(path, *a, **k):
        if where == "validate":
            raise exc
        return None

    monkeypatch.setattr(fetch_gtfs, "download", fake_download)
    monkeypatch.setattr(fetch_gtfs, "validate_zip", fake_validate)

    rc = fetch_gtfs.main()

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err.strip(), "failure message must go to stderr"
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_main_bad_feed_does_not_replace_good_dest(monkeypatch, capsys, no_real_network, tmp_dest, make_gtfs_zip):
    # Decision 7: invalid download must leave an existing DEST byte-for-byte unchanged
    good = _gtfs_bytes(make_gtfs_zip)
    tmp_dest.parent.mkdir(parents=True)
    tmp_dest.write_bytes(good)
    html = b"<!DOCTYPE html><html><body>503 Service Unavailable</body></html>"
    seen: list[Path] = []

    def fake_download(url, dest, *a, **k):
        dest = Path(dest)
        seen.append(dest)
        dest.write_bytes(html)
        return hashlib.sha256(html).hexdigest()

    monkeypatch.setattr(fetch_gtfs, "download", fake_download)  # real validate_zip

    rc = fetch_gtfs.main()

    assert rc == 1
    assert tmp_dest.read_bytes() == good
    assert not _new(tmp_dest).exists()
    assert seen and seen[0] != tmp_dest
    err = capsys.readouterr().err
    assert err.strip() and "Traceback" not in err


def test_main_download_error_leaves_good_dest(monkeypatch, capsys, no_real_network, tmp_dest, make_gtfs_zip):
    good = _gtfs_bytes(make_gtfs_zip)
    tmp_dest.parent.mkdir(parents=True)
    tmp_dest.write_bytes(good)

    def fake_download(url, dest, *a, **k):
        raise DownloadError("HTTP 503")

    monkeypatch.setattr(fetch_gtfs, "download", fake_download)
    assert fetch_gtfs.main() == 1
    assert tmp_dest.read_bytes() == good
    assert not _new(tmp_dest).exists()


def test_main_good_feed_is_staged_then_replaces_dest(
    monkeypatch, capsys, no_real_network, tmp_dest, make_gtfs_zip
):
    # Decision 7: download to DEST + ".new", validate that, then os.replace onto DEST
    old = _gtfs_bytes(make_gtfs_zip)
    new = _gtfs_bytes(make_gtfs_zip, extra=[("feed_info.txt", b"feed_publisher_name\nTL\n", zipfile.ZIP_STORED)])
    assert old != new
    tmp_dest.parent.mkdir(parents=True)
    tmp_dest.write_bytes(old)
    seen: list[Path] = []

    def fake_download(url, dest, *a, **k):
        dest = Path(dest)
        seen.append(dest)
        dest.write_bytes(new)
        return hashlib.sha256(new).hexdigest()

    monkeypatch.setattr(fetch_gtfs, "download", fake_download)  # real validate_zip

    rc = fetch_gtfs.main()

    assert rc == 0
    assert len(seen) == 1
    assert seen[0] != tmp_dest
    assert seen[0] == _new(tmp_dest)
    assert tmp_dest.read_bytes() == new
    assert not _new(tmp_dest).exists()
    out = capsys.readouterr().out
    assert out.strip() == f"sha256={hashlib.sha256(new).hexdigest()} size={len(new)}"


def test_main_good_feed_with_no_existing_dest(monkeypatch, capsys, no_real_network, tmp_dest, make_gtfs_zip):
    new = _gtfs_bytes(make_gtfs_zip)

    def fake_download(url, dest, *a, **k):
        Path(dest).write_bytes(new)
        return hashlib.sha256(new).hexdigest()

    monkeypatch.setattr(fetch_gtfs, "download", fake_download)
    assert fetch_gtfs.main() == 0
    assert tmp_dest.read_bytes() == new
    assert not _new(tmp_dest).exists()
