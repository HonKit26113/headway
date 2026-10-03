# Headway: Transit Housing Scorer

Search an address. Know the transit.

A neighbourhood transit scorer for students hunting off-campus housing. Get a 0-10 score based on commute time, bus frequency, late-night service, and walk distance to campus.

**Live:** [https://headway.railway.app](https://headway.railway.app)

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

- **Backend:** FastAPI, Python 3.11, H3, GTFS data
- **Frontend:** React, Vite, MapLibre GL, Tailwind CSS
- **Deployment:** Railway

---

## Roles

- **BE1:** Scoring & geospatial logic
- **BE2:** GTFS data pipeline
- **FE:** Map UI & React components
- **GEN:** Landing page, QA, demo

See [`headway-claude.md`](../headway-claude.md) for full project spec.
