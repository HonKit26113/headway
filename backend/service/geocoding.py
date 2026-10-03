"""Address -> point via Nominatim, rate-limited and cached. See CONTRACT.md (Phase E)."""
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Headway/0.1 (+https://github.com/Olisaemeka-Paul-Ani/Headway)"
METRO_VAN_BBOX = (48.9, 49.6, -123.5, -122.2)  # lat_min, lat_max, lon_min, lon_max
MIN_INTERVAL_S = 1.0
CACHE_SIZE = 1024
LOCK_WAIT_S = 8.0  # beyond this a request gives up instead of queueing
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")  # control chars except \t \n \v \f \r


class GeocoderUnavailable(Exception):
    pass


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    display_name: str


_lock = threading.Lock()          # one Nominatim request at a time, >= MIN_INTERVAL_S apart
_cache_lock = threading.Lock()    # guards _cache (shared by the server's worker threads)
_last_request = -math.inf
_cache: "OrderedDict[str, GeoResult | None]" = OrderedDict()


def reset() -> None:
    """Clear the cache and rate-limit state."""
    global _last_request
    with _cache_lock:
        _cache.clear()
    _last_request = -math.inf


def _cached(key: str):
    """(True, value) on a cache hit, else (False, None)."""
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return True, _cache[key]
    return False, None


def _remember(key: str, value) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def _clean(text: str) -> str:
    """Drop control characters (whitespace ones become spaces) and collapse whitespace."""
    return " ".join(_CONTROL.sub("", text).split())


def _in_bbox(lat: float, lon: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = METRO_VAN_BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _request(query: str, key: str):
    """One rate-limited Nominatim call (or a cache hit that arrived while waiting).

    Returns ("hit", value) or ("fresh", parsed_json). Failures -> GeocoderUnavailable, never naming the address.
    """
    global _last_request
    lat_min, lat_max, lon_min, lon_max = METRO_VAN_BBOX
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "ca",
        "viewbox": f"{lon_min},{lat_max},{lon_max},{lat_min}",
        "bounded": 1,
    }
    if not _lock.acquire(timeout=LOCK_WAIT_S):
        raise GeocoderUnavailable("geocoder busy")
    try:
        hit, value = _cached(key)  # someone may have looked this address up while we waited
        if hit:
            return "hit", value
        wait = _last_request + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        try:
            resp = requests.get(
                NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT},
                timeout=5, allow_redirects=False,
            )
        except requests.RequestException as e:
            raise GeocoderUnavailable(f"geocoder request failed: {type(e).__name__}") from None
        if resp.status_code != 200:
            raise GeocoderUnavailable(f"geocoder returned HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:  # requests' JSONDecodeError is a ValueError too
            raise GeocoderUnavailable("geocoder returned invalid JSON") from None
        if not isinstance(data, list):
            raise GeocoderUnavailable("geocoder returned unexpected JSON")
        return "fresh", data
    finally:
        _lock.release()


def _parse(results: list) -> GeoResult | None:
    if not results or not isinstance(results[0], dict):
        return None
    top = results[0]
    try:
        lat, lon = float(top["lat"]), float(top["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and _in_bbox(lat, lon)):
        return None
    name = top.get("display_name")
    return GeoResult(lat, lon, _clean(name)[:200] if isinstance(name, str) else "")


def geocode(address: str) -> GeoResult | None:
    """Address -> point in Metro Vancouver, or None if not found. Raises GeocoderUnavailable on outages."""
    if not isinstance(address, str):
        return None
    query = _clean(address)
    if not 3 <= len(query) <= 200:
        return None
    key = query.casefold()
    hit, value = _cached(key)
    if hit:
        return value
    kind, payload = _request(query, key)
    if kind == "hit":
        return payload
    result = _parse(payload)
    _remember(key, result)
    return result
