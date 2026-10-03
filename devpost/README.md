# Headway: Find Your Commute

*Draft — written at ~hour 3. Placeholders marked [TODO] need real data once BE1's scoring and FE's map are live.*

## Inspiration

Moving off-campus is a tradeoff students make blind: cheaper rent usually means a worse commute, but nobody can tell you *how much* worse until they've already signed the lease. We wanted a way to see that tradeoff up front — one number that actually accounts for how transit works in real life, not just straight-line distance to campus.

## What it does

Search any address, pick your campus, and Headway scores it 0–10 based on four weighted factors:

- 🚌 **Commute time** — how long it actually takes to get to campus by transit
- ⏱ **Bus frequency** — how often service runs at the nearest stop
- 🌙 **Late-night service** — whether you can get home after a late class or shift
- 🚶 **Walk distance** — how far the address is from the nearest stop

Each factor is shown separately, not just buried in the final score, so you can see *why* a place scored the way it did.

## How we built it

- **Backend:** Python + FastAPI, parsing real TransLink GTFS static data (stops, routes, stop times) into weighted scores
- **Frontend:** React + Vite + Tailwind, MapLibre GL for the map view
- **Data:** TransLink's published GTFS feed for the Burnaby/SFU area
- **Design:** dark theme, one accent color (orange), Instrument Serif + Geist typography — built to be read in 5 seconds

[TODO: fill in once BE1's `/api/score` is live — architecture detail on the H3-adjacent scoring approach, actual latency numbers, any clever bits in the route graph]

## Challenges

- **Heatmap scope cut:** the H3 geospatial library doesn't build on Windows (CMake toolchain issue). Rather than burn hours fighting it mid-hackathon, we cut the heatmap entirely and kept the core product (search → score + factors) which doesn't depend on it.
- [TODO: BE1/BE2's real challenges — GTFS parsing edge cases, routing graph, whatever actually bit us]

## What's next

- Multi-stop commute routing (bus → SkyTrain → walk → campus)
- Compare tool: side-by-side scores for multiple listings
- Expand beyond SFU to UBC, BCIT
- A heatmap, done properly — precomputed server-side GeoJSON grid instead of fighting H3 on Windows

## Team

- Cedric H. — CS, UBC
- Herman L. — CS, UBC
- Daniel L. — CS, UBC
- Olisaemeka A. — DS + CS, SFU
