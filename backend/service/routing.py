"""Build a GeoJSON FeatureCollection showing the route from an origin to campus.

The frontend renders this with three MapLibre layers:
  - 'route-ride'        solid coloured line for transit legs
  - 'route-ride-casing' dark outline behind ride segments
  - 'route-walk'        dashed white line for walking legs

Each Feature is a LineString with properties:
  type  – "ride" | "walk"
  line  – human-readable line name (ride only), shown on hover
  color – hex colour for the ride segment

Walking legs follow streets (pedestrian routing) and bus legs follow roads through the
stops of the leg. Rail legs follow the track shape from GTFS shapes.txt. If routing or
shapes are unavailable, a leg falls back to the straight line through its stops.
"""
import math
from concurrent.futures import ThreadPoolExecutor

import config
from service.geometry import route_path
from service.tracks import RAIL_LINES, track_path
from service.transit import (
    nearest_stops, commute_minutes, commute_routes,
    stop_latlon, _current, _commute_entry,
)

# Palette for colouring successive ride legs so they're visually distinct.
LEG_COLORS = ["#ff5a2e", "#3b82f6", "#22c55e", "#a855f7", "#eab308", "#ec4899"]

def get_line_color(line: str) -> str:
    """Distinct colors for transport types (buses=blue, RapidBuses=green, trains=real colors)."""
    if line == "Expo Line":
        return "#0033a0"
    elif line == "Millennium Line":
        return "#ffcd00"
    elif line == "Canada Line":
        return "#007c9f"
    elif line == "West Coast Express":
        return "#4c2d7a"
    elif line == "SeaBus":
        return "#746661"
    elif line == "99":
        return "#ff7322"
    elif line.startswith("R") and line[1:].isdigit():
        return "#008522"  # RapidBus Green
    else:
        return "#3b82f6"  # Bus Blue


def _spec(typ, pts, *, line="", color="#ffffff", costing=None, path=None):
    """A line to draw. costing says how to snap it to the street network (None = don't);
    path is ready-made geometry (rail track) that takes priority over routing."""
    return {"typ": typ, "pts": pts, "line": line, "color": color, "costing": costing, "path": path}


def _resolve(spec):
    """Turn a spec into a GeoJSON feature, using a routed path when one is available."""
    path = spec["path"] or (route_path(spec["pts"], spec["costing"]) if spec["costing"] else None)
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": path or spec["pts"]},
        "properties": {"type": spec["typ"], "line": spec["line"], "color": spec["color"]},
    }


def _stops_to_coords(stop_ids: list[str]) -> list[list[float]]:
    """Convert a list of stop IDs to [[lon, lat], ...], skipping unknowns."""
    coords = []
    for sid in stop_ids:
        ll = stop_latlon(sid)
        if ll is not None:
            coords.append([ll[1], ll[0]])  # GeoJSON is [lon, lat]
    return coords


def _apart(a, b, eps=1e-7) -> bool:
    return abs(a[0] - b[0]) > eps or abs(a[1] - b[1]) > eps


def build_route_geojson(origin: tuple, campus: str) -> dict:
    """GeoJSON route from *origin* (lat, lon) to *campus*.

    Uses the precomputed legs data (list of stops per ride/walk segment)
    to draw the path through each transit stop.
    """
    lat, lon = origin
    campus_latlon = config.CAMPUS_COORDS.get(campus)
    if campus_latlon is None:
        return {"type": "FeatureCollection", "features": []}

    campus_lat, campus_lon = campus_latlon
    here = [lon, lat]
    campus_pt = [campus_lon, campus_lat]

    # Find the best stop (shortest commute time) - match scoring.py logic exactly
    stops = nearest_stops(lat, lon, radius_m=300)
    best_stop = None
    best_time = math.inf
    for stop, walk_m in stops:
        t = commute_minutes(stop.stop_id, campus)
        if t is not None and t < best_time:
            best_time = t
            best_stop = stop

    specs = []

    if best_stop is None:
        specs.append(_spec("walk", [here, campus_pt], line="Walk to campus", costing="pedestrian"))
        return {"type": "FeatureCollection", "features": _render(specs)}

    # Get the full commute entry with legs
    s = _current()
    entry = _commute_entry(s, best_stop.stop_id, campus)
    legs = entry.get("legs") if entry else None

    stop_pt = [best_stop.lon, best_stop.lat]

    # Walk from origin to the boarding stop
    if _apart(here, stop_pt):
        specs.append(_spec("walk", [here, stop_pt], line="Walk to stop", costing="pedestrian"))

    last = stop_pt  # where the journey currently ends; the final walk to campus starts here

    if legs:
        # We have full leg data with stop IDs: draw the path through each transit stop
        ride_idx = 0
        for leg in legs:
            coords = _stops_to_coords(leg["stops"])
            if len(coords) < 2:
                continue
            last = coords[-1]

            if leg["type"] == "ride":
                name = leg.get("line", "")
                color = get_line_color(name)
                ride_idx += 1
                rail = name in RAIL_LINES
                specs.append(_spec(
                    "ride", coords, line=name, color=color,
                    costing=None if rail else "auto",
                    path=track_path(name, coords[0], coords[-1]) if rail else None,
                ))
            else:  # walk transfer
                specs.append(_spec("walk", coords, line="Transfer walk", costing="pedestrian"))

        # Walk from the last stop to campus
        if _apart(last, campus_pt):
            specs.append(_spec("walk", [last, campus_pt], line="Walk to campus", costing="pedestrian"))
    else:
        # Fallback: no legs data
        routes = commute_routes(best_stop.stop_id, campus) or []
        if not routes:
            specs.append(_spec("walk", [stop_pt, campus_pt], line="Walk to campus", costing="pedestrian"))
        else:
            # Split evenly between stop and campus (straight lines: there's no real geometry)
            n = len(routes)
            prev = stop_pt
            for i, line_name in enumerate(routes):
                end = [
                    best_stop.lon + (campus_lon - best_stop.lon) * ((i + 1) / n),
                    best_stop.lat + (campus_lat - best_stop.lat) * ((i + 1) / n),
                ]
                specs.append(_spec("ride", [prev, end], line=line_name,
                                   color=get_line_color(line_name)))
                prev = end

    return {"type": "FeatureCollection", "features": _render(specs)}


def _render(specs):
    """Resolve all lines; routing requests run in parallel and order is preserved."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(_resolve, specs))