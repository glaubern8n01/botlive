from __future__ import annotations

import asyncio
import re
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import require_http_auth, require_websocket_auth, valid_token
from .database import SessionLocal, get_db
from .models import AuditEvent, LiveSession, MediaAsset, MediaPlayback, Product, ScriptBlock, SessionMaterial
from .schemas import MediaAssetIn, PlaybackControl, ProductIn, ScriptBlockIn, SessionIn, SessionMaterialIn, SimulationControl
from .media_storage import inspect_media, safe_path, store_upload
from .simulator import scenario, stream
import os
from pathlib import Path

CLIENTS: set[WebSocket] = set()
CLIENT_LOCKS: dict[WebSocket,asyncio.Lock] = {}
PLAYBACK_TASKS: dict[str,asyncio.Task] = {}

async def broadcast(event: dict) -> None:
    stale=[]
    for client in list(CLIENTS):
        try:
            async with CLIENT_LOCKS[client]: await client.send_json(event)
        except Exception: stale.append(client)
    for client in stale: CLIENTS.discard(client)

def allowed_origins() -> list[str]:
    return [x.strip() for x in os.getenv("SHOP_LIVE_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if x.strip()]

def allowed_extension_ids() -> set[str]:
    return {value.strip() for value in os.getenv("SHOP_LIVE_ALLOWED_EXTENSION_IDS", "").split(",") if re.fullmatch(r"[a-p]{32}", value.strip())}

def allowed_websocket_origin(origin: str | None) -> bool:
    if origin in allowed_origins(): return True
    match = re.fullmatch(r"chrome-extension://([a-p]{32})", origin or "")
    return bool(match and match.group(1) in allowed_extension_ids())

app = FastAPI(title="BotLive Shop Local Agent", version="0.3.0", docs_url="/shop-live/docs")
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-Shop-Live-Token"])

def serialize(row) -> dict:
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in list(data.items()):
        if hasattr(value, "isoformat"): data[key] = value.isoformat()
    if isinstance(row, LiveSession): data["product_ids"] = list(row.product_order)
    return data

def record(db: Session, kind: str, payload: dict, session_id: str | None = None, result: str = "ok") -> AuditEvent:
    event = AuditEvent(type=kind, payload=payload, session_id=session_id, result=result)
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

@app.put("/shop-live/v1/products/{item_id}", dependencies=AUTH)
def update_product(item_id: str, payload: ProductIn, db: Session = Depends(get_db)):
    item = db.get(Product, item_id)
    if not item: raise HTTPException(404, "Produto inexistente")
    before = serialize(item)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    db.commit(); db.refresh(item); record(db, "product.updated", {"before": before, "after": serialize(item)})
    return serialize(item)

@app.delete("/shop-live/v1/products/{item_id}", status_code=204, dependencies=AUTH)
def delete_product(item_id: str, db: Session = Depends(get_db)):
    item = db.get(Product, item_id)
    if not item: raise HTTPException(404, "Produto inexistente")
    before = serialize(item); db.delete(item); db.commit(); record(db, "product.deleted", {"before": before})

@app.post("/shop-live/v1/sessions", status_code=201, dependencies=AUTH)
def create_session(payload: SessionIn, db: Session = Depends(get_db)):
    if len(payload.product_ids) != len(set(payload.product_ids)): raise HTTPException(422, "Produtos duplicados")
    products = db.scalars(select(Product).where(Product.id.in_(payload.product_ids))).all() if payload.product_ids else []
    if set(payload.product_ids) != {item.id for item in products}: raise HTTPException(422, "Produto inexistente")
    item = LiveSession(title=payload.title, estimated_minutes=payload.estimated_minutes, seed=payload.seed, products=list(products), product_order=list(payload.product_ids))
    db.add(item); db.commit(); db.refresh(item)
    record(db, "session.created", {"product_ids": payload.product_ids, "seed": payload.seed}, item.id); return serialize(item)

@app.get("/shop-live/v1/sessions", dependencies=AUTH)
def list_sessions(db: Session = Depends(get_db)):
    return [serialize(row) for row in db.scalars(select(LiveSession).order_by(LiveSession.created_at)).all()]

@app.put("/shop-live/v1/sessions/{item_id}", dependencies=AUTH)
def update_session(item_id: str, payload: SessionIn, db: Session = Depends(get_db)):
    item = db.get(LiveSession, item_id)
    if not item: raise HTTPException(404, "Sessão inexistente")
    if len(payload.product_ids) != len(set(payload.product_ids)): raise HTTPException(422, "Produtos duplicados")
    products = db.scalars(select(Product).where(Product.id.in_(payload.product_ids))).all() if payload.product_ids else []
    by_id = {product.id: product for product in products}
    if set(payload.product_ids) != set(by_id): raise HTTPException(422, "Produto inexistente")
    before=serialize(item); item.title=payload.title; item.estimated_minutes=payload.estimated_minutes; item.seed=payload.seed; item.products=[by_id[value] for value in payload.product_ids]; item.product_order=list(payload.product_ids)
    db.commit(); db.refresh(item); record(db,"session.updated",{"before":before,"after":serialize(item)},item_id); return serialize(item)

@app.get("/shop-live/v1/audit", dependencies=AUTH)
def audit(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    total = len(db.scalars(select(AuditEvent.id)).all())
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [serialize(row) for row in rows], "limit": limit, "offset": offset, "total": total}

@app.get("/shop-live/v1/simulation/{seed}", dependencies=AUTH)
def simulation(seed: int): return scenario(seed)

@app.post("/shop-live/v1/media", status_code=201, dependencies=AUTH)
def create_media(payload: MediaAssetIn, db: Session = Depends(get_db)):
    if payload.product_id and not db.get(Product, payload.product_id): raise HTTPException(422, "Produto inexistente")
    if payload.authorized and not payload.authorization_source.strip(): raise HTTPException(422, "Informe a origem da autorização")
    item = MediaAsset(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item)
    record(db, "media.created", {"media_id":item.id,"kind":item.kind,"authorized":item.authorized}); return serialize(item)

@app.get("/shop-live/v1/media", dependencies=AUTH)
def list_media(kind: str | None = None, product_id: str | None = None, db: Session = Depends(get_db)):
    query = select(MediaAsset).order_by(MediaAsset.created_at)
    if kind: query = query.where(MediaAsset.kind == kind)
    if product_id: query = query.where(MediaAsset.product_id == product_id)
    return [serialize(row) for row in db.scalars(query).all()]

@app.post("/shop-live/v1/media/upload", status_code=201, dependencies=AUTH)
async def upload_media(file: UploadFile = File(...), product_id: str | None = Form(default=None), authorized: bool = Form(...), authorization_source: str = Form(...), db: Session = Depends(get_db)):
    product_id=product_id or None
    stored_path: Path | None = None
    if not authorized: raise HTTPException(422,"O operador deve autorizar o arquivo")
    if not authorization_source.strip(): raise HTTPException(422,"Informe a origem da autorização")
    if product_id and not db.get(Product,product_id): raise HTTPException(422,"Produto inexistente")
    try:
        stored_name,stored_path,size,mime,extension=await store_upload(file)
        metadata=inspect_media(stored_path,extension);kind="video" if metadata.get("width") else "audio"
        item=MediaAsset(product_id=product_id,kind=kind,name=Path(file.filename or "Mídia autorizada").name[:160],local_path=stored_name,duration_seconds=max(0,int(round(metadata["duration_seconds"]))),duration_milliseconds=max(0,int(round(metadata["duration_seconds"]*1000))),authorized=True,authorization_source=authorization_source.strip(),stored_name=stored_name,mime_type=mime,size_bytes=size,format_name=metadata["format_name"],width=metadata["width"],height=metadata["height"])
        db.add(item);db.commit();db.refresh(item);record(db,"media.uploaded",{"media_id":item.id,"size_bytes":size,"format":metadata["format_name"],"authorized":True});return serialize(item)
    except ValueError as error:
        record(db,"media.upload_failed",{"filename":Path(file.filename or "").name,"reason":str(error)},result="blocked")
        raise HTTPException(422,str(error))
    except Exception as error:
        if stored_path: stored_path.unlink(missing_ok=True)
        record(db,"media.upload_failed",{"filename":Path(file.filename or "").name,"reason":type(error).__name__},result="error")
        raise HTTPException(500,"Falha ao armazenar mídia")

@app.get("/shop-live/v1/media/{item_id}/content")
def media_content(item_id: str, token: str | None = None, db: Session = Depends(get_db)):
    if not valid_token(token): raise HTTPException(401,"Token local inválido")
    item=db.get(MediaAsset,item_id)
    if not item or not item.stored_name: raise HTTPException(404,"Arquivo inexistente")
    try: path=safe_path(item.stored_name)
    except ValueError: raise HTTPException(403,"Caminho de mídia inválido")
    if not path.is_file(): raise HTTPException(404,"Arquivo inexistente")
    return FileResponse(path,media_type=item.mime_type,filename=item.name,content_disposition_type="inline")

@app.put("/shop-live/v1/media/{item_id}", dependencies=AUTH)
def update_media(item_id: str, payload: MediaAssetIn, db: Session = Depends(get_db)):
    item=db.get(MediaAsset,item_id)
    if not item: raise HTTPException(404,"Mídia inexistente")
    if payload.product_id and not db.get(Product,payload.product_id): raise HTTPException(422,"Produto inexistente")
    if payload.authorized and not payload.authorization_source.strip(): raise HTTPException(422,"Informe a origem da autorização")
    before=serialize(item)
    for key,value in payload.model_dump().items(): setattr(item,key,value)
    db.commit(); db.refresh(item); record(db,"media.updated",{"before":before,"after":serialize(item)}); return serialize(item)

@app.delete("/shop-live/v1/media/{item_id}", status_code=204, dependencies=AUTH)
def delete_media(item_id: str, db: Session = Depends(get_db)):
    item=db.get(MediaAsset,item_id)
    if not item: raise HTTPException(404,"Mídia inexistente")
    usage=db.scalar(select(SessionMaterial).where(SessionMaterial.media_id == item_id).limit(1))
    if usage:
        record(db,"media.delete_blocked",{"media_id":item_id,"session_id":usage.session_id},result="blocked")
        raise HTTPException(409,"Media utilizada por uma sessao")
    before=serialize(item); path=None
    if item.stored_name:
        try: path=safe_path(item.stored_name)
        except ValueError:
            record(db,"media.delete_failed",{"media_id":item_id,"reason":"unsafe_path"},result="blocked")
            raise HTTPException(403,"Caminho de media invalido")
    db.delete(item); db.commit()
    if path and path.exists(): path.unlink()
    record(db,"media.deleted",{"before":before})

@app.post("/shop-live/v1/scripts", status_code=201, dependencies=AUTH)
def create_script_block(payload: ScriptBlockIn, db: Session = Depends(get_db)):
    if not db.get(Product, payload.product_id): raise HTTPException(422, "Produto inexistente")
    item = ScriptBlock(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item)
    record(db, "script.created", {"script_id":item.id,"product_id":item.product_id}); return serialize(item)

@app.get("/shop-live/v1/products/{product_id}/scripts", dependencies=AUTH)
def list_script_blocks(product_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(ScriptBlock).where(ScriptBlock.product_id == product_id).order_by(ScriptBlock.position)).all()
    return [serialize(row) for row in rows]

@app.put("/shop-live/v1/scripts/{item_id}", dependencies=AUTH)
def update_script(item_id: str, payload: ScriptBlockIn, db: Session = Depends(get_db)):
    item=db.get(ScriptBlock,item_id)
    if not item: raise HTTPException(404,"Bloco inexistente")
    if not db.get(Product,payload.product_id): raise HTTPException(422,"Produto inexistente")
    before=serialize(item)
    for key,value in payload.model_dump().items(): setattr(item,key,value)
    db.commit(); db.refresh(item); record(db,"script.updated",{"before":before,"after":serialize(item)}); return serialize(item)

@app.delete("/shop-live/v1/scripts/{item_id}", status_code=204, dependencies=AUTH)
def delete_script(item_id: str, db: Session = Depends(get_db)):
    item=db.get(ScriptBlock,item_id)
    if not item: raise HTTPException(404,"Bloco inexistente")
    before=serialize(item); db.delete(item); db.commit(); record(db,"script.deleted",{"before":before})

@app.put("/shop-live/v1/sessions/{session_id}/materials", dependencies=AUTH)
def set_session_materials(session_id: str, payload: list[SessionMaterialIn], db: Session = Depends(get_db)):
    if not db.get(LiveSession, session_id): raise HTTPException(404, "Sessão inexistente")
    ids = [item.media_id for item in payload]
    positions = [item.position for item in payload]
    if len(ids) != len(set(ids)): raise HTTPException(422, "Mídia duplicada na sessão")
    if len(positions) != len(set(positions)): raise HTTPException(422, "Posições devem ser únicas")
    media = db.scalars(select(MediaAsset).where(MediaAsset.id.in_(ids))).all() if ids else []
    if set(ids) != {item.id for item in media}: raise HTTPException(422, "Mídia inexistente")
    if any(not item.authorized for item in media): raise HTTPException(422, "Somente mídia autorizada pode entrar na sessão")
    db.query(SessionMaterial).filter(SessionMaterial.session_id == session_id).delete()
    db.add_all([SessionMaterial(session_id=session_id, **item.model_dump()) for item in payload]); db.commit()
    record(db, "session.materials_updated", {"count":len(payload)}, session_id)
    return {"items":[item.model_dump() for item in sorted(payload,key=lambda x:x.position)]}

@app.get("/shop-live/v1/sessions/{session_id}/materials", dependencies=AUTH)
def list_session_materials(session_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(SessionMaterial).where(SessionMaterial.session_id == session_id).order_by(SessionMaterial.position)).all()
    return {"items":[{**serialize(row),"media":serialize(db.get(MediaAsset,row.media_id))} for row in rows]}

def playback_payload(db: Session, session_id: str) -> dict:
    state=db.get(MediaPlayback,session_id)
    if not state:
        state=MediaPlayback(session_id=session_id);db.add(state);db.commit();db.refresh(state)
    media=db.get(MediaAsset,state.media_id) if state.media_id else None
    return {**serialize(state),"media":serialize(media) if media else None}

def playback_queue(db: Session, session_id: str):
    return db.scalars(select(SessionMaterial).where(SessionMaterial.session_id == session_id).order_by(SessionMaterial.position)).all()

async def publish_playback(session_id: str) -> None:
    with SessionLocal() as db: payload=playback_payload(db,session_id)
    await broadcast({"type":"media.playback_state","payload":payload})

async def playback_clock(session_id: str) -> None:
    while True:
        await asyncio.sleep(1)
        with SessionLocal() as db:
            state=db.get(MediaPlayback,session_id)
            if not state or state.status == "stopped": return
            if state.status != "playing": continue
            queue=playback_queue(db,session_id)
            if not queue or state.queue_index >= len(queue):
                state.status="stopped";state.media_id=None;db.commit();continue
            current=queue[state.queue_index];state.position_seconds += 1
            if state.position_seconds >= current.planned_duration_seconds:
                if state.queue_index + 1 < len(queue):
                    state.queue_index += 1;state.media_id=queue[state.queue_index].media_id;state.position_seconds=0
                    record(db,"playback.advanced",{"media_id":state.media_id,"automatic":True},session_id)
                else:
                    state.status="stopped";state.position_seconds=0
                    record(db,"playback.stopped",{"reason":"queue_completed"},session_id)
            db.commit()
        await publish_playback(session_id)

@app.get("/shop-live/v1/sessions/{session_id}/playback", dependencies=AUTH)
def get_playback(session_id: str, db: Session = Depends(get_db)):
    if not db.get(LiveSession,session_id): raise HTTPException(404,"Sessao inexistente")
    return playback_payload(db,session_id)

@app.post("/shop-live/v1/sessions/{session_id}/playback/control", dependencies=AUTH)
async def control_playback(session_id: str, payload: PlaybackControl, db: Session = Depends(get_db)):
    if not db.get(LiveSession,session_id): raise HTTPException(404,"Sessao inexistente")
    queue=playback_queue(db,session_id);state=db.get(MediaPlayback,session_id) or MediaPlayback(session_id=session_id)
    if not queue:
        record(db,"playback.failed",{"action":payload.action,"reason":"empty_queue"},session_id,result="blocked")
        raise HTTPException(422,"A sessao nao possui midias")
    events={"start":"playback.started","pause":"playback.paused","resume":"playback.resumed","next":"playback.advanced","stop":"playback.stopped"}
    if payload.action == "start": state.queue_index=0;state.media_id=queue[0].media_id;state.position_seconds=0;state.status="playing"
    elif payload.action == "pause":
        if state.status != "playing": raise HTTPException(409,"Reproducao nao iniciada")
        state.status="paused"
    elif payload.action == "resume":
        if state.status != "paused": raise HTTPException(409,"Reproducao nao pausada")
        state.status="playing"
    elif payload.action == "next":
        if state.queue_index + 1 >= len(queue): state.status="stopped";state.position_seconds=0
        else: state.queue_index+=1;state.media_id=queue[state.queue_index].media_id;state.position_seconds=0;state.status="playing"
    else: state.status="stopped";state.position_seconds=0
    db.add(state);db.commit();db.refresh(state);record(db,events[payload.action],{"media_id":state.media_id,"queue_index":state.queue_index},session_id)
    if payload.action in {"start","resume","next"} and (session_id not in PLAYBACK_TASKS or PLAYBACK_TASKS[session_id].done()):
        PLAYBACK_TASKS[session_id]=asyncio.create_task(playback_clock(session_id))
    result=playback_payload(db,session_id);await broadcast({"type":"media.playback_state","payload":result});return result

def operation_context(db: Session, live: LiveSession) -> dict:
    by_id={product.id:product for product in live.products}; products=[by_id[value] for value in live.product_order if value in by_id]; current=products[0] if products else None; following=products[1] if len(products)>1 else None
    scripts=db.scalars(select(ScriptBlock).where(ScriptBlock.product_id == current.id).order_by(ScriptBlock.position)).all() if current else []
    materials=db.scalars(select(SessionMaterial).where(SessionMaterial.session_id == live.id).order_by(SessionMaterial.position)).all()
    return {"session_id":live.id,"session_title":live.title,"current_product":serialize(current) if current else None,"next_product":serialize(following) if following else None,"scripts":[serialize(row) for row in scripts],"materials":[serialize(row) for row in materials]}

@app.get("/shop-live/v1/sessions/{session_id}/operation", dependencies=AUTH)
def get_operation(session_id: str, db: Session = Depends(get_db)):
    live=db.get(LiveSession,session_id)
    if not live: raise HTTPException(404,"Sessão inexistente")
    return operation_context(db,live)

@app.get("/shop-live/simulator-page", response_class=HTMLResponse)
def simulator_page():
    return """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Shop LIVE Simulator</title></head><body data-shop-live-simulator='true'><main><h1>Página simulada Shop LIVE</h1><p>Nenhuma conta real é acessada.</p><section data-current-product='Produto simulado A'>Produto atual: Produto simulado A</section><section data-next-product='Produto simulado B'>Próximo: Produto simulado B</section><section data-comment-count='0'>0 comentários simulados</section><div role='alert' data-alert-level='ok'>Sem alertas</div></main><script>document.body.dataset.snapshotId='snapshot-'+crypto.randomUUID();let tick=0;setInterval(()=>{tick++;const current=document.querySelector('[data-current-product]'),next=document.querySelector('[data-next-product]'),comments=document.querySelector('[data-comment-count]'),alert=document.querySelector('[role=alert]');if(tick===2){current.dataset.currentProduct='Produto simulado B';current.textContent='Produto atual: Produto simulado B';next.dataset.nextProduct='Produto simulado C';next.textContent='Próximo: Produto simulado C'}comments.dataset.commentCount=String(tick);comments.textContent=tick+' comentários simulados';if(tick===3){alert.dataset.alertLevel='attention';alert.textContent='Áudio baixo (simulado)' }},700)</script></body></html>"""

@app.websocket("/shop-live/v1/events")
async def events(socket: WebSocket):
    if not allowed_websocket_origin(socket.headers.get("origin")) or not await require_websocket_auth(socket):
        await socket.close(code=1008); return
    await socket.accept()
    CLIENTS.add(socket)
    CLIENT_LOCKS[socket]=asyncio.Lock()
    await socket.send_json({"type": "simulation.ready", "payload": {"seed": 42, "state": "ready"}})
    paused, stopped, send_lock = asyncio.Event(), asyncio.Event(), CLIENT_LOCKS[socket]
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
                    if command.session_id:
                        selected = db.get(LiveSession, command.session_id)
                        if not selected:
                            await send({"type":"command.rejected","payload":{"reason":"session_not_found"}}); continue
                        live = selected
                    live.status = "ao-vivo"; db.add(live); db.commit(); db.refresh(live); session_id = live.id
                    record(db, "simulation.started", {"seed": 42}, session_id)
                    context = operation_context(db, live)
                await send({"type":"operation.context","payload":context})
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
    finally:
        CLIENTS.discard(socket)
        CLIENT_LOCKS.pop(socket,None)
