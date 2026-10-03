# In-memory cache for heatmaps
HEATMAP_CACHE = {}

def get_heatmap(campus: str):
    return HEATMAP_CACHE.get(campus)

def set_heatmap(campus: str, geojson):
    HEATMAP_CACHE[campus] = geojson
