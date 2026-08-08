import os
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, Field

app = FastAPI(title="BotLive Shop Local Agent", docs_url="/shop-live/docs")
SESSIONS, PRODUCTS, EVENTS = {}, {}, []

class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(max_length=100)
    price: float = Field(ge=0)
    approved_answers: list[str] = []
    prohibited_claims: list[str] = []

class SessionIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    estimated_minutes: int = Field(ge=5, le=720)
    product_ids: list[str] = []

def record(kind, subject):
    event = {"id": str(uuid4()), "type": kind, "subject_id": subject, "source": "local-agent", "result": "ok", "at": datetime.now(timezone.utc).isoformat()}
    EVENTS.append(event); return event

@app.get("/shop-live/v1/health")
def health(): return {"ok": True, "mode": os.getenv("SHOP_LIVE_MODE", "simulation"), "external_actions": False}

@app.post("/shop-live/v1/products", status_code=201)
def create_product(payload: ProductIn):
    item = {"id": str(uuid4()), **payload.model_dump()}; PRODUCTS[item["id"]] = item; record("product.created", item["id"]); return item

@app.get("/shop-live/v1/products")
def list_products(): return list(PRODUCTS.values())

@app.post("/shop-live/v1/sessions", status_code=201)
def create_session(payload: SessionIn):
    missing = [x for x in payload.product_ids if x not in PRODUCTS]
    if missing: raise HTTPException(422, "Produto inexistente")
    item = {"id": str(uuid4()), **payload.model_dump(), "status": "rascunho"}; SESSIONS[item["id"]] = item; record("session.created", item["id"]); return item

@app.get("/shop-live/v1/audit")
def audit(): return EVENTS[-500:]

@app.websocket("/shop-live/v1/events")
async def events(socket: WebSocket):
    allowed = {x.strip() for x in os.getenv("SHOP_LIVE_ALLOWED_ORIGINS", "http://localhost:3000").split(",")}
    if socket.headers.get("origin") not in allowed: await socket.close(code=1008); return
    await socket.accept(); await socket.send_json({"type": "simulation.ready", "seed": 42})
