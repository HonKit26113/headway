# Headway: Transit Housing Scorer

Search an address. Know the transit.

A neighbourhood transit scorer for students hunting off-campus housing. Get a 0-10 score based on commute time, bus frequency, late-night service, and walk distance to campus.

**Live:** [https://headway.railway.app](https://headway.railway.app)

---

## Known Limitations

**Heatmap is cut from scope.** The H3 library fails to build on Windows (CMake toolchain issue), and we pulled it from `requirements.txt` rather than burn hours fighting it. The core product — search an address, get a score + 4 factors — doesn't depend on it. See `headway-claude.md` for the full reasoning and the scope-cut log.

---

## Setup

### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

**API Docs:** http://localhost:8000/docs

### Frontend
```bash
cd frontend
npm install
npm run dev
```

**App:** http://localhost:5173

---

## Tech Stack

- **Backend:** FastAPI, Python 3.11, ~~H3~~ (cut — Windows build issue), GTFS data
- **Frontend:** React, Vite, MapLibre GL, Tailwind CSS
- **Deployment:** Railway

---

## Roles

- **BE1:** Scoring & geospatial logic
- **BE2:** GTFS data pipeline
- **FE:** Map UI & React components
- **GEN:** Landing page, QA, demo

See [`headway-claude.md`](../headway-claude.md) for full project spec.
