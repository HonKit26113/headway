from pydantic import BaseModel, Field

class ScoreRequest(BaseModel):
    address: str = Field(max_length=200)
    campus: str

class Factor(BaseModel):
    label: str
    value: str
    percent: int

class ScoreResponse(BaseModel):
    score: float
    factors: list[Factor]
    summary: str | None = None

class SummaryRequest(BaseModel):
    score: float
    factors: list[Factor]
    campus: str
