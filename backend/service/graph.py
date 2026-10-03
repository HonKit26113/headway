"""Route-aware transit graph and commute times to campus. See CONTRACT.md (Phase D)."""
import heapq
from collections import defaultdict

import numpy as np
import pandas as pd

from service.gtfs import DAY_END, DAY_START  # ride times use daytime trips only (07:00-19:00)

CAMPUS_RADIUS_M = 1000      # stops this close to the campus point walk there
TRANSFER_RADIUS_M = 250     # max walk between stops to change vehicles
BOARD_PENALTY_S = 300       # wait for every boarding except the first
WALK_MPS = 1.4              # straight-line walking speed
EARTH_R = 6371000.0
M_PER_DEG_LAT = np.pi * EARTH_R / 180


def _haversine_m(lat1, lon1, lat2, lon2):
    """Haversine distance in meters; works on scalars and numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def walking_pairs(stops: pd.DataFrame, max_m: float) -> list[tuple[str, str, float]]:
    """Ordered pairs (a, b, meters) of distinct stops within max_m, both directions."""
    if len(stops) < 2:
        return []
    ids = stops["stop_id"].astype(str).to_numpy()
    lat = stops["stop_lat"].to_numpy(dtype=float)
    lon = stops["stop_lon"].to_numpy(dtype=float)
    ok = np.isfinite(lat) & np.isfinite(lon)  # rows without a usable position can't be walked to
    ids, lat, lon = ids[ok], lat[ok], lon[ok]
    if len(ids) < 2:
        return []
    # Grid cells at least max_m wide everywhere in the data, so neighbours are in the 3x3 block.
    cell_lat = max_m / M_PER_DEG_LAT
    cell_lon = max_m / (M_PER_DEG_LAT * max(np.cos(np.radians(np.abs(lat).max())), 1e-6))
    keys = np.stack([np.floor(lat / cell_lat), np.floor(lon / cell_lon)], axis=1).astype(np.int64)
    cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (r, c) in enumerate(map(tuple, keys)):
        cells[(r, c)].append(i)

    pairs = []
    for (r, c), members in cells.items():
        near = [j for dr in (-1, 0, 1) for dc in (-1, 0, 1) for j in cells.get((r + dr, c + dc), ())]
        a = np.asarray(members)[:, None]
        b = np.asarray(near)[None, :]
        d = _haversine_m(lat[a], lon[a], lat[b], lon[b])
        ai, bi = np.nonzero((d <= max_m) & (ids[a] != ids[b]))  # same id = same stop, never a pair
        for x, y in zip(ai, bi):
            pairs.append((ids[members[x]], ids[near[y]], float(d[x, y])))
    pairs.sort()
    return pairs


def _patterns(stop_times, trips, service_ids):
    """Active stop_times rows with their pattern (route_id, direction_id), in trip order."""
    active = trips.loc[trips["service_id"].isin(service_ids), ["trip_id", "route_id", "direction_id"]]
    active = active.assign(direction_id=active["direction_id"].fillna(""))
    st = stop_times.merge(active, on="trip_id", validate="many_to_one")
    st = st.assign(seq=pd.to_numeric(st["stop_sequence"])).sort_values(["trip_id", "seq"], kind="stable")
    return st.reset_index(drop=True)


def commute_from_all_stops(stops, stop_times, trips, service_ids, campus_latlon, *,
                           campus_radius_m=CAMPUS_RADIUS_M, transfer_m=TRANSFER_RADIUS_M,
                           board_penalty_s=BOARD_PENALTY_S, walk_mps=WALK_MPS) -> dict[str, float]:
    """Minutes from every stop that can reach campus. See CONTRACT.md for the model."""
    st = _patterns(stop_times, trips, service_ids)
    stop_ids = list(dict.fromkeys(list(stops["stop_id"].astype(str)) + list(st["stop_id"].astype(str))))
    stand = {s: i for i, s in enumerate(stop_ids)}  # node id for "standing at stop s"

    # Ride hops between consecutive stops of each trip; median duration per (pattern, A, B).
    nxt = st.groupby("trip_id", sort=False)
    hops = pd.DataFrame({
        "route_id": st["route_id"], "direction_id": st["direction_id"],
        "a": st["stop_id"], "b": nxt["stop_id"].shift(-1),
        "dur": nxt["arrival_s"].shift(-1).astype("Float64") - st["departure_s"].astype("Float64"),
    }).dropna(subset=["b", "dur"])
    leaves = st["departure_s"].astype("Float64")
    daytime = (leaves >= DAY_START) & (leaves < DAY_END)  # NightBus run times would be unrealistically fast
    hops = hops[(hops["dur"] >= 0) & daytime.loc[hops.index].fillna(False)]
    hop_time = hops.groupby(["route_id", "direction_id", "a", "b"], sort=True)["dur"].median()

    can_board = st["pickup_type"] != "1" if "pickup_type" in st else pd.Series(True, index=st.index)
    can_alight = st["drop_off_type"] != "1" if "drop_off_type" in st else pd.Series(True, index=st.index)
    key = list(zip(st["stop_id"], st["route_id"], st["direction_id"]))
    board_ok = {k for k, ok in zip(key, can_board) if ok}
    alight_ok = {k for k, ok in zip(key, can_alight) if ok}

    on: dict[tuple, int] = {}  # node id for "on board pattern p at stop s"
    for k in sorted(set(key)):
        on[k] = len(stop_ids) + len(on)
    n = len(stop_ids) + len(on)

    # Reverse graph: rev[v] = [(u, cost)] for every forward edge u -> v.
    rev: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for (route, direction, a, b), dur in hop_time.items():
        rev[on[(b, route, direction)]].append((on[(a, route, direction)], float(dur)))
    for k, node in on.items():
        if k in board_ok:  # stand s -> on (s, p) costs a boarding wait
            rev[node].append((stand[k[0]], float(board_penalty_s)))
        if k in alight_ok:  # on (s, p) -> stand s is free
            rev[stand[k[0]]].append((node, 0.0))
    walks = walking_pairs(stops, transfer_m)
    for a, b, m in walks:
        rev[stand[b]].append((stand[a], m / walk_mps))

    # Campus targets: stops within campus_radius_m walk to the campus point.
    lat0, lon0 = campus_latlon
    s_lat = stops["stop_lat"].to_numpy(dtype=float)
    s_lon = stops["stop_lon"].to_numpy(dtype=float)
    to_campus = _haversine_m(s_lat, s_lon, lat0, lon0)
    campus_walk = {
        str(s): float(m) / walk_mps for s, m in zip(stops["stop_id"], to_campus) if m <= campus_radius_m
    }

    dist = [np.inf] * n
    heap = []
    for s, sec in campus_walk.items():
        dist[stand[s]] = sec
        heap.append((sec, stand[s]))
    heapq.heapify(heap)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        for u, w in rev[v]:
            if d + w < dist[u]:
                dist[u] = d + w
                heapq.heappush(heap, (d + w, u))

    # Journey cost from an origin: walk straight to campus, or board here / one walk away for free.
    first_board = defaultdict(lambda: np.inf)  # best on-board cost at stop s, first boarding free
    for k, node in on.items():
        if k in board_ok:
            first_board[k[0]] = min(first_board[k[0]], dist[node])
    best = dict(first_board)
    for a, b, m in walks:
        if b in first_board:
            best[a] = min(best.get(a, np.inf), m / walk_mps + first_board[b])
    for s, sec in campus_walk.items():
        best[s] = min(best.get(s, np.inf), sec)

    known = set(stops["stop_id"].astype(str))  # stop_times ids missing from stops never reach the output
    return {s: round(sec / 60, 1) for s, sec in sorted(best.items()) if s in known and np.isfinite(sec)}
