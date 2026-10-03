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
