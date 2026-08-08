from typing import Literal
from pydantic import BaseModel, Field

class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(default="", max_length=100)
    price: float = Field(ge=0)
    approved_answers: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)

class SessionIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    estimated_minutes: int = Field(ge=5, le=720)
    product_ids: list[str] = Field(default_factory=list)
    seed: int = 42

class SimulationControl(BaseModel):
    action: Literal["start", "pause", "resume", "stop"]
    speed: float = Field(default=1.0, ge=0.05, le=20)
