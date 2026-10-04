import logging
import numpy as np
from service.scoring import compute_score

logger = logging.getLogger(__name__)

# Light -> dark ramp (higher score = darker)
COLOR_RAMP = ["#fff5eb", "#fdd0a2", "#fd8d3c", "#d94801", "#7f2704"]


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


def generate_heatmap_geojson(
    campus: str,
    lat_min: float = 49.00,
    lat_max: float = 49.35,
    lon_min: float = -123.30,
    lon_max: float = -122.45,
    lat_step: float = 0.01,
    score_min: float | None = None,   # set both to fix the scale (e.g. 0 and 100)
    score_max: float | None = None,
) -> dict:
    """Grid of scored cells as GeoJSON, with normalized score and color included."""
    # Make cells roughly square in meters: scale longitude step by 1/cos(lat)
    mid_lat = (lat_min + lat_max) / 2.0
    lon_step = lat_step / np.cos(np.radians(mid_lat))

    n_lat = int(np.ceil((lat_max - lat_min) / lat_step))
    n_lon = int(np.ceil((lon_max - lon_min) / lon_step))

    cells = []
    for i in range(n_lat):
        for j in range(n_lon):
            # Cell edges, then center, so the grid covers the box exactly
            south = lat_min + i * lat_step
            west = lon_min + j * lon_step
            north, east = south + lat_step, west + lon_step
            center = (south + lat_step / 2, west + lon_step / 2)

            try:
                score = float(compute_score(center, campus).score)
            except Exception:
                logger.exception("compute_score failed at %s", center)
                continue  # skip instead of faking a 0

            cells.append((south, west, north, east, score))

    if not cells:
        return {"type": "FeatureCollection", "features": [], "metadata": {}}

    scores = [c[4] for c in cells]
    lo = min(scores) if score_min is None else score_min
    hi = max(scores) if score_max is None else score_max
    span = (hi - lo) or 1.0

    features = []
    for south, west, north, east, score in cells:
        t = (score - lo) / span
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
            "properties": {
                "score": score,
                "score_norm": round(t, 4),
                "color": score_to_color(t),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"score_min": lo, "score_max": hi},
    }