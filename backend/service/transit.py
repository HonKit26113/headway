"""Runtime lookups over the built JSON artifacts: what BE1's scoring calls. See CONTRACT.md (Phase E)."""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import config

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_RADIUS_M = 1000
MAX_RADIUS_M = 2000
FALLBACK_KMH = 20
EARTH_R = 6371000.0


@dataclass(frozen=True)
class Stop:
    stop_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class StopStats:
    headway_min: float | None
    departures_per_hour: float
    trips_per_day: int
    last_departure_min: int
    last_departure_label: str
    late_trips_after_23: int


@dataclass(frozen=True, eq=False)
class _State:
    stops: dict[str, Stop] = field(default_factory=dict)
    ids: np.ndarray = field(default_factory=lambda: np.array([], dtype=object))
    lat: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    lon: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    stats: dict[str, StopStats] = field(default_factory=dict)
    commute: dict[str, dict[str, float]] = field(default_factory=dict)
    manifest: dict | None = None

    @property
    def fallback(self) -> bool:
        return self.manifest is None


_state: _State | None = None


def _haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _finite(x) -> float:
    """float(x), refusing NaN/Infinity (JSON allows them) so no lookup ever returns nan/inf."""
    v = float(x)
    if not math.isfinite(v):
        raise ValueError("non-finite number in artifact")
    return v


def _parse_stops(raw) -> dict[str, Stop]:
    if not isinstance(raw, dict):
        raise ValueError("stops.json must be an object")
    stops = {}
    for sid, row in raw.items():
        name, lat, lon = row  # wrong shape -> ValueError/TypeError
        stops[str(sid)] = Stop(str(sid), str(name), _finite(lat), _finite(lon))
    return stops


def _parse_stats(raw) -> dict[str, StopStats]:
    if not isinstance(raw, dict):
        raise ValueError("stop_stats.json must be an object")
    return {
        str(sid): StopStats(
            headway_min=None if row["headway_min"] is None else _finite(row["headway_min"]),
            departures_per_hour=_finite(row["departures_per_hour"]),
            trips_per_day=int(row["trips_per_day"]),
            last_departure_min=int(row["last_departure_min"]),
            last_departure_label=str(row["last_departure_label"]),
            late_trips_after_23=int(row["late_trips_after_23"]),
        )
        for sid, row in raw.items()
    }


def _parse_commute(raw) -> dict[str, dict]:
    if not isinstance(raw, dict):
        raise ValueError("commute file must be an object")
    out = {}
    for sid, m in raw.items():
        if isinstance(m, dict):
            out[str(sid)] = {"minutes": _finite(m["minutes"]), "routes": [str(r) for r in m.get("routes", [])]}
        else:
            out[str(sid)] = {"minutes": _finite(m), "routes": []}
            
    if any(m["minutes"] < 0 for m in out.values()):
        raise ValueError("negative commute")
    return out


def _with_stops(stops: dict[str, Stop], **kw) -> _State:
    ids = sorted(stops)
    return _State(
        stops=stops,
        ids=np.array(ids, dtype=object),
        lat=np.array([stops[s].lat for s in ids], dtype=float),
        lon=np.array([stops[s].lon for s in ids], dtype=float),
        **kw,
    )


def load(data_dir: Path | str | None = None) -> None:
    """(Re)load artifacts (default: DATA_DIR at call time); any problem -> fallback mode. Never raises."""
    global _state
    data_dir = Path(DATA_DIR if data_dir is None else data_dir)
    try:
        stops = _parse_stops(_read_json(data_dir / "stops.json"))
    except (OSError, ValueError, TypeError, RecursionError):
        stops = {}
    try:
        manifest = _read_json(data_dir / "manifest.json")
        stats = _parse_stats(_read_json(data_dir / "stop_stats.json"))
        if set(manifest["campuses"]) != set(config.CAMPUS_COORDS):
            raise ValueError("manifest campuses differ from config")  # also keeps odd names out of paths
        commute = {
            name: _parse_commute(_read_json(data_dir / f"commute_{name}.json"))
            for name in config.CAMPUS_COORDS
        }
        if not stops:
            raise ValueError("no stops")
        state = _with_stops(stops, stats=stats, commute=commute, manifest=manifest)
    except Exception:  # any bad content -> fallback; load() must never take the server down
        state = _with_stops(stops)  # fallback: distance-only estimates
    _state = state


