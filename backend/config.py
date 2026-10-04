import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 8000))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
GEOCODE_PROVIDER = os.getenv("GEOCODE_PROVIDER", "nominatim")
GTFS_CACHE_PATH = os.getenv("GTFS_CACHE_PATH", "data/gtfs_cache.json")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 21600))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Campus coordinates (lat, lon)
CAMPUS_COORDS = {
    "sfu": (49.2766, -122.9156),
    "ubc": (49.2606, -123.2533),
    "bcit": (49.2490, -123.0010),  # BCIT Burnaby campus (Willingdon Ave & Canada Way)
}

# Scoring thresholds
COMMUTE_THRESHOLD = 60  # minutes
FREQUENCY_THRESHOLD = 30  # headway minutes
