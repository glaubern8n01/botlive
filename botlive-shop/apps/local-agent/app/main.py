from __future__ import annotations

import asyncio
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import require_http_auth, require_websocket_auth
from .database import SessionLocal, get_db
from .models import AuditEvent, LiveSession, Product
from .schemas import ProductIn, SessionIn, SimulationControl
from .simulator import scenario, stream
import os

def allowed_origins() -> list[str]:
    return [x.strip() for x in os.getenv("SHOP_LIVE_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if x.strip()]

app = FastAPI(title="BotLive Shop Local Agent", version="0.3.0", docs_url="/shop-live/docs")
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Shop-Live-Token"])

def serialize(row) -> dict:
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    if isinstance(row, LiveSession): data["product_ids"] = [product.id for product in row.products]
    return data

def record(db: Session, kind: str, payload: dict, session_id: str | None = None) -> AuditEvent:
    event = AuditEvent(type=kind, payload=payload, session_id=session_id)
    db.add(event); db.commit(); db.refresh(event); return event

def set_session_status(session_id: str, status: str, event_type: str, payload: dict | None = None) -> None:
    with SessionLocal() as db:
        live = db.get(LiveSession, session_id)
        if not live: return
        live.status = status
        db.commit()
        record(db, event_type, payload or {}, session_id)

def interrupt_if_active(session_id: str) -> None:
    with SessionLocal() as db:
        live = db.get(LiveSession, session_id)
        if not live or live.status not in {"ao-vivo", "pausada"}: return
        live.status = "interrompida"; db.commit()
        record(db, "session.interrupted", {"reason": "websocket_disconnected"}, session_id)

AUTH = [Depends(require_http_auth)]

@app.get("/shop-live/v1/health", dependencies=AUTH)
def health(): return {"ok": True, "mode": "simulation", "external_actions": False, "database": "migration-managed"}

@app.post("/shop-live/v1/products", status_code=201, dependencies=AUTH)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    item = Product(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item)
    record(db, "product.created", {"product_id": item.id}); return serialize(item)

@app.get("/shop-live/v1/products", dependencies=AUTH)
def list_products(db: Session = Depends(get_db)):
    return [serialize(row) for row in db.scalars(select(Product).order_by(Product.created_at)).all()]

@app.post("/shop-live/v1/sessions", status_code=201, dependencies=AUTH)
def create_session(payload: SessionIn, db: Session = Depends(get_db)):
    products = db.scalars(select(Product).where(Product.id.in_(payload.product_ids))).all() if payload.product_ids else []
    if set(payload.product_ids) != {item.id for item in products}: raise HTTPException(422, "Produto inexistente")
    item = LiveSession(title=payload.title, estimated_minutes=payload.estimated_minutes, seed=payload.seed, products=list(products))
    db.add(item); db.commit(); db.refresh(item)
    record(db, "session.created", {"product_ids": payload.product_ids, "seed": payload.seed}, item.id); return serialize(item)

@app.get("/shop-live/v1/sessions", dependencies=AUTH)
def list_sessions(db: Session = Depends(get_db)):
    return [serialize(row) for row in db.scalars(select(LiveSession).order_by(LiveSession.created_at)).all()]

@app.get("/shop-live/v1/audit", dependencies=AUTH)
def audit(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    total = len(db.scalars(select(AuditEvent.id)).all())
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [serialize(row) for row in rows], "limit": limit, "offset": offset, "total": total}

@app.get("/shop-live/v1/simulation/{seed}", dependencies=AUTH)
def simulation(seed: int): return scenario(seed)

@app.websocket("/shop-live/v1/events")
async def events(socket: WebSocket):
    if socket.headers.get("origin") not in allowed_origins() or not await require_websocket_auth(socket):
        await socket.close(code=1008); return
    await socket.accept()
    await socket.send_json({"type": "simulation.ready", "payload": {"seed": 42, "state": "ready"}})
    paused, stopped, send_lock = asyncio.Event(), asyncio.Event(), asyncio.Lock()
    task: asyncio.Task | None = None
    session_id: str | None = None

    async def send(event: dict) -> None:
        async with send_lock: await socket.send_json(event)

    async def produce(live_id: str, speed: float) -> None:
        async for event in stream(42, speed, paused, stopped):
            with SessionLocal() as db: record(db, event["type"], event.get("payload", {}), live_id)
            await send(event)
        if stopped.is_set():
            set_session_status(live_id, "encerrada", "session.ended", {"reason": "operator_stop"})
            await send({"type": "simulation.stopped", "payload": {"state": "ready"}})
        else:
            with SessionLocal() as db:
                live = db.get(LiveSession, live_id)
                if live: live.status = "encerrada"; db.commit()
            await send({"type": "simulation.completed", "payload": {"state": "ready"}})

    try:
        while True:
            command = SimulationControl.model_validate_json(await socket.receive_text())
            if command.action == "start" and (task is None or task.done()):
                paused.clear(); stopped.clear()
                with SessionLocal() as db:
                    live = LiveSession(title="Simulação determinística", estimated_minutes=30, status="ao-vivo", seed=42)
                    db.add(live); db.commit(); db.refresh(live); session_id = live.id
                    record(db, "simulation.started", {"seed": 42}, session_id)
                task = asyncio.create_task(produce(session_id, command.speed))
                await send({"type": "simulation.started", "payload": {"state": "running", "session_id": session_id}})
            elif command.action == "pause" and task and not task.done() and not paused.is_set():
                paused.set(); set_session_status(session_id, "pausada", "simulation.paused")
                await send({"type": "simulation.paused", "payload": {"state": "paused"}})
            elif command.action == "resume" and task and not task.done() and paused.is_set():
                paused.clear(); set_session_status(session_id, "ao-vivo", "simulation.resumed")
                await send({"type": "simulation.resumed", "payload": {"state": "running"}})
            elif command.action == "stop" and task and not task.done():
                stopped.set(); paused.clear(); await task
    except (WebSocketDisconnect, ValueError):
        if task and not task.done(): task.cancel()
        if session_id: interrupt_if_active(session_id)