def reset() -> None:
    """Forget loaded data; the next lookup auto-loads DATA_DIR."""
    global _state
    _state = None


def _current() -> _State:
    if _state is None:
        load()
    return _state


def _real(x) -> bool:
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, (bool, np.bool_)) and math.isfinite(x)


def nearest_stops(lat: float, lon: float, radius_m: float = DEFAULT_RADIUS_M, k: int | None = None) -> list[tuple[Stop, float]]:
    """Every stop within radius_m of (lat, lon), closest first, as (Stop, walk_m)."""
    if not (_real(lat) and _real(lon)):
        raise ValueError("lat and lon must be finite numbers")
    if not _real(radius_m):
        raise ValueError("radius_m must be a finite number")
    if k is not None and (isinstance(k, (bool, np.bool_)) or not isinstance(k, (int, np.integer)) or k < 1):
        raise ValueError("k must be an int >= 1 or None")
    lat, lon = float(lat), float(lon)  # numpy float32 input would drag the maths down to 32-bit precision
    radius = min(max(float(radius_m), 0.0), MAX_RADIUS_M)
    s = _current()
    if not len(s.ids):
        return []
    d = _haversine_m(lat, lon, s.lat, s.lon)
    hits = np.nonzero(d <= radius)[0]
    order = hits[np.argsort(d[hits], kind="stable")]  # ids are sorted, so ties stay in stop_id order
    if k is not None:
        order = order[:k]
    return [(s.stops[s.ids[i]], float(d[i])) for i in order]


def stop_stats(stop_id: str) -> StopStats | None:
    """Weekday service summary for a stop; None if unknown or no weekday service."""
    return _current().stats.get(stop_id)


def _commute_entry(s, stop_id: str, campus: str) -> dict | None:
    """{"minutes": float, "routes": [str, ...]} for a stop, or None if unknown/unreachable."""
    entry = s.commute.get(campus, {}).get(stop_id)
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry
    return {"minutes": float(entry), "routes": []}  # older files stored a bare number


def commute_minutes(stop_id: str, campus: str) -> float | None:
    """Minutes from stop to campus; None if unknown stop or unreachable."""
    if campus not in config.CAMPUS_COORDS:
        raise ValueError(f"unknown campus {campus!r}")
    s = _current()
    if not s.fallback:
        entry = _commute_entry(s, stop_id, campus)
        return entry["minutes"] if entry else None
    stop = s.stops.get(stop_id)
    if stop is None:
        return None
    lat0, lon0 = config.CAMPUS_COORDS[campus]
    km = float(_haversine_m(stop.lat, stop.lon, lat0, lon0)) / 1000
    return round(km / FALLBACK_KMH * 60, 1)


def commute_routes(stop_id: str, campus: str) -> list[str] | None:
    """Lines to take from stop to campus, in order, e.g. ["Expo Line", "145"].

    [] means the stop is within walking distance of campus. None means the stop
    is unknown or unreachable, or the app is in fallback mode (no route data).
    """
    if campus not in config.CAMPUS_COORDS:
        raise ValueError(f"unknown campus {campus!r}")
    s = _current()
    if s.fallback:
        return None
    entry = _commute_entry(s, stop_id, campus)
    return entry["routes"] if entry else None


def data_status() -> dict:
    """What's loaded: real artifacts or fallback estimates."""
    s = _current()
    m = s.manifest or {}
    return {
        "gtfs_loaded": not s.fallback,
        "fallback": s.fallback,
        "feed_version": m.get("feed_version"),
        "service_date": m.get("service_date"),
        "stops": len(s.stops),
    }
