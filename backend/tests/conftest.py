"""Shared pytest fixtures for Headway BE2 tests.

All zips are built programmatically in tmp_path: no binary fixtures, no network.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable, Iterable

import pytest

REQUIRED = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")

_SMALL = {
    "stops.txt": b"stop_id,stop_name,stop_lat,stop_lon\n1,Main St,49.28,-123.12\n",
    "routes.txt": b"route_id,route_short_name,route_type\nR1,99,3\n",
    "trips.txt": b"route_id,service_id,trip_id\nR1,WK,T1\n",
    "stop_times.txt": b"trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:00:00,08:00:00,1,1\n",
    "calendar.txt": b"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWK,1,1,1,1,1,0,0,20260101,20261231\n",
    "calendar_dates.txt": b"service_id,date,exception_type\nWK,20260704,2\n",
}


def write_zip(
    path: Path,
    members: Iterable[tuple[str, bytes, int]],
) -> Path:
    """Write a zip at `path`. Each member is (name, data, compress_type).

    Uses ZipInfo so arbitrary (malicious) names are stored verbatim.
    """
    with zipfile.ZipFile(path, "w") as zf:
        for name, data, ctype in members:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ctype
            zf.writestr(info, data)
    return path


@pytest.fixture
def make_gtfs_zip(tmp_path: Path) -> Callable[..., Path]:
    """Factory: build a GTFS-ish zip in its own subdir of tmp_path.

    make_gtfs_zip(name="x.zip", calendar=("calendar.txt",), omit=(), extra=[(name, data, ctype)])
    Base members are ZIP_STORED (ratio 1.0) so only `extra` can trip size/ratio checks.
    """
    counter = {"n": 0}

    def _make(
        name: str = "feed.zip",
        *,
        calendar: tuple[str, ...] = ("calendar.txt", "calendar_dates.txt"),
        omit: tuple[str, ...] = (),
        extra: Iterable[tuple[str, bytes, int]] = (),
    ) -> Path:
        counter["n"] += 1
        d = tmp_path / f"zips{counter['n']}"
        d.mkdir()
        members = [
            (m, _SMALL[m], zipfile.ZIP_STORED)
            for m in (*REQUIRED, *calendar)
            if m not in omit
        ]
        members.extend(extra)
        return write_zip(d / name, members)

    return _make
