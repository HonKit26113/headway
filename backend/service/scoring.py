import math

from api.models import ScoreResponse, Factor
from service.transit import nearest_stops, stop_stats, commute_minutes


def compute_score(origin: tuple, campus: str) -> ScoreResponse:
    lat, lon = origin
    stops = nearest_stops(lat, lon, radius_m=300)
    shortest_time_to_dest = math.inf
    best_headway = math.inf
    headways = []
    last_departure = 0
    best_walk_m = math.inf
    for stop, walk_distance_m in stops:
        time = commute_minutes(stop.stop_id, campus)
        if time is None:
            continue
        if time <= shortest_time_to_dest:
            shortest_time_to_dest = time
            best_walk_m = walk_distance_m

        stats = stop_stats(stop.stop_id)
        if stats is None:
            continue
        if stats.headway_min is not None:
            headways.append(stats.headway_min)
            if stats.headway_min < best_headway:
                best_headway = stats.headway_min
        if stats.last_departure_min is not None and stats.last_departure_min > last_departure:
            last_departure = stats.last_departure_min

    shortest_walk_min = best_walk_m / 1.4 / 60  # meters → minutes at 1.4 m/s
    avg_headway = sum(headways) / len(headways) if headways else None

    commute_score = get_commute_score(shortest_time_to_dest)
    frequency_score = get_frequency_score(avg_headway)
    latenight_score = get_latenight_score(last_departure)
    walk_score = get_walk_score(shortest_walk_min)

    if best_headway == "---" or (isinstance(best_headway, float) and math.isinf(best_headway)):
        best_headway = "---"

    final_score = (
        commute_score * 0.3 +     
        frequency_score * 0.3 +      
        latenight_score * 0.2 +      
        walk_score * 0.2  
    )

    # Safely format values for the UI (handle inf and None when no route is found)
    commute_str = "N/A" if math.isinf(shortest_time_to_dest) else f"{round(shortest_time_to_dest)} min"
    avg_headway_str = "N/A" if avg_headway is None else f"every {int(avg_headway)} min"
    best_headway_str = "N/A" if best_headway == "---" else f"every {int(best_headway)} min"
    walk_str = "N/A" if math.isinf(shortest_walk_min) else f"{int(shortest_walk_min)} min"
    
    factors = [
        Factor(label="Commute to campus", value=commute_str, percent=int(commute_score * 10)),
        Factor(label="Average frequency", value=avg_headway_str, percent=int(frequency_score * 10)),
        Factor(label="Peak frequency", value=best_headway_str, percent=0),
        Factor(label="Last trip home", value=f"until {int((last_departure // 60) % 24):02d}:{int(last_departure % 60):02d}", percent=int(latenight_score * 10)),
        Factor(label="Walk to nearest stop", value=walk_str, percent=int(walk_score * 10)),
    ]

    return ScoreResponse(score=round(final_score, 1), factors=factors)

def get_commute_score(time: float) -> float:
    if time >= 60:
        return 0
    if time <= 15:
        return 10.0
    return (60 - time) / 45 * 10

def get_latenight_score(last_departure: float) -> float:
    """
    Returns a score based on the latest departure of the day. No late service→0, after 1am→10

    Args:
        last_departure: In minutes after midnight, the latest depature of the day. >1440 = after midnight.

    Returns:
        float: score in [0, 10]
    """
    if last_departure < 23*60:
        return 0
    if last_departure > 25*60:
        return 10.0
    return (last_departure - 23*60) / (3*60) * 10

def get_frequency_score(headway_min: float | None) -> float:
    """0–10: 30min headway→0, 5min→10, clamped."""
    if headway_min is None or headway_min >= 30:
        return 0.0
    if headway_min <= 5:
        return 10.0
    return (30 - headway_min) / 25 * 10

def get_walk_score(walk_min: float) -> float:
    """0–10: 20min walk→0, 2min→10, clamped."""
    if walk_min >= 20:
        return 0.0
    if walk_min <= 2:
        return 10.0
    return (20 - walk_min) / 18 * 10
