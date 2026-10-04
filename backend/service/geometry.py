"""service/geometry.py - street-following paths between points, via a Valhalla server.

route_path(points, costing) takes [[lon, lat], ...] and returns a [[lon, lat], ...] path
that follows streets, or None if routing fails (callers then fall back to straight lines).
costing is "pedestrian" for both walks and buses (to ignore vehicle turn restrictions).
"""
import json
import logging
import math
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Free OpenStreetMap-hosted Valhalla (fair use, no key). Point VALHALLA_URL at your own
# instance or any other Valhalla server if you outgrow it.
VALHALLA_URL = os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de/route")
MAX_LOCATIONS = int(os.environ.get("VALHALLA_MAX_LOCATIONS", 10))  # server cap per request (the public one allows 10); longer legs are chunked
TIMEOUT_S = 6
MAX_DETOUR = 3.0     # reject a routed path more than 3x longer than the straight stop-to-stop line

_cache: dict[tuple, list | None] = {}  # successful results only


def _decode_polyline(shape: str, precision: int = 6) -> list[list[float]]:
    """Decode an encoded polyline (Valhalla uses precision 6) to [[lon, lat], ...]."""
    factor = 10 ** precision
    coords, index, lat, lon = [], 0, 0, 0
    while index < len(shape):
        for axis in (0, 1):
            result, shift = 0, 0
            while True:
                b = ord(shape[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coords.append([lon / factor, lat / factor])
    return coords


def _length_m(path: list[list[float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(path, path[1:]):
        dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
        dy = (lat2 - lat1) * 110_540
        total += math.hypot(dx, dy)
    return total


def _route_chunk(points: list[list[float]], costing: str) -> list[list[float]]:
    last = len(points) - 1
    body = {
        "locations": [
            {"lat": p[1], "lon": p[0], "type": "break" if i in (0, last) else "through"}
            for i, p in enumerate(points)
        ],
        "costing": costing,
    }
    req = urllib.request.Request(
        VALHALLA_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "headway-app/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        # Valhalla explains rejections in the body, e.g. {"error_code":171,"error":"No suitable edges near location"}
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    path: list[list[float]] = []
    for leg in data["trip"]["legs"]:
        path.extend(_decode_polyline(leg["shape"]))
    return path


def _dedupe(points: list[list[float]]) -> list[list[float]]:
    """Drop consecutive identical points (a repeated stop makes Valhalla reject the request)."""
    out: list[list[float]] = []
    for p in points:
        if not out or (round(p[0], 6), round(p[1], 6)) != (round(out[-1][0], 6), round(out[-1][1], 6)):
            out.append(p)
    return out


def _route_points(chunk: list[list[float]], costing: str) -> list[list[float]] | None:
    """Route a chunk in one request. If that fails, route stop to stop so a single bad stop
    only costs one straight segment instead of the whole leg. None if nothing could be routed."""
    try:
        return _route_chunk(chunk, costing)
    except Exception as e:
        logger.warning("routing failed (%s, %d points): %s", costing, len(chunk), e)
    if len(chunk) <= 2:
        return None

    path: list[list[float]] = []
    routed = 0
    for a, b in zip(chunk, chunk[1:]):
        try:
            seg = _route_chunk([a, b], costing)
            routed += 1
        except Exception as e:
            logger.warning("segment %s -> %s unroutable (%s): %s", a, b, costing, e)
            seg = [a, b]  # straight line for just this hop
        if path and seg and path[-1] == seg[0]:
            seg = seg[1:]
        path.extend(seg)
    return path if routed else None


def route_path(points: list[list[float]], costing: str) -> list[list[float]] | None:
    """Street-following path through points in order, or None on any failure."""
    points = _dedupe(points)
    if len(points) < 2:
        return None
    key = (costing, tuple((round(x, 6), round(y, 6)) for x, y in points))
    if key in _cache:
        return _cache[key]

    path: list[list[float]] = []
    step = MAX_LOCATIONS - 1
    for i in range(0, len(points) - 1, step):
        chunk = points[i:i + MAX_LOCATIONS]
        if len(chunk) < 2:
            break
        part = _route_points(chunk, costing)
        if part is None:
            return None
        if path and part and path[-1] == part[0]:
            part = part[1:]  # chunks share an endpoint
        path.extend(part)

    if len(path) < 2 or _length_m(path) > MAX_DETOUR * max(_length_m(points), 1.0):
        logger.warning("discarding implausible routed path (%s, %d points)", costing, len(points))
        return None

    _cache[key] = path
    return path