"""service/tracks.py - rail geometry from GTFS shapes.txt.

track_path(line, first, last) returns the stretch of track between two stops as
[[lon, lat], ...], or None if shapes aren't available (callers then draw stop to stop).

Only the shapes of RAIL_LINES are loaded, once, on first use. Call preload() at
startup to avoid that delay on the first request.
"""
import logging
import math
import os
import threading
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# TODO: folder that contains your GTFS routes.txt, trips.txt and shapes.txt
GTFS_ZIP = Path(os.environ.get("GTFS_ZIP", "data/raw/google_transit.zip"))

# Lines that run on their own track/water, not on roads. Labels are route_short_name,
# or route_long_name when there is no short name (same as the rest of the app).
RAIL_LINES = {"Expo Line", "Millennium Line", "Canada Line", "WCE", "SeaBus"}

MAX_STOP_TO_TRACK_M = 150  # a stop farther than this from a shape isn't on that shape
MAX_DETOUR = 3.0           # reject a cut that is >3x the straight line between the two stops

_lock = threading.Lock()
_shapes_by_line: dict[str, list[np.ndarray]] | None = None  # label -> [array (n, 2) of lon, lat]
_cache: dict[tuple, list | None] = {}


def _load() -> dict[str, list[np.ndarray]]:
    import zipfile
    with zipfile.ZipFile(GTFS_ZIP) as zf:
        routes = pd.read_csv(zf.open("routes.txt"), dtype=str, keep_default_na=False)
        short = routes["route_short_name"].str.strip()
        long = routes["route_long_name"].str.strip()
        routes["label"] = short.where(short != "", long)
        routes = routes[routes["label"].isin(RAIL_LINES)]
        label_of = dict(zip(routes["route_id"].str.strip(), routes["label"]))

        trips = pd.read_csv(zf.open("trips.txt"), dtype=str, keep_default_na=False,
                            usecols=["route_id", "shape_id"])
        trips["route_id"] = trips["route_id"].str.strip()
        trips = trips[trips["route_id"].isin(label_of) & (trips["shape_id"] != "")].drop_duplicates()

        ids_by_label: dict[str, set] = defaultdict(set)
        for rid, sid in zip(trips["route_id"], trips["shape_id"]):
            ids_by_label[label_of[rid]].add(sid)
        wanted = set().union(*ids_by_label.values()) if ids_by_label else set()
        if not wanted:
            return {}

        parts = []  # shapes.txt is large: read in chunks and keep only the rail shapes
        cols = ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]
        for chunk in pd.read_csv(zf.open("shapes.txt"), dtype={"shape_id": str}, usecols=cols,
                                 chunksize=200_000):
            chunk = chunk[chunk["shape_id"].isin(wanted)]
            if len(chunk):
                parts.append(chunk)
        if not parts:
            return {}

    df = pd.concat(parts).sort_values(["shape_id", "shape_pt_sequence"])
    arrays = {sid: g[["shape_pt_lon", "shape_pt_lat"]].to_numpy(dtype=float)
              for sid, g in df.groupby("shape_id")}
    return {label: [arrays[s] for s in sorted(sids) if s in arrays]
            for label, sids in ids_by_label.items()}


def _get_shapes() -> dict[str, list[np.ndarray]]:
    global _shapes_by_line
    if _shapes_by_line is None:
        with _lock:
            if _shapes_by_line is None:
                try:
                    _shapes_by_line = _load()
                    logger.info("loaded rail shapes: %s",
                                {k: len(v) for k, v in _shapes_by_line.items()})
                except Exception as e:  # missing file/column etc.: rail falls back to stop to stop
                    logger.warning("could not load rail shapes from %s: %s", GTFS_ZIP, e)
                    _shapes_by_line = {}
    return _shapes_by_line


preload = _get_shapes


def _length_m(path) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(path, path[1:]):
        dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
        dy = (lat2 - lat1) * 110_540
        total += math.hypot(dx, dy)
    return total


def _project(shape: np.ndarray, lonlat) -> tuple[int, float, float, list[float]]:
    """Nearest point on the polyline: (segment index, t along segment, distance in m, [lon, lat])."""
    lon0, lat0 = lonlat
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_540
    xy = np.column_stack(((shape[:, 0] - lon0) * kx, (shape[:, 1] - lat0) * ky))
    a, ab = xy[:-1], xy[1:] - xy[:-1]
    denom = (ab ** 2).sum(axis=1)
    denom[denom == 0] = 1e-9
    t = np.clip(-(a * ab).sum(axis=1) / denom, 0.0, 1.0)
    closest = a + ab * t[:, None]
    d = np.hypot(closest[:, 0], closest[:, 1])
    k = int(d.argmin())
    p = shape[k] + (shape[k + 1] - shape[k]) * t[k]
    return k, float(t[k]), float(d[k]), [float(p[0]), float(p[1])]


def _slice(shape: np.ndarray, p1, p2) -> list[list[float]]:
    """Track between two projected points, in travel order (either direction along the shape)."""
    k1, t1, _, pt1 = p1
    k2, t2, _, pt2 = p2
    if (k1, t1) <= (k2, t2):
        middle = shape[k1 + 1:k2 + 1]
    else:
        middle = shape[k2 + 1:k1 + 1][::-1]
    return [pt1] + [[float(x), float(y)] for x, y in middle] + [pt2]


def track_path(line: str, first: list[float], last: list[float]) -> list[list[float]] | None:
    """Track from `first` to `last` ([lon, lat] stops) on `line`, or None if unavailable."""
    key = (line, round(first[0], 6), round(first[1], 6), round(last[0], 6), round(last[1], 6))
    if key in _cache:
        return _cache[key]

    best = None
    for shape in _get_shapes().get(line, []):
        if len(shape) < 2:
            continue
        p1, p2 = _project(shape, first), _project(shape, last)
        if max(p1[2], p2[2]) > MAX_STOP_TO_TRACK_M:
            continue  # this branch/variant doesn't serve both stops
        score = p1[2] + p2[2]
        if best is None or score < best[0]:
            best = (score, shape, p1, p2)
    if best is None:
        return None

    _, shape, p1, p2 = best
    path = _slice(shape, p1, p2)
    if _length_m(path) > MAX_DETOUR * max(_length_m([first, last]), 1.0):
        logger.warning("discarding implausible track cut for %s", line)
        return None

    _cache[key] = path
    return path