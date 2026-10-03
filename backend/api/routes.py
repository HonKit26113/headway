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
