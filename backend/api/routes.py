from fastapi import APIRouter, HTTPException
from api.models import ScoreRequest, ScoreResponse
from service.scoring import compute_score
from service.geocoding import geocode

router = APIRouter(prefix="/api")

@router.post("/score")
async def score(req: ScoreRequest) -> ScoreResponse:
    try:
        location = geocode(req.address)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"geocoder unavailable: {e}")

    if location is None:
        raise HTTPException(status_code=400, detail="Address not found")

    try:
        result = compute_score((location.lat, location.lon), req.campus)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    from service.summary import generate_summary
    result.summary = generate_summary(result.score, result.factors, req.campus)
    return result

# @router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/heatmap")
async def heatmap(campus: str):
    from service.heatmap import generate_heatmap_geojson
    return generate_heatmap_geojson(campus)
