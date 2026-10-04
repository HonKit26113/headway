# Headway: Transit Housing Scorer
## Multi-Role Claude.md for StormHacks 2026

**Project Goal:** A neighbourhood transit score tool for students hunting off-campus housing. Query an address ~~or explore a heatmap~~. Score shows commute time, frequency, late-night service, and walking distance to campus.

**Tech Stack:** Python backend (FastAPI), React frontend, MapLibre GL JS, ~~H3 grid (res 8)~~ (cut — Windows build issue), TransLink GTFS static data, deployed on Railway.

**Design System:** Black (#0B0B0C), Orange (#FF5A2E), Gray (#8E8C87). Fonts: **Instrument Serif** (headers), **Geist** (body, 400/500/600).

**Team Roles:** BE1 (You / Scoring), BE2 (Data & Routes), FE (Map UI), GEN (Landing, QA, Pitch).

**Hackathon:** Oct 3–4, 2026 (24–36h). **Goal:** Win.

---

> ## ⚠️ SCOPE CUT: Heatmap is OUT
> **Real reason:** The H3 library fails to build on Windows (CMake toolchain issue). Already pulled from `backend/requirements.txt`; `/api/heatmap` and the heatmap cache stub have been removed from `backend/`.
>
> **Why it's fine to cut:** The heatmap was a visualization layer on top of the core feature (search → score + 4 factors). That core is unaffected and is a complete demo on its own.
>
> **If a teammate finds slack time:** the lowest-risk path back in is precompute — BE2 generates a static GeoJSON grid of scores at startup (no H3 needed), FE renders it as a layer. Costs ~2h. PostGIS or fighting the H3 Windows build are not worth it in a 24h window.
>
> Sections below that reference the heatmap (marked ~~struck through~~) describe the original vision and are kept for context — they are **not being built**.

---

## PICK YOUR ROLE

**Which role are you?** Jump to your section:

| Role | What You Build | Section | Time | Commits |
|------|---|---|---|---|
| **BE1** (Scoring / Geospatial) | Weighted scoring, H3 heatmap, `/api/score`, `/api/heatmap` | [Backend: Scoring & Heatmap](#backend-scoring--heatmap) | ~14h | 8–12 |
| **BE2** (GTFS / Data) | Load TransLink GTFS, parse routes, calculate frequency, geocode | [Backend: GTFS & Data](#backend-gtfs--data) | ~11h | 6–10 |
| **FE** (Map UI) | MapLibre map, search bar, score panel, campus picker, Tailwind styling | [Frontend: Map & UI](#frontend-map--ui) | ~13h | 10–15 |
| **GEN** (Landing / QA) | Landing page, demo video, Devpost, scope cuts, QA testing | [Frontend: Landing & Demo](#frontend-landing--demo) | 5h code + 19h management | 3–5 |

**Not sure?** Read the intro to [ROLES, RESPONSIBILITIES & WORKING MODES](#iii-roles-responsibilities--working-modes) first, then pick your section above.

---

## I. DESIGN & BRAND

**Color Palette:**
- Black (#0B0B0C) — Background
- Orange (#FF5A2E) — Accent (CTAs, highlights, factor bars)
- Gray (#8E8C87) — Secondary text

**Typography:**
- **Headers:** Instrument Serif (serif, thin weight, formal)
- **Body:** Geist (sans-serif, 400–600 weights, clean & readable)
- Load both from Google Fonts CDN; see Frontend Setup section for imports.

**Design philosophy:** Minimalist, dark theme, one accent color. Judges should read your UI in 5 seconds. Big serif headline on landing, orange button for CTA, black background with orange factor bars in the panel.

---

## I. FILE STRUCTURE

```
headway/
├── README.md                      # Repo root; one sentence + link to live app
├── .gitignore                     # Standard (Go, node_modules, .env)
├── .env.example                   # No secrets; example keys only
│
├── backend/                       # Python 3.11+ with FastAPI
│   ├── main.py                    # Entry point; FastAPI app, CORS, startup
│   ├── requirements.txt            # fastapi, uvicorn, h3, pandas, requests, numpy
│   ├── .env.example               # PORT=8000, CORS_ORIGIN=http://localhost:5173
│   │
│   ├── api/
│   │   ├── routes.py              # FastAPI router; score, heatmap, geocode, health
│   │   └── models.py              # Pydantic: ScoreRequest, ScoreResponse, Factor
│   │
│   ├── service/
│   │   ├── scoring.py             # Core: compute_score, weighted_score, factor_calc
│   │   ├── gtfs.py                # load_gtfs, parse_stops, parse_routes, calc_frequency
│   │   ├── routing.py             # find_nearest_stop, compute_commute_time (BFS on route graph)
│   │   ├── geocoding.py           # geocode_address via Nominatim
│   │   ├── geom.py                # haversine distance, h3 hex operations
│   │   └── cache.py               # HeatmapCache (in-memory dict + TTL)
│   │
│   ├── data/
│   │   ├── translink_stops.geojson (pre-downloaded)
│   │   ├── translink_routes.geojson (pre-downloaded)
│   │   └── README.md              # How to update GTFS files
│   │
│   └── config.py                  # Env vars, campus coords, scoring thresholds
│
├── frontend/                      # React + Vite
│   ├── index.html                 # Import Instrument Serif + Geist from Google Fonts
│   ├── vite.config.js
│   ├── package.json
│   ├── tailwind.config.js         # Configure colors: black, orange, gray
│   ├── postcss.config.js
│   ├── src/
│   │   ├── main.jsx               # React entry
│   │   ├── App.jsx                # Router: Landing vs Map
│   │   ├── pages/
│   │   │   ├── Landing.jsx        # Serif heading, CTA, hero visual
│   │   │   └── App.jsx            # Map page: search + campus picker + heatmap + panel
│   │   ├── components/
│   │   │   ├── MapContainer.jsx   # MapLibre init + layer mgmt
│   │   │   ├── ScorePanel.jsx     # Detail panel, factors breakdown
│   │   │   ├── SearchBar.jsx      # Geocode input, debounced
│   │   │   ├── CampusPicker.jsx   # Radio/button group
│   │   │   ├── Legend.jsx         # Score color scale
│   │   │   └── Heatmap.jsx        # Render grid, query /api/heatmap
│   │   ├── hooks/
│   │   │   ├── useApi.js          # Fetch wrapper + error handling
│   │   │   └── useGeocode.js      # Debounced geocode call
│   │   ├── styles/
│   │   │   ├── globals.css        # Tailwind + dark mode, fonts
│   │   │   └── map.css            # MapLibre overrides, hex colors
│   │   └── lib/
│   │       ├── api.js             # API client (base URL from env)
│   │       ├── geocoding.js       # Nominatim wrapper
│   │       └── colors.js          # Score → hex gradient
│   └── public/
│       ├── index.html
│       └── favicon.svg
│
├── devpost/                       # Hackathon submission
│   ├── README.md                  # 300-word project summary
│   ├── demo-video.mp4             # 60s walkthrough (GEN)
│   └── screenshot.png             # Heatmap view
│
├── .github/workflows/
│   └── deploy.yml                 # On push to main: build + deploy backend + frontend
│
├── docker/                        # Optional; for local dev only
│   ├── docker-compose.yml
│   └── # Skip for hackathon unless infra is blocker
│
└── docs/
    └── ARCHITECTURE.md            # Flow diagram, data model, scoring formula
```

---

## II. DATA FLOW & SCORING FORMULA

### The Core Logic (BE1 owns this)

1. **User submits address** → `POST /api/score`
   - Input: `{address: "123 Main St, Burnaby", campus: "sfu"}`
   - Geocode address → lat/lon via Nominatim
   - Find H3 hex (res 8) containing that point

2. **Compute commute route**
   - Load GTFS routes (pre-fetched from TransLink; parsed into pandas DataFrame)
   - For each route, find nearest stop to address using haversine distance
   - Route graph: find path from nearest stop to campus stop using BFS
   - Extract duration (GTFS `arrival_time - departure_time`)

3. **Aggregate all routes serving that hex**
   - **Frequency:** avg headway (minutes between buses) at that stop (calculated from stop_times.txt)
   - **Late night:** count of trips after 11pm; store last trip time
   - **Walk time:** haversine distance (address → nearest stop) / 1.4 m/s
   - **Commute:** duration from step 2

4. **Weight factors into single 0–10 score**
   ```python
   score = (
     commute_factor * 0.3 +        # 0–10: 60min→0, 15min→10
     frequency_factor * 0.3 +      # 0–10: 30min headway→0, 5min→10
     latenight_factor * 0.2 +      # 0–10: no late service→0, after 1am→10
     walk_factor * 0.2             # 0–10: 20min walk→0, 2min→10
   )
   score = min(10, score)
   ```
   → Return `{score: 8.4, factors: {...}}`

5. **Heatmap:** `GET /api/heatmap?campus=sfu`
   - Precompute scores for a grid of H3 hexes (500–1000 hexes covering Burnaby)
   - Cache result in-memory (or Redis), expire every 6h
   - Return geojson-like: `{hex_id: "8...", center: [lat, lon], score: 7.2}`
   - Frontend renders as heatmap overlay

---

## III. ROLES, RESPONSIBILITIES & WORKING MODES

### Working Modes

**Air Programming (default for core logic):**
- You write the code. Claude teaches concepts and guides debugging.
- New concepts: Claude explains upfront (e.g., "here's how pandas groupby works").
- Repeated patterns: you attempt first, then debug collaboratively if stuck.
- Boilerplate is included; you still write it (builds fluency).
- **Why:** You own every line. You understand decisions. Independent capability.
- **When:** All core logic (scoring, GTFS parsing, API handlers, key components).

**Vibecoding (fallback for speed):**
- Describe intent in pseudo-code or English. Claude generates full, production-ready code.
- You review, test, and tweak.
- **Why:** Fast. Useful for boilerplate you understand already.
- **When:** Only when calendar pressure is extreme AND the code isn't core logic (e.g., FE needs a button component in 20min, not the search bar).

**For Headway:**
- **BE1 (You):** Air-program scoring logic. Core product; must understand every factor.
- **BE2:** Air-program GTFS parsing. Own the data flow.
- **FE:** Air-program search + score panel (what judges see). Can vibecode Legend/Heatmap if needed.
- **GEN:** Air-program landing copy. Own the narrative.

---

## Backend: Scoring & ~~Heatmap~~ (heatmap cut — see scope cut notice above)

[← Back to Role Picker](#pick-your-role) | [BE2 (GTFS & Data)](#backend-gtfs--data) | [FE (Map & UI)](#frontend-map--ui) | [GEN (Landing & Demo)](#frontend-landing--demo)

### BE1: Scoring & Geospatial Logic

**Primary deliverable:** H3 aggregation, factor computation, score weighting.

**Coding hours:** ~14h over 24h (backloaded toward hour 16–24 for integration).

**Commits:** 20–28; PRs: 6–8.

**Air Programming Guide** (Claude teaches the flow, you write each piece):

First, understand the flow:
1. User POSTs address + campus to `/api/score`
2. Geocode the address to lat/lon
3. Find the nearest transit stop
4. Compute commute time from that stop to campus (using GTFS routes)
5. Gather frequency + late-night data for that stop
6. Weight all 4 factors (commute, frequency, late-night, walk) into a 0–10 score
7. Return the score + factors to the frontend

Now code it. Start with the main app setup:

File: `backend/main.py`
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from service.gtfs import load_gtfs_on_startup

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://headway.railway.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load GTFS data on startup (happens once)
@app.on_event("startup")
async def startup():
    load_gtfs_on_startup()

# Include routing
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

File: `backend/api/routes.py`
```python
from fastapi import APIRouter, HTTPException
from api.models import ScoreRequest, ScoreResponse, Factor
from service.scoring import compute_score
from service.geocoding import geocode_address

router = APIRouter(prefix="/api")

@router.post("/score")
async def score_handler(req: ScoreRequest) -> ScoreResponse:
    """
    POST /api/score
    Input: {address: "123 Main St, Burnaby", campus: "sfu"}
    Output: {score: 8.4, factors: [{label: "Commute", value: "24 min", percent: 78}, ...]}
    """
    try:
        # Geocode address to lat/lon via Nominatim
        latlon = geocode_address(req.address)
        if not latlon:
            raise HTTPException(status_code=400, detail="Address not found")
        
        # Compute score (all logic is in service.scoring.compute_score)
        score_obj = compute_score(latlon, req.campus)
        
        # Format factors for the panel
        factors = [
            Factor(label="Commute", value=f"{score_obj.commute_time} min", percent=int(score_obj.commute_factor * 10)),
            Factor(label="Bus frequency", value=f"every {score_obj.frequency_headway} min", percent=int(score_obj.frequency_factor * 10)),
            Factor(label="Late night service", value=f"until {score_obj.late_night_time}", percent=int(score_obj.latenight_factor * 10)),
            Factor(label="Walk to stop", value=f"{score_obj.walk_time} min", percent=int(score_obj.walk_factor * 10)),
        ]
        
        return ScoreResponse(score=score_obj.score, factors=factors)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/heatmap")
async def heatmap_handler(campus: str):
    """
    GET /api/heatmap?campus=sfu
    Returns GeoJSON of scored hexagons covering Burnaby
    """
    from service.cache import get_heatmap_cache
    
    cache = get_heatmap_cache()
    geojson = cache.get_heatmap(campus)
    if not geojson:
        # Precompute on demand (or have it precomputed at startup)
        geojson = compute_heatmap_grid(campus)
        cache.set_heatmap(campus, geojson)
    
    return geojson

@router.get("/health")
async def health():
    return {"status": "ok"}
```

File: `backend/service/scoring.py` (core logic)
```python
import h3
import numpy as np
from service.routing import find_nearest_stop, compute_commute_time
from service.geom import haversine
from service.cache import ROUTE_CACHE
from config import CAMPUS_COORDS, COMMUTE_THRESHOLD, FREQUENCY_THRESHOLD

def compute_score(latlon: tuple, campus: str) -> ScoreObject:
    """
    Main scoring function. Called for each user query.
    Factors: commute time, bus frequency, late-night service, walk distance.
    """
    lat, lon = latlon
    
    # 1. Find nearest stop to address
    nearest_stop = find_nearest_stop(lat, lon)
    walk_distance = haversine(lat, lon, nearest_stop.lat, nearest_stop.lon)
    walk_time_min = (walk_distance * 1000) / 1.4 / 60  # meters to minutes at 1.4 m/s
    
    # 2. Compute commute from this stop to campus
    commute_time = compute_commute_time(nearest_stop.id, campus)
    
    # 3. Gather frequency + late-night from cache
    route_cache = ROUTE_CACHE[campus]
    frequency_headway = route_cache.get(nearest_stop.id, {}).get("frequency", 30)
    late_night_time = route_cache.get(nearest_stop.id, {}).get("last_trip", "11:00 PM")
    
    # 4. Compute factors (0–10 scale)
    commute_factor = max(0, 10 * (1 - (commute_time / COMMUTE_THRESHOLD)))
    frequency_factor = max(0, 10 * (1 - (frequency_headway / FREQUENCY_THRESHOLD)))
    latenight_factor = 10 if "12:" in late_night_time or "1:" in late_night_time else 5
    walk_factor = max(0, 10 * (1 - (walk_time_min / 20)))
    
    # 5. Weight factors
    score = (
        commute_factor * 0.3 +
        frequency_factor * 0.3 +
        latenight_factor * 0.2 +
        walk_factor * 0.2
    )
    score = min(10, max(0, score))
    
    return ScoreObject(
        score=round(score, 1),
        commute_time=int(commute_time),
        commute_factor=commute_factor,
        frequency_headway=int(frequency_headway),
        frequency_factor=frequency_factor,
        late_night_time=late_night_time,
        latenight_factor=latenight_factor,
        walk_time=int(walk_time_min),
        walk_factor=walk_factor,
    )
```

**Teaching notes for BE1:**
- FastAPI basics: routing with decorators, Pydantic models for validation
- Pandas for GTFS DataFrames: filtering, merging, calculating aggregates
- H3 grid operations: `h3.geo_to_h3()` to find hex from lat/lon
- Haversine distance: formula for distance between two lat/lon points
- Weighting factors: turning raw metrics (minutes, headway) into 0–10 scale

You write each handler. Claude guides on patterns, debugging, and formula calibration. If threshold tuning feels off after testing (e.g., "why is Burnaby getting 4.2 instead of 7?"), Claude helps you diagnose and adjust the weights.

**Checkpoints for agents:**
1. **Hour 2:** GTFS data loaded; routes parsed; `nearestStop` function returns a valid stop.
2. **Hour 8:** Scoring formula implemented; test with 5 hardcoded address/campus pairs; score range 0–10.
3. **Hour 16:** `/api/score` endpoint live; FE can call it; JSON matches panel layout.
4. **Hour 20:** Heatmap endpoint live; precomputed grid caches; FE renders without lag.
5. **Hour 23:** Final tuning; judges see 8–9 scores in central Burnaby, 3–4 in remote areas.

**Fallback plan (if GTFS parsing fails):**
- Use hardcoded distance-based proxy: `score = 10 * exp(-walk_time / 5)`
- Prefetch top 5 routes per campus by hand; don't block on dynamic data.

---

## Backend: GTFS & Data

[← Back to Role Picker](#pick-your-role) | [BE1 (Scoring & Heatmap)](#backend-scoring--heatmap) | [FE (Map & UI)](#frontend-map--ui) | [GEN (Landing & Demo)](#frontend-landing--demo)

### BE2: Data Pipeline & Routes

**Primary deliverable:** TransLink GTFS ingestion, route graph construction, API for BE1.

**Coding hours:** ~11h over 24h (frontloaded hours 0–10, then integration).

**Commits:** 15–22; PRs: 5–7.

**Air Programming Guide** (Claude teaches GTFS parsing, you write):

First, understand what GTFS is:
- A standard format for transit schedules (stops, routes, timings)
- TransLink publishes it as a ZIP file with multiple CSV files: stops.txt, routes.txt, stop_times.txt
- You parse these into pandas DataFrames and provide them to BE1

Your job: load GTFS → parse CSVs → cache to JSON for fast reloads.

File: `backend/service/gtfs.py`
```python
import pandas as pd
import json
import requests
import zipfile
import io
from io import StringIO

def load_gtfs():
    """
    Fetch TransLink GTFS; parse stops, routes, stop_times.
    Returns (stops_df, routes_df, stop_times_df) cached for BE1's use.
    """
    # 1. Download GTFS from TransLink (or use local file for faster iteration)
    print("Loading GTFS...")
    try:
        url = "https://translink.ca/data/GTFS.zip"
        r = requests.get(url, timeout=30)
        gtfs_zip = zipfile.ZipFile(io.BytesIO(r.content))
    except Exception as e:
        print(f"GTFS download failed: {e}. Using fallback hardcoded routes.")
        return None, None, None
    
    # 2. Parse stops.txt → DataFrame[stop_id, stop_lat, stop_lon, stop_name]
    try:
        stops_df = pd.read_csv(gtfs_zip.open("stops.txt"))
        print(f"Loaded {len(stops_df)} stops")
    except Exception as e:
        print(f"Failed to parse stops: {e}")
        return None, None, None
    
    # 3. Parse routes.txt → DataFrame[route_id, route_long_name, route_short_name]
    try:
        routes_df = pd.read_csv(gtfs_zip.open("routes.txt"))
        print(f"Loaded {len(routes_df)} routes")
    except Exception as e:
        print(f"Failed to parse routes: {e}")
        return None, None, None
    
    # 4. Parse stop_times.txt → DataFrame[stop_id, trip_id, arrival_time, departure_time]
    try:
        stop_times_df = pd.read_csv(gtfs_zip.open("stop_times.txt"))
        print(f"Loaded {len(stop_times_df)} stop_times")
    except Exception as e:
        print(f"Failed to parse stop_times: {e}")
        return None, None, None
    
    return stops_df, routes_df, stop_times_df

def calculate_frequency(stop_times_df: pd.DataFrame, stop_id: str) -> int:
    """
    Calculate average headway (minutes between buses) for a stop.
    """
    stop_trips = stop_times_df[stop_times_df["stop_id"] == stop_id].sort_values("departure_time")
    if len(stop_trips) < 2:
        return 60  # Default to 60 min if not enough data
    
    # Convert times to minutes, calculate gaps
    times = pd.to_datetime(stop_trips["departure_time"], format="%H:%M:%S")
    gaps = times.diff().dt.total_seconds() / 60
    avg_headway = gaps.dropna().mean()
    
    return int(avg_headway) if not pd.isna(avg_headway) else 60

def get_last_trip_time(stop_times_df: pd.DataFrame, stop_id: str) -> str:
    """
    Get the latest trip time at a stop (for late-night scoring).
    """
    stop_trips = stop_times_df[stop_times_df["stop_id"] == stop_id]
    if len(stop_trips) == 0:
        return "11:00 PM"
    
    latest_time = stop_trips["departure_time"].max()
    return latest_time

def routes_to_geojson(routes_df: pd.DataFrame, stops_df: pd.DataFrame, stop_times_df: pd.DataFrame):
    """
    Generate route GeoJSON for visualization (optional; judges may see this).
    Each route is a line connecting its stops in order.
    """
    features = []
    
    for idx, route in routes_df.iterrows():
        route_id = route["route_id"]
        route_trips = stop_times_df[stop_times_df["route_id"] == route_id]
        
        if len(route_trips) == 0:
            continue
        
        # Get stops for this route in order
        route_stops = route_trips.drop_duplicates("stop_id")[["stop_id"]].merge(
            stops_df, left_on="stop_id", right_on="stop_id"
        )
        
        if len(route_stops) < 2:
            continue
        
        # Build coordinates
        coords = [[row["stop_lon"], row["stop_lat"]] for _, row in route_stops.iterrows()]
        
        feature = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "name": route.get("route_long_name", route.get("route_short_name", "Unknown")),
                "route_id": route_id
            }
        }
        features.append(feature)
    
    return {"type": "FeatureCollection", "features": features}

def save_cache_to_json(stops_df, routes_df, stop_times_df, output_path="data/gtfs_cache.json"):
    """
    Save parsed GTFS to JSON for fast reloading during hackathon.
    """
    cache = {
        "stops": stops_df.to_dict(orient="records"),
        "routes": routes_df.to_dict(orient="records"),
        "stop_times": stop_times_df.to_dict(orient="records"),
    }
    with open(output_path, "w") as f:
        json.dump(cache, f)
    print(f"Cached GTFS to {output_path}")

def load_cache_from_json(path="data/gtfs_cache.json"):
    """
    Load cached GTFS data if available (faster than re-downloading).
    """
    try:
        with open(path, "r") as f:
            cache = json.load(f)
        stops_df = pd.DataFrame(cache["stops"])
        routes_df = pd.DataFrame(cache["routes"])
        stop_times_df = pd.DataFrame(cache["stop_times"])
        print(f"Loaded cached GTFS from {path}")
        return stops_df, routes_df, stop_times_df
    except Exception as e:
        print(f"Could not load cache: {e}")
        return None, None, None
```

**Teaching notes for BE2:**
- Pandas I/O: `pd.read_csv()` for CSVs, working with ZIP files in memory
- Data aggregation: groupby(), mean(), min(), max() for frequency + late-night calculations
- Haversine distance: finding nearest stop to a lat/lon point
- Caching: save parsed DataFrames to JSON at startup, reload on subsequent runs (speeds up iteration 100x)
- Error handling: graceful fallback if GTFS download fails

You write the load_gtfs() function. Claude guides on pandas patterns and optimization. If frequency calculation is slow, Claude helps you vectorize it. If caching is broken, debug together.

**Checkpoints for agents:**
1. **Hour 2:** TransLink GTFS downloaded; `stops.txt` parsed; validate 500+ stops in Burnaby.
2. **Hour 5:** `routes.txt` parsed; `stop_times.txt` loaded; adjacency graph built.
3. **Hour 8:** Route GeoJSON generated; FE can render it as overlay (stretch goal).
4. **Hour 10:** Precomputed fallback routes hardcoded (top 3 to each campus).
5. **Hour 14:** BE1 integration test: pass a stop_id to BE1, get back valid commute time.

**Fallback plan (if GTFS is corrupted or unavailable):**
- Use precomputed distance-based estimate: `commute_time = distance_km / 20 * 60` (20 km/h avg speed).
- Deploy with 10–15 hardcoded stops in Burnaby, Metrotown, SFU area.

---

## Frontend: Map & UI

[← Back to Role Picker](#pick-your-role) | [BE1 (Scoring & Heatmap)](#backend-scoring--heatmap) | [BE2 (GTFS & Data)](#backend-gtfs--data) | [GEN (Landing & Demo)](#frontend-landing--demo)

### FE: Map & UI

**Primary deliverable:** MapLibre heatmap, geocoding search, details panel, smooth interactions.

**Coding hours:** ~13h over 24h (even load, debugging spikes late).

**Commits:** 25–35; PRs: 7–9.

**Air Programming Guide** (Claude teaches React patterns, you write):

First, understand the architecture:
- App.jsx: main layout, state for campus/score/heatmap
- MapContainer.jsx: MapLibre setup, heatmap layer rendering, map click handling
- SearchBar.jsx: debounced geocoding + score API call
- CampusPicker.jsx: radio buttons to switch campus
- ScorePanel.jsx: display score + factors with progress bars

You build each component. Claude teaches React hooks (useState, useEffect), MapLibre GL integration, Tailwind styling. You attempt CSS first, iterate visually.

File: `frontend/src/App.jsx`
```jsx
// App.jsx: Main layout
function App() {
  const [campus, setCampus] = useState("sfu");
  const [selectedAddress, setSelectedAddress] = useState(null);
  const [score, setScore] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  
  useEffect(() => {
    // Fetch heatmap on campus change
    fetch(`/api/heatmap?campus=${campus}`)
      .then(r => r.json())
      .then(setHeatmap);
  }, [campus]);
  
  const handleSearch = async (addr) => {
    const res = await fetch("/api/score", {
      method: "POST",
      body: JSON.stringify({address: addr, campus})
    });
    const data = await res.json();
    setSelectedAddress(addr);
    setScore(data);
  };
  
  return (
    <div className="flex h-screen">
      <MapContainer campus={campus} heatmap={heatmap} onPin={setSelectedAddress} />
      <ScorePanel score={score} address={selectedAddress} />
    </div>
  );
}

// MapContainer.jsx
function MapContainer({campus, heatmap, onPin}) {
  const mapContainer = useRef(null);
  const map = useRef(null);
  
  useEffect(() => {
    // Init MapLibre, add heatmap layer, handle clicks
    const m = new maplibregl.Map({
      container: mapContainer.current,
      style: "https://protomaps.github.io/basemaps/protomaps(light).json",
      center: campusCoords[campus],
      zoom: 12
    });
    
    // Add heatmap layer from geojson
    if (heatmap) {
      m.addSource("heatmap-source", {type: "geojson", data: heatmap});
      m.addLayer({
        id: "heatmap-layer",
        type: "fill",
        source: "heatmap-source",
        paint: {"fill-color": ["interpolate", ["linear"], ["get", "score"], ...colorStops]}
      });
    }
    
    // Handle map click
    m.on("click", (e) => {
      const hex = e.features[0]?.properties?.hex_id;
      if (hex) onPin(hex);
    });
    
    map.current = m;
  }, [campus, heatmap]);
  
  return <div ref={mapContainer} style={{width: "100%", height: "100%"}} />;
}

// ScorePanel.jsx
function ScorePanel({score, address}) {
  if (!score) return <aside>Select a location</aside>;
  
  return (
    <aside className="w-96 p-8 border-l border-gray-700 flex flex-col gap-6">
      <div>
        <div className="text-gray-400 text-sm uppercase">Selected</div>
        <div className="text-xl font-medium">{address}</div>
      </div>
      <div className="border-b border-gray-700 pb-6">
        <span className="text-6xl font-serif">{score.score.toFixed(1)}</span>
        <span className="text-lg text-gray-400"> / 10</span>
      </div>
      <div className="space-y-4">
        {score.factors.map(f => (
          <div key={f.label}>
            <div className="flex justify-between text-sm mb-2">
              <span className="text-gray-400">{f.label}</span>
              <span>{f.value}</span>
            </div>
            <div className="h-1 bg-gray-700 rounded">
              <div className="h-full bg-red-500" style={{width: `${f.percent}%`}}></div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
```

**Teaching notes for FE:**
- React hooks: useState (campus, score, heatmap), useEffect (fetch on mount/dependency change)
- MapLibre GL JS: initialization, adding layers, event handling (click, hover)
- Tailwind: utility-first styling, dark mode with `dark:` prefix, custom colors via config
- Debouncing: useCallback to prevent too many API calls while typing
- Composition: each component owns one piece of state, passes data down, callbacks up

You build each component incrementally. Start with SearchBar (simplest), then CampusPicker, then MapContainer (trickiest). Claude guides on MapLibre event handling and Tailwind layout. You choose padding/spacing, test visually, iterate.

**Checkpoints for agents:**
1. **Hour 3:** Landing page live; CTA links to map view.
2. **Hour 6:** Map view initialized; MapLibre renders (even without data); campus picker works.
3. **Hour 9:** Heatmap layer renders; colors update when campus changes.
4. **Hour 12:** Search bar geocodes; submitting an address calls `/api/score` and shows result.
5. **Hour 15:** Score panel fully styled; factors display with progress bars.
6. **Hour 20:** Polish: smooth transitions, mobile responsiveness, no console errors.
7. **Hour 23:** Final demo: search a real Burnaby address, see score + factors.

**Fallback plan (if MapLibre is slow or crashes):**
- Use a static SVG heatmap (predrawn canvas) instead of live vector tiles.
- Keep search and score panel; lose the interactive map.

---

## Frontend: Landing & Demo

[← Back to Role Picker](#pick-your-role) | [BE1 (Scoring & Heatmap)](#backend-scoring--heatmap) | [BE2 (GTFS & Data)](#backend-gtfs--data) | [FE (Map & UI)](#frontend-map--ui)

### GEN: Landing, QA, Pitch, Demo (You)

**Primary deliverable:** Landing page copy, Devpost writeup, 60s demo video, final QA.

**Coding hours:** ~5h over 24h (backloaded to hour 20–24).

**Commits:** 8–12; PRs: 3–4.

**Responsibilities:**

1. **Landing page copy & setup** (Hour 0–2)
   - Finalize headline, subheading, CTAs.
   - Ensure landing.html links correctly to app.
   - Test on mobile.

2. **Demo video** (Hour 18–21)
   - Screencast: search a real address, show heatmap, highlight score breakdown.
   - 60 seconds max. Audio: "Headway helps students find housing with a commute that works."
   - Export as `.mp4`; upload to Devpost.

3. **Devpost README** (Hour 20–22)
   - **Inspiration:** "Students juggle housing costs, distance to campus, and transit access."
   - **What it does:** "Headway scores any address by commute + transit frequency + late-night service."
   - **How we built it:** "Go backend with H3 geospatial logic, React + MapLibre frontend, TransLink GTFS data."
   - **Challenges:** Pick two: GTFS parsing, getting judges to care about backend logic.
   - **What's next:** Compare feature, multi-campus, mobile app.

4. **QA & final checks** (Hour 22–24)
   - Search for 10 real Burnaby addresses; confirm scores are sensible.
   - Test campus picker; confirm scores change.
   - Check for typos, broken links, missing imagery.
   - Screenshot heatmap for Devpost thumbnail.

**Your role (you own it):**

Landing page copy, demo video, Devpost submission. Claude helps brainstorm, refine copy, but you decide the voice and narrative.

**Outline for GEN:**
```markdown
# Headway: Find Your Commute

**Inspiration**
Moving to an apartment while in school is stressful. Students weigh distance against rent. Headway cuts through the noise by scoring any address by how well transit gets you to campus.

**What it does**
1. Enter an address or click the map.
2. See an instant score (0–10).
3. Understand why: commute time, bus frequency, late-night service, walk distance.

**How we built it**
- **Backend (Go):** H3 geospatial indexing, GTFS parsing, weighted scoring.
- **Frontend (React + MapLibre):** Heatmap, search, score breakdown.
- **Data:** TransLink Burnaby transit data (static GTFS).

**Challenges**
1. Parsing GTFS without choking on 1,000+ routes.
2. Making the scoring logic intuitive to judges in 60 seconds.

**What's next**
- Multi-stop commute routing (bus + SkyTrain + walk).
- Comparison tool: side-by-side score multiple listings.
- Mobile app for apartment hunting.
```

**Your process:**
- Lock the outline with BE1 at hour 2 (understand the scoring logic so you can pitch it).
- Draft Devpost README by hour 20 (once demo works end-to-end). Claude can suggest phrasing, but you control the voice.
- Record demo video at hour 20 (not hour 23; gives time to re-record if needed). One take: search address, show score, explain one factor briefly. 60 seconds.

**Checkpoints for agents:**
1. **Hour 2:** Landing page live; copy finalized.
2. **Hour 12:** Devpost outline drafted.
3. **Hour 18:** Demo video script + recording plan locked.
4. **Hour 21:** Video recorded + edited.
5. **Hour 22:** Devpost README submitted; all fields filled.
6. **Hour 23:** QA complete; no crashes on 10 test addresses.
7. **Hour 24:** Final screenshot taken; all systems green; ready to demo.

---

## IV. DEPLOYMENT

### Local Development
```bash
# Backend
cd backend
pip install -r requirements.txt
python main.py                    # Server on http://localhost:8000 (Uvicorn)

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                       # Vite on :5173

# Browser
open http://localhost:5173
```

### Backend Requirements
```txt
# requirements.txt
# Web framework & server
fastapi==0.104.1
uvicorn[standard]==0.24.0

# Data validation
pydantic==2.5.0
pydantic-settings==2.1.0

# Geospatial
h3==3.7.0
numpy==1.24.3

# Data processing
pandas==2.1.1

# HTTP & I/O
requests==2.31.0
python-dotenv==1.0.0

# Optional: async support
aiofiles==23.2.1

# Optional: caching (if using Redis)
# redis==5.0.0
```

### Staging (Railway)
```bash
# Prerequisite: Railway account + GitHub connection

# Backend deployment
cd backend
railway up
# → Detects Python; installs from requirements.txt, runs uvicorn main:app
# → Sets BACKEND_URL env var

# Frontend deployment (build + static hosting)
cd ../frontend
npm run build                     # Output: dist/
railway up
# → Detects Node; serves Vite SPA; env.VITE_API_URL points to backend

# Health check
curl https://headway-backend.railway.app/health
curl https://headway.railway.app
```

### Docker (optional; for local containerized testing)
```dockerfile
# backend/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Variables
```bash
# backend/.env
PORT=8000
GEOCODE_PROVIDER=nominatim        # Free, no key needed
GTFS_URL=https://translink.ca/data/GTFS.zip
GTFS_CACHE_PATH=data/gtfs_cache.json
CACHE_TTL_SECONDS=21600            # 6 hours
CORS_ORIGINS=http://localhost:5173,https://headway.railway.app
LOG_LEVEL=info

# frontend/.env (Vite)
VITE_API_URL=http://localhost:8000
VITE_ACCENT_COLOR=#FF5A2E
VITE_CAMPUS_DEFAULT=sfu
```

### Backend Setup
```bash
cd backend

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and edit as needed
cp .env.example .env

# Run locally
python main.py

# Or use uvicorn directly with auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup (Fonts & Colors)

File: `frontend/index.html`
```html
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Headway</title>
  
  <!-- Fonts: Instrument Serif (headers) + Geist (body) -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
</head>
```

File: `frontend/tailwind.config.js`
```js
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        black: '#0B0B0C',
        orange: '#FF5A2E',  // accent
        gray: '#8E8C87',     // secondary text
      },
      fontFamily: {
        serif: ['Instrument Serif', 'Georgia', 'serif'],  // Headers
        sans: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],  // Body
      },
    },
  },
  plugins: [],
};
```

File: `frontend/src/styles/globals.css`
```css
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&display=swap');

:root {
  --black: #0B0B0C;
  --orange: #FF5A2E;
  --gray: #8E8C87;
  --gray-light: #A9A69F;
  --gray-lighter: #1F1F22;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
  background: var(--black);
  color: #EDEBE6;
  line-height: 1.6;
}

h1, h2, h3, h4, h5, h6 {
  font-family: 'Instrument Serif', Georgia, serif;
  font-weight: 400;
}

h1 { font-size: 3rem; letter-spacing: -0.02em; }
h2 { font-size: 2rem; }
h3 { font-size: 1.25rem; }
```

### Database
**None.** All data is in-memory (GTFS cache) or computed on-the-fly. If you need persistence (favorites, history), add SQLite in hour 22; otherwise skip it.

### Performance Targets
- `/api/score`: <200ms (geo + route lookup + weighting).
- `/api/heatmap`: <1s (precomputed; served from cache).
- Frontend map render: <500ms (MapLibre + GeoJSON).

### Disaster Recovery
- **GTFS fails to parse:** Fall back to hardcoded distance-based scoring (see BE2 fallback).
- **Backend crashes:** Frontend shows "Unable to reach server; try again in 30s."
- **Frontend JS fails:** Landing page still works (static HTML).

---

## V. GIT WORKFLOW

```bash
# Main branch: always deployable
git checkout main

# Each role: feature branch
git checkout -b be1/scoring
# ... work ...
git add .
git commit -m "add H3 scoring with factor weighting"
git push origin be1/scoring
# → Open PR; merge once BE2 integration tests pass

git checkout -b be2/gtfs-loader
# ... work ...
git commit -m "parse translink GTFS; save routes geojson"
git push origin be2/gtfs-loader

git checkout -b fe/map-layer
# ... work ...
git commit -m "render heatmap from /api/heatmap"
git push origin fe/map-layer

git checkout -b gen/landing-copy
# ... work ...
git commit -m "finalize landing page copy and styling"
git push origin gen/landing-copy

# Merge in order (be2 → be1 → fe → gen) to avoid conflicts
```

### Commit Message Format
```
<type>(<scope>): <subject>

<body (optional)>

// Good examples:
feat(be1): add weighted factor aggregation
fix(fe): correct heatmap color interpolation
docs(gen): finalize devpost readme
chore(infra): set up railway deployment
```

---

## VI. AGENT CHECKPOINTS & HANDOFF PROTOCOL

### How to Post Checkpoints (GitHub Issues)

**Before hour 0:**
- One person creates a GitHub Issue titled: **"🔔 Checkpoints & Status"**
- Copy the template below into the Issue description
- Pin it to the repo (so it's always visible)

**Every 90 minutes, each role posts a comment in that issue:**

**Template to copy-paste:**
```
## [Role] Status @ Hour [N]

**Completed:**
- [x] checkpoint 1
- [x] checkpoint 2

**PR/Commit:** [link or short hash]

**Blockers:** none / [list them]

**Next 90 min:** [what you're building next]
```

**Example (BE1 @ Hour 8):**
```
## BE1 Status @ Hour 8

**Completed:**
- [x] GTFS loaded and parsed with pandas
- [x] nearest_stop() working on 5 test addresses
- [x] haversine distance tested

**PR:** https://github.com/team/headway/pull/3

**Blockers:** none

**Next 90 min:** Implement factor weighting, test /api/score endpoint with BE2
```

**Example (FE @ Hour 6):**
```
## FE Status @ Hour 6

**Completed:**
- [x] Vite dev server running
- [x] MapLibre renders blank map at campus coords
- [x] SearchBar component scaffolded

**Commit:** a1b2c3d

**Blockers:** MapLibre GL CSS not importing cleanly, need to debug Tailwind + MapLibre together

**Next 90 min:** Fix MapLibre styling, wire search to /api/score endpoint
```

### Approval Process (You / GEN)

**Every 90 min, monitor the checkpoint issue.** Read each role's update.

**If the checkpoint looks solid:**
- Reply with: `✅ approved — on track`

**If there's a blocker:**
- Reply with: `⚠️ [role] — [brief issue]. Need help or should we pivot?`

**At Hour 12 (scope cut decision):**
- Post a new comment in the checkpoint issue:
```
## 🔪 Scope Cut @ Hour 12

**Keep (shipping):**
- Search address → score + factors
- Landing page + CTA
- Devpost + demo

**Cut (reducing scope):**
- Heatmap (saves BE1 2h + FE 3h)
- Why: [BE1 blocked on X / FE behind on Y]

**New priority:** [what replaces cut work]

---
**Everyone confirm you saw this ↑ and move to new priorities. Next checkpoint @ hour 14.**
```

Everyone sees the decision at once. No Slack ambiguity.

---

### Integration Points (Critical Handoffs)

| Hour | Handoff | From | To | Success Criteria |
|------|---------|------|-----|------------------|
| 5 | GTFS parsing complete | BE2 | BE1 | `routes[]` struct can be passed to BE1 scorer |
| 10 | Search geocoding + scoring | FE | BE1 | Frontend can call `/api/score` and render response |
| 14 | Heatmap endpoint live | BE1 | FE | Frontend renders heatmap layer without lag |
| 18 | Landing page deployment | GEN | FE | CTA links correctly to app view |
| 21 | Demo video + Devpost draft | GEN | Team | Video is <1min, Devpost is in submission form |
| 24 | Final QA | All | Judges | No crashes on 10 test addresses; demo works end-to-end |

### Scope Cutting (Do This at Hour 12 if Behind)

**Keep (non-negotiable):**
- Search address → get score (1–2 min API call)
- Score panel with 4 factors (commute, frequency, late-night, walk)
- Landing page with CTA
- Devpost submission + demo video

**Cut in this order if time pressure hits:**

**1. Heatmap layer** (first cut)
   - **Why:** Judges care about the score logic, not a map gradient. Search + panel alone is a full product.
   - **Loss:** Visual polish. No substantive feature loss.
   - **Estimate:** Saves BE1 2h + FE 3h.
   - **How:** Remove heatmap endpoint from BE1. FE still renders a static map background (gray grid).

**2. Multi-campus picker** (second cut if still behind)
   - **Why:** Hard-code SFU as the only campus. Routes + scoring are already campus-agnostic; just set `campus="sfu"` everywhere.
   - **Loss:** Generality. Users can't compare to UBC.
   - **Estimate:** Saves BE2 1h + FE 30min.
   - **How:** Remove campus picker button. Set a hidden default in config.

**3. Route visualization** (always cut; was never core)
   - **Why:** Judges won't notice. It's a nice-to-have for the map layer you already cut.
   - **Estimate:** Saves BE2 1h.

**4. Mobile responsiveness** (cut if polish time is tight)
   - **Why:** Demo is on desktop. Judges use a big screen.
   - **Loss:** Looks awkward on phones; nobody cares for a 60s demo.
   - **Estimate:** Saves FE 1h of Tailwind tweaking.

**5. Custom error pages** (cut if style/QA time is slipping)
   - **Why:** A JSON error is fine. Judges won't test edge cases.
   - **Estimate:** Saves BE1 + FE 30min.

### Fallback Escalation

**If a checkpoint is missed by 30 min:**
1. Role reports blocker immediately (Slack / Discord).
2. Another role context-switches to unblock (e.g., FE helps BE1 debug API call).
3. Invoke scope cuts above in order.

**Example timeline if things slip:**
- Hour 12: Search works, but heatmap is slow. GEN says "cut heatmap." Saves 5h of calendar.
- Hour 16: BE2 still fighting GTFS. Use distance-based fallback scoring (takes 30min). Still ship on time.
- Hour 20: FE not done with panel polish. Multi-campus cut. Saves 1.5h. Deploy with SFU only.
- Hour 23: Demo recorded. Devpost submitted. Ship.

---

## VII. TECH DECISIONS & RATIONALE

| Decision | Rationale | Fallback |
|----------|-----------|----------|
| **Python 3.11 + FastAPI** | Fast prototyping; pandas + h3 are production libraries; async support; auto docs (Swagger/OpenAPI) at /docs. Uvicorn is lightweight. | Flask (simpler but slower; no built-in async). |
| **pandas + h3** | pandas handles GTFS CSV parsing cleanly; h3 is the de-facto Python geospatial grid library. | numpy alone (lower-level, more verbose). |
| H3 grid (res 8) | ~1 km hexes; fast aggregation; visually cleaner heatmaps. | 1 km² square grid (simpler code; uglier on map). |
| MapLibre GL JS | Free vector tiles; no billing; better than Mapbox. | Leaflet + OpenStreetMap tiles (raster, lower resolution). |
| TransLink GTFS static | 24h hackathon; live data parsing is risky. | Hardcoded top 5 routes per campus (fallback ready). |
| Nominatim geocoding | Free; no API key; widely trusted. | Offline reverse-geocode library (slower; 100ms vs 500ms). |
| In-memory cache | Simple Python dict with TTL; no DB setup overhead. | Redis (more resilient; more setup). |
| React (not Vue / Svelte) | Most judges know React; fastest iteration with vibecoding. | Vanilla HTML + JS (harder to update dynamically). |
| Tailwind CSS | Fast utility-first styling; shadcn/ui ready to go. | Plain CSS (slower to style; more custom code). |
| Railway deployment | GitHub auto-deploy; free tier covers 24h hackathon. Both backend and frontend auto-detect language. | Fly.io or Vercel (slightly more complex setup). |

---

## VIII. COMMUNICATION & HAND-OFF DURING EVENT

**Discord/Slack:**
- **#be1-scoring** — You, any integration Q's
- **#be2-data** — BE2 GTFS updates
- **#fe** — Frontend blockers
- **#gen** — Landing, copy, QA
- **#blockers** — Escalations only

**Daily standups (if doing a 36h event):**
- **Hour 12:** What's working? What's not? Adjust scope if needed.
- **Hour 20:** Last stretch. Demo readiness. QA plan.

**Final 2 hours:**
- **Freeze features.** Only bug fixes + final styling.
- GEN records demo video.
- All pushes go to `main` + deploy to Railway.
- Test on staged URL before judges see it.

---

## IX. SUCCESS CRITERIA FOR JUDGES

The demo should show:

1. **Product clarity:** "Search an address, get a score." No explanation needed.
2. **Visual polish:** Dark theme, readable typography, accent color used consistently.
3. **Real data:** Actual TransLink routes, actual Burnaby addresses, sensible scores.
4. **Interaction:** Search works, campus picker updates scores, details panel is readable.
5. **Backend depth:** Explain H3 grid + factor weighting in 30 seconds. Judges see the logic, not magic.

**Elevator pitch (20 seconds):**
> "Headway scores any address by how well transit gets you to campus. We pull real TransLink data, compute a weighted score for commute time, frequency, late-night service, and walk distance, and show it on a heatmap. A student can search a listing, see the score instantly, and make a better housing decision."

**Technical depth (60 seconds):**
> "Under the hood, we index Burnaby into H3 hexagons. For each hex, we load the GTFS route graph, find the nearest stop, compute the shortest path to campus, and aggregate factors from all routes. We weight commute time and frequency most heavily because that's what matters most. It's all computed in real-time or served from a 6-hour cache, so response times are <200ms even on a slow network."

---

## X. POST-HACKATHON ROADMAP (If You Ship & Win)

1. **Multi-stop routing:** Bus → SkyTrain → walk → campus.
2. **Compare tool:** Side-by-side scores for 3+ listings.
3. **Save favorites:** Auth + database.
4. **Mobile app:** React Native / Flutter.
5. **Expand:** UBC, BCIT, Concordia.
6. **Monetize:** Partner with landlords, sponsored listings.

---

## QUICK START BY ROLE

**New to the repo?** Follow these steps in order:

1. **Read your role** in the table above → click the link
2. **Run the SETUP** below (everyone does this once)
3. **Start coding** — your role section has checkpoints and examples
4. **Commit every 90 min** — show judges you're actually coding during the hackathon

---

## SETUP (Before Hour 0 — 15 minutes)

**Do this before anyone starts coding.**

```bash
# Clone repo
git clone <repo> headway && cd headway

# Backend: create folder structure + init files
cd backend
mkdir -p api service data util
touch main.py requirements.txt .env.example config.py
touch api/__init__.py api/routes.py api/models.py
touch service/__init__.py service/gtfs.py service/scoring.py service/routing.py service/geocoding.py service/geom.py service/cache.py
cd ..

# Frontend: Vite handles structure
cd frontend
# (Vite init already created src/, public/, etc.)
mkdir -p src/components src/hooks src/styles src/lib
touch src/components/.gitkeep src/hooks/.gitkeep src/lib/.gitkeep
cd ..

# Install dependencies
cd backend
python3 -m venv venv
source venv/bin/activate  # (or venv\Scripts\activate on Windows)
pip install -r requirements.txt
cd ../frontend
npm install
cd ..

# Verify both servers start
# Terminal 1:
cd backend && python main.py
# Should see: "Uvicorn running on http://localhost:8000"

# Terminal 2:
cd frontend && npm run dev
# Should see: "VITE v5.0.0 ready in ... ms"

# Browser:
# http://localhost:5173 → landing page
# http://localhost:8000/docs → FastAPI Swagger UI
```

If either server fails, **debug now**. Don't start hour 0 with broken env.

---

## Initial File Scaffolding (Copy into each file)

**backend/main.py**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
import config

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.on_event("startup")
async def startup():
    # Load GTFS at startup (BE2 fills this in)
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**backend/config.py**
```python
import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 8000))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
GEOCODE_PROVIDER = os.getenv("GEOCODE_PROVIDER", "nominatim")
GTFS_CACHE_PATH = os.getenv("GTFS_CACHE_PATH", "data/gtfs_cache.json")

# Campus coordinates (lat, lon)
CAMPUS_COORDS = {
    "sfu": (49.2766, -122.9156),
    "ubc": (49.2606, -123.2533),
    "bcit": (49.2506, -122.9506),
}

# Scoring thresholds
COMMUTE_THRESHOLD = 60  # minutes; scores below 15min get 10, above 60min get 0
FREQUENCY_THRESHOLD = 30  # headway minutes; scores below 5min get 10, above 30min get 0
```

**backend/api/__init__.py**
```python
# Empty file; makes api/ a package
```

**backend/api/routes.py**
```python
from fastapi import APIRouter
from api.models import ScoreRequest, ScoreResponse

router = APIRouter(prefix="/api")

@router.post("/score")
async def score(req: ScoreRequest) -> ScoreResponse:
    # BE1 fills this in
    pass

@router.get("/heatmap")
async def heatmap(campus: str):
    # BE1 fills this in
    pass

@router.get("/health")
async def health():
    return {"status": "ok"}
```

**backend/api/models.py**
```python
from pydantic import BaseModel

class ScoreRequest(BaseModel):
    address: str
    campus: str

class Factor(BaseModel):
    label: str
    value: str
    percent: int

class ScoreResponse(BaseModel):
    score: float
    factors: list[Factor]
```

**backend/service/__init__.py**
```python
# Empty file; makes service/ a package
```

**backend/service/gtfs.py**
```python
import pandas as pd

def load_gtfs():
    # BE2 fills this in
    pass

def get_frequency(stop_id: str) -> int:
    # BE2 fills this in
    pass
```

**backend/service/scoring.py**
```python
from api.models import ScoreResponse

def compute_score(latlon: tuple, campus: str) -> ScoreResponse:
    # BE1 fills this in
    pass
```

**backend/service/geocoding.py**
```python
def geocode_address(address: str) -> tuple:
    # BE1 fills this in (lat, lon)
    pass
```

**backend/service/geom.py**
```python
import math

def haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance in meters between two lat/lon points"""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c
```

**backend/service/cache.py**
```python
# In-memory cache for heatmaps
HEATMAP_CACHE = {}

def get_heatmap(campus: str):
    return HEATMAP_CACHE.get(campus)

def set_heatmap(campus: str, geojson):
    HEATMAP_CACHE[campus] = geojson
```

**frontend/src/App.jsx**
```jsx
import { useState, useEffect } from 'react'
import './styles/globals.css'

export default function App() {
  const [campus, setCampus] = useState("sfu")
  const [score, setScore] = useState(null)
  
  // FE fills this in
  
  return (
    <div>
      {/* FE builds the layout */}
    </div>
  )
}
```

**frontend/src/styles/globals.css**
```css
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&display=swap');

:root {
  --black: #0B0B0C;
  --orange: #FF5A2E;
  --gray: #8E8C87;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
  background: var(--black);
  color: #EDEBE6;
}

h1, h2, h3 {
  font-family: 'Instrument Serif', Georgia, serif;
}
```

**backend/requirements.txt** (paste this in)
```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
pydantic-settings==2.1.0
h3==3.7.0
numpy==1.24.3
pandas==2.1.1
requests==2.31.0
python-dotenv==1.0.0
```

---

## QUICK START (Copy & Paste)

```bash
# Clone repo
git clone <repo> headway && cd headway

# Backend (Terminal 1)
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
# Server running on http://localhost:8000
# API docs available at http://localhost:8000/docs (Swagger UI)

# Frontend (Terminal 2)
cd frontend
npm install
npm run dev
# Dev server on http://localhost:5173

# Test the API
curl -X POST http://localhost:8000/api/score \
  -H "Content-Type: application/json" \
  -d '{"address": "123 Main St, Burnaby", "campus": "sfu"}'

# Expected response:
# {"score": 8.4, "factors": [...]}

# Deploy to Railway
# Push to main branch → GitHub Actions → Railway auto-deploys both services
```

---

## FINAL NOTES

### For the Team

**Working mode for everyone: Air Programming.** You write the code; Claude guides/teaches. New concepts explained upfront; repeated patterns, you attempt first. This is how you build independent capability.

- **BE1 (You, Scoring):** Air-program the scoring logic (core product; must understand every factor). Claude teaches pandas, H3, weighting. You write the formula. Test early with hardcoded addresses (hour 8). Practice explaining it to judges in 30 seconds.
- **BE2 (GTFS):** Air-program the GTFS parser. Claude teaches pandas I/O, aggregation, caching. You write load_gtfs() + frequency calc. Parse early; save to JSON cache immediately (hour 5). If download fails at hour 2, you have time to fallback to distance-based scoring.
- **FE:** Air-program search + score panel first (core UX; judges stare at this). MapLibre is tricky; heatmap can vibecode if time is tight. You pick Tailwind spacing values, iterate visually.
- **GEN (You):** Own landing page copy (1–2h), demo video (2h), Devpost (1h). Claude helps brainstorm/refine, but you control the narrative. At hour 12, **you make the scope cut decision.** Don't wait for permission.

**Critical call at Hour 12:**
If BE2 is fighting GTFS or FE is stuck on MapLibre, **GEN declares scope cut #1: heatmap gone.** Saves 5h. Ship search + score panel only. Judges won't miss the heatmap; they'll notice if the panel is half-built.

### Python + FastAPI Specific Tips

1. **Leverage FastAPI's auto-docs:** During demo, open `http://localhost:8000/docs` to show judges the API contract. Proves the backend is real.
2. **Use async strategically:** Nominatim calls and GTFS parsing are I/O-bound; mark them `async def` to avoid blocking.
3. **Pandas DataFrames as in-memory DBs:** Don't overthink it. A DataFrame with `df[df["stop_id"] == x]` is fast enough for hackathon scale.
4. **Cache GTFS to JSON:** By hour 5, BE2 should have saved the parsed GTFS to `data/gtfs_cache.json`. Then every restart is 50ms instead of 10s.
5. **Pydantic models are your friend:** Define request/response models once; FastAPI auto-validates and auto-docs them.

### Success Criteria (In Priority Order)

1. **Search works:** User types address → score appears. (Hours 0–12)
2. **Factors make sense:** Scores in central Burnaby > 7, remote areas < 5. (Hours 12–16)
3. **API is stable:** No crashes on 10 test addresses. (Hours 16–22)
4. **Demo is clean:** Search once, show score breakdown, emphasize the formula. 60 seconds. (Hour 20)
5. **Devpost is complete:** All fields filled, video uploaded. (Hour 22)

**Heatmap, multi-campus, routing—these are +1 if time allows. Don't build them at the expense of polish.**

---

**This is winnable. You've shipped Ferguson, LeetLoop, ColorStack bot. This is the same pattern: lock the core loop, vibecode the details, ship fast. Judges care about clarity + working demo + deep backend logic. You have all three if you focus.**

**Go win.**
