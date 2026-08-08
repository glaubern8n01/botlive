from typing import Literal
from pydantic import BaseModel, Field

class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(default="", max_length=100)
    price: float = Field(ge=0)
    approved_answers: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)
    active: bool = True

class SessionIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    estimated_minutes: int = Field(ge=5, le=720)
    product_ids: list[str] = Field(default_factory=list)
    seed: int = 42

class SimulationControl(BaseModel):
    action: Literal["start", "pause", "resume", "stop"]
    speed: float = Field(default=1.0, ge=0.05, le=20)
    session_id: str | None = None

class MediaAssetIn(BaseModel):
    product_id: str | None = None
    kind: Literal["video", "audio"]
    name: str = Field(min_length=2, max_length=160)
    local_path: str = Field(min_length=1, max_length=1024)
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    authorized: bool = False
    authorization_source: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)

class ScriptBlockIn(BaseModel):
    product_id: str
    kind: Literal["abertura", "apresentacao", "problema", "demonstracao", "beneficios", "prova", "objecoes", "pergunta", "cta", "transicao", "encerramento"]
    position: int = Field(ge=0, le=1000)
    duration_seconds: int = Field(default=60, ge=5, le=3600)
    text: str = Field(min_length=2, max_length=4000)
    title: str = Field(default="", max_length=160)

class SessionMaterialIn(BaseModel):
    media_id: str
    position: int = Field(ge=0, le=1000)
    planned_duration_seconds: int = Field(ge=1, le=86400)
    product_id: str | None = None
    script_id: str | None = None

class PlaybackControl(BaseModel):
    action: Literal["start", "pause", "resume", "next", "previous", "seek", "volume", "stop"]
    value: float | None = None

class RuntimeControl(BaseModel):
    action: Literal["start_rehearsal", "start_operation", "pause", "resume", "next", "previous", "stop", "teleprompter"]
    speed: float | None = Field(default=None, ge=0.25, le=4)
    font_size: int | None = Field(default=None, ge=18, le=96)
    teleprompter_paused: bool | None = None

class DiagnosticIn(BaseModel):
    camera: Literal["ok", "missing", "denied", "frozen", "unknown"] = "unknown"
    microphone: Literal["ok", "missing", "denied", "silent", "unknown"] = "unknown"
    connection: Literal["ok", "offline", "unstable"] = "ok"
    volume: float = Field(default=0, ge=0, le=1)
    camera_id: str = Field(default="", max_length=200)
    microphone_id: str = Field(default="", max_length=200)

class SettingIn(BaseModel):
    value: dict = Field(default_factory=dict)
