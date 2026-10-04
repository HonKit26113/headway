import logging

import numpy as np
from global_land_mask import globe  # pip install global-land-mask

import config
from service.scoring import compute_score

logger = logging.getLogger(__name__)

# How far around the selected campus to grid, in degrees (~0.1 = ~11km)
RADIUS_DEG = 0.1

# Light -> dark ramp (higher score = darker)
COLOR_RAMP = ["#fff5eb", "#fdd0a2", "#fd8d3c", "#d94801", "#7f2704"]
EMPTY_COLOR = "#555555"  # only used if a land cell has no scored neighbors at all


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def score_to_color(t: float) -> str:
    """Map t in [0, 1] to a hex color along COLOR_RAMP."""
    t = min(max(t, 0.0), 1.0)
    pos = t * (len(COLOR_RAMP) - 1)
    i = min(int(pos), len(COLOR_RAMP) - 2)
    frac = pos - i
    c0, c1 = _hex_to_rgb(COLOR_RAMP[i]), _hex_to_rgb(COLOR_RAMP[i + 1])
    rgb = [round(a + (b - a) * frac) for a, b in zip(c0, c1)]
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _is_unreachable(response) -> bool:
    """True if the scorer found no route to campus from this point."""
    return any(
        f.label == "Commute to campus" and f.value == "N/A"
        for f in response.factors
    )


def _is_land_cell(south: float, west: float, north: float, east: float) -> bool:
    """
    A cell counts as land if its center or any corner is on land, so cells
    straddling the coastline are kept and the shore doesn't get a gap.
    """
    lats = np.array([(south + north) / 2, south, south, north, north])
    lons = np.array([(west + east) / 2, west, east, west, east])
    return bool(np.any(globe.is_land(lats, lons)))


def _fill_empty(grid: np.ndarray, fillable: np.ndarray) -> np.ndarray:
    """
    Fill NaN cells with the mean of their non-NaN neighbors (8-connected),
    touching only cells where `fillable` is True (i.e. land).

    Runs in passes so large holes fill inward from their edges: each pass
    only uses values that existed at the start of that pass, so the result
    doesn't depend on iteration order.
    """
    grid = grid.copy()
    while True:
        empty = np.argwhere(np.isnan(grid) & fillable)
        if len(empty) == 0:
            break

        updates = {}
        for i, j in empty:
            block = grid[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]
            vals = block[~np.isnan(block)]
            if vals.size:
                updates[(i, j)] = float(vals.mean())

        if not updates:  # nothing scored anywhere nearby; leave the rest empty
            break
        for (i, j), v in updates.items():
            grid[i, j] = v
    return grid


def generate_heatmap_geojson(
    campus: str,
    lat_min: float | None = None,
    lat_max: float | None = None,
    lon_min: float | None = None,
    lon_max: float | None = None,
    lat_step: float = 0.02,
    score_min: float | None = None,   # set both to fix the scale (e.g. 0 and 10)
    score_max: float | None = None,
    fill_unreachable: bool = True,    # also fill land cells with no route to campus
    exclude_water: bool = True,       # skip cells that are entirely over water
) -> dict:
    """Grid of scored cells as GeoJSON, centered on the campus. Empty land cells take the average of their neighbors."""
    if lat_min is None or lat_max is None or lon_min is None or lon_max is None:
        # Default to a box centered on the campus rather than all of Metro Vancouver -
        # computing the whole region per request was OOM-killing the backend.
        campus_lat, campus_lon = config.CAMPUS_COORDS[campus]
        lat_min, lat_max = campus_lat - RADIUS_DEG, campus_lat + RADIUS_DEG
        lon_min, lon_max = campus_lon - RADIUS_DEG, campus_lon + RADIUS_DEG

    # Make cells roughly square in meters: scale longitude step by 1/cos(lat)
    mid_lat = (lat_min + lat_max) / 2.0
    lon_step = lat_step / np.cos(np.radians(mid_lat))

    n_lat = int(np.floor((lat_max - lat_min) / lat_step))
    n_lon = int(np.floor((lon_max - lon_min) / lon_step))

    grid = np.full((n_lat, n_lon), np.nan)
    land = np.ones((n_lat, n_lon), dtype=bool)

    for i in range(n_lat):
        for j in range(n_lon):
            south = lat_min + i * lat_step
            west = lon_min + j * lon_step
            north, east = south + lat_step, west + lon_step

            if exclude_water and not _is_land_cell(south, west, north, east):
                land[i, j] = False
                continue  # never scored, filled, or drawn

            center = (float(south + lat_step / 2), float(west + lon_step / 2))
            try:
                response = compute_score(center, campus)
            except Exception:
                logger.exception("compute_score failed at %s", center)
                continue  # stays NaN, filled from neighbors below

            if fill_unreachable and _is_unreachable(response):
                continue  # stays NaN, filled from neighbors below

            grid[i, j] = float(response.score)

    scored_mask = ~np.isnan(grid)
    if not scored_mask.any():
        return {"type": "FeatureCollection", "features": [], "metadata": {}}

    # Color scale comes from the real (unfilled) scores
    lo = float(np.nanmin(grid)) if score_min is None else score_min
    hi = float(np.nanmax(grid)) if score_max is None else score_max
    span = (hi - lo) or 1.0

    filled = _fill_empty(grid, fillable=land)

    logger.info(
        "heatmap %s: cells=%d land=%d scored=%d filled=%d still_empty=%d range=%.1f..%.1f",
        campus,
        grid.size,
        int(land.sum()),
        int(scored_mask.sum()),
        int((land & ~scored_mask & ~np.isnan(filled)).sum()),
        int((land & np.isnan(filled)).sum()),
        lo,
        hi,
    )

    features = []
    for i in range(n_lat):
        for j in range(n_lon):
            if not land[i, j]:
                continue

            south = lat_min + i * lat_step
            west = lon_min + j * lon_step
            north, east = south + lat_step, west + lon_step

            value = filled[i, j]
            if np.isnan(value):
                props = {"score": None, "score_norm": None,
                         "color": EMPTY_COLOR, "filled": True}
            else:
                t = (float(value) - lo) / span
                props = {
                    "score": round(float(value), 1),
                    "score_norm": round(t, 4),
                    "color": score_to_color(t),
                    "filled": not bool(scored_mask[i, j]),
                }

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [west, south], [east, south],
                        [east, north], [west, north],
                        [west, south],
                    ]],
                },
                "properties": props,
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"score_min": lo, "score_max": hi},
    }