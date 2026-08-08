from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import Base, SessionLocal, engine, get_db
from .models import AuditEvent, LiveSession, Product
from .schemas import ProductIn, SessionIn, SimulationControl
from .simulator import scenario, stream

def allowed_origins() -> list[str]:
    return [x.strip() for x in os.getenv("SHOP_LIVE_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if x.strip()]

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield

app = FastAPI(title="BotLive Shop Local Agent", version="0.2.0", docs_url="/shop-live/docs", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

def serialize(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}

def record(db: Session, kind: str, payload: dict, session_id: str | None = None) -> AuditEvent:
    event = AuditEvent(type=kind, payload=payload, session_id=session_id)
    db.add(event); db.commit(); db.refresh(event); return event

@app.get("/shop-live/v1/health")
def health():
    return {"ok": True, "mode": "simulation", "external_actions": False, "database": "connected"}

@app.post("/shop-live/v1/products", status_code=201)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    item = Product(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item)
    record(db, "product.created", {"product_id": item.id})
    return serialize(item)

@app.get("/shop-live/v1/products")
def list_products(db: Session = Depends(get_db)):
    return [serialize(row) for row in db.scalars(select(Product).order_by(Product.created_at)).all()]

@app.post("/shop-live/v1/sessions", status_code=201)
def create_session(payload: SessionIn, db: Session = Depends(get_db)):
    existing = set(db.scalars(select(Product.id).where(Product.id.in_(payload.product_ids))).all()) if payload.product_ids else set()
    if set(payload.product_ids) != existing: raise HTTPException(422, "Produto inexistente")
    item = LiveSession(title=payload.title, estimated_minutes=payload.estimated_minutes, seed=payload.seed)
    db.add(item); db.commit(); db.refresh(item)
    record(db, "session.created", {"product_ids": payload.product_ids, "seed": payload.seed}, item.id)
    return serialize(item)

@app.get("/shop-live/v1/sessions")
def list_sessions(db: Session = Depends(get_db)):
    return [serialize(row) for row in db.scalars(select(LiveSession).order_by(LiveSession.created_at)).all()]

@app.get("/shop-live/v1/audit")
def audit(db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(500)).all()
    return [serialize(row) for row in rows]

@app.get("/shop-live/v1/simulation/{seed}")
def simulation(seed: int):
    return scenario(seed)

@app.websocket("/shop-live/v1/events")
async def events(socket: WebSocket):
    if socket.headers.get("origin") not in allowed_origins():
        await socket.close(code=1008); return
    await socket.accept()
    await socket.send_json({"type": "simulation.ready", "payload": {"seed": 42}})
    try:
        while True:
            command = SimulationControl.model_validate_json(await socket.receive_text())
            with SessionLocal() as db:
                live = LiveSession(title="Simulação determinística", estimated_minutes=30, status="ao-vivo", seed=42)
                db.add(live); db.commit(); db.refresh(live)
                record(db, "session.started", {"seed": live.seed}, live.id)
            async for event in stream(42, command.speed):
                with SessionLocal() as db: record(db, event["type"], event.get("payload", {}), live.id)
                await socket.send_json(event)
            with SessionLocal() as db:
                persisted = db.get(LiveSession, live.id); persisted.status = "encerrada"; db.commit()
    except (WebSocketDisconnect, ValueError):
        return
