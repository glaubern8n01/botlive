from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from .auth import require_http_auth
from .database import SessionLocal, get_db
from .media_storage import safe_path, storage_root
from .paths import BACKUP_ROOT, DATABASE_PATH, DATA_ROOT, RUN_ROOT
from .models import AuditEvent, LiveSession, LocalSetting, MediaAsset, MediaPlayback, Product, ScriptBlock, SessionMaterial, SessionRuntime
from .realtime import broadcast
from .schemas import DiagnosticIn, RuntimeControl, SettingIn

router=APIRouter(prefix="/shop-live/v1",dependencies=[Depends(require_http_auth)])

def serialize(row):
    data={column.name:getattr(row,column.name) for column in row.__table__.columns}
    for key,value in list(data.items()):
        if hasattr(value,"isoformat"): data[key]=value.isoformat()
    return data

def audit(db:Session,kind:str,payload:dict,session_id:str|None=None,result="ok"):
    item=AuditEvent(type=kind,payload=payload,session_id=session_id,result=result);db.add(item);db.commit();return item

def runtime_state(db:Session,session_id:str):
    live=db.get(LiveSession,session_id)
    if not live: raise HTTPException(404,"Sessão inexistente")
    runtime=db.get(SessionRuntime,session_id)
    if not runtime: runtime=SessionRuntime(session_id=session_id);db.add(runtime);db.commit();db.refresh(runtime)
    if runtime.status=="running" and runtime.started_at:
        started=runtime.started_at if runtime.started_at.tzinfo else runtime.started_at.replace(tzinfo=timezone.utc)
        runtime.elapsed_seconds=max(runtime.elapsed_seconds,int((datetime.now(timezone.utc)-started).total_seconds()))
    queue=db.scalars(select(SessionMaterial).where(SessionMaterial.session_id==session_id).order_by(SessionMaterial.position)).all()
    current=queue[runtime.current_index] if queue and runtime.current_index<len(queue) else None
    previous=queue[runtime.current_index-1] if queue and runtime.current_index>0 else None
    following=queue[runtime.current_index+1] if queue and runtime.current_index+1<len(queue) else None
    media=db.get(MediaAsset,current.media_id) if current else None
    product=db.get(Product,current.product_id) if current and current.product_id else None
    script=db.get(ScriptBlock,current.script_id) if current and current.script_id else None
    alerts=[]
    if runtime.elapsed_seconds>live.estimated_minutes*60: alerts.append("session_long")
    if current and runtime.elapsed_seconds>sum(x.planned_duration_seconds for x in queue[:runtime.current_index+1]): alerts.append("script_late")
    if media and media.stored_name:
        try:
            if not safe_path(media.stored_name).is_file(): alerts.append("media_missing")
        except ValueError: alerts.append("media_missing")
    return {**serialize(runtime),"session":serialize(live),"queue_length":len(queue),"current":serialize(current) if current else None,"previous":serialize(previous) if previous else None,"next":serialize(following) if following else None,"media":serialize(media) if media else None,"product":serialize(product) if product else None,"script":serialize(script) if script else None,"alerts":alerts}

@router.get("/library")
def library(q:str="",kind:str="all",tag:str="",active:bool|None=None,db:Session=Depends(get_db)):
    term=f"%{q.strip()}%"
    products=select(Product);media=select(MediaAsset);scripts=select(ScriptBlock)
    if q: products=products.where(or_(Product.name.ilike(term),Product.category.ilike(term),Product.notes.ilike(term)));media=media.where(or_(MediaAsset.name.ilike(term),MediaAsset.notes.ilike(term)));scripts=scripts.where(or_(ScriptBlock.title.ilike(term),ScriptBlock.text.ilike(term)))
    if active is not None: products=products.where(Product.active==active)
    product_rows=db.scalars(products.order_by(Product.created_at.desc())).all() if kind in {"all","product"} else []
    media_rows=db.scalars(media.order_by(MediaAsset.created_at.desc())).all() if kind in {"all","video","audio"} else []
    if kind in {"video","audio"}: media_rows=[row for row in media_rows if row.kind==kind]
    script_rows=db.scalars(scripts.order_by(ScriptBlock.created_at.desc())).all() if kind in {"all","script"} else []
    if tag:
        product_rows=[row for row in product_rows if tag in row.tags];media_rows=[row for row in media_rows if tag in row.tags]
    return {"products":[serialize(x) for x in product_rows],"media":[serialize(x) for x in media_rows],"scripts":[serialize(x) for x in script_rows]}

@router.post("/products/{item_id}/duplicate",status_code=201)
def duplicate_product(item_id:str,db:Session=Depends(get_db)):
    source=db.get(Product,item_id)
    if not source: raise HTTPException(404,"Produto inexistente")
    item=Product(name=f"{source.name} (cópia)",category=source.category,price=source.price,approved_answers=list(source.approved_answers),prohibited_claims=list(source.prohibited_claims),tags=list(source.tags),notes=source.notes,active=source.active);db.add(item);db.commit();db.refresh(item);audit(db,"product.duplicated",{"source_id":item_id,"product_id":item.id});return serialize(item)

@router.post("/scripts/{item_id}/duplicate",status_code=201)
def duplicate_script(item_id:str,db:Session=Depends(get_db)):
    source=db.get(ScriptBlock,item_id)
    if not source: raise HTTPException(404,"Roteiro inexistente")
    item=ScriptBlock(product_id=source.product_id,kind=source.kind,position=source.position+1,duration_seconds=source.duration_seconds,text=source.text,title=f"{source.title or source.kind} (cópia)");db.add(item);db.commit();db.refresh(item);audit(db,"script.duplicated",{"source_id":item_id,"script_id":item.id});return serialize(item)

@router.post("/media/{item_id}/duplicate",status_code=201)
def duplicate_media(item_id:str,db:Session=Depends(get_db)):
    source=db.get(MediaAsset,item_id)
    if not source or not source.stored_name: raise HTTPException(404,"Mídia local inexistente")
    original=safe_path(source.stored_name);limit=int(os.getenv("SHOP_LIVE_MEDIA_TOTAL_MAX_BYTES",str(10*1024**3)));used=sum(x.stat().st_size for x in storage_root().iterdir() if x.is_file())
    if used+original.stat().st_size>limit: raise HTTPException(413,"Armazenamento local atingiu o limite configurado")
    new_name=f"{uuid4().hex}{original.suffix.lower()}";target=safe_path(new_name);shutil.copyfile(original,target)
    try:
        item=MediaAsset(product_id=source.product_id,kind=source.kind,name=f"{source.name} (cópia)",local_path=new_name,duration_seconds=source.duration_seconds,duration_milliseconds=source.duration_milliseconds,authorized=True,authorization_source=source.authorization_source,stored_name=new_name,mime_type=source.mime_type,size_bytes=source.size_bytes,format_name=source.format_name,width=source.width,height=source.height,tags=list(source.tags),notes=source.notes);db.add(item);db.commit();db.refresh(item);audit(db,"media.duplicated",{"source_id":item_id,"media_id":item.id});return serialize(item)
    except Exception:
        db.rollback();target.unlink(missing_ok=True);raise

@router.get("/sessions/{session_id}/runtime")
def get_runtime(session_id:str,db:Session=Depends(get_db)): return runtime_state(db,session_id)

@router.post("/sessions/{session_id}/runtime/control")
async def control_runtime(session_id:str,payload:RuntimeControl,db:Session=Depends(get_db)):
    state=runtime_state(db,session_id);runtime=db.get(SessionRuntime,session_id);live=db.get(LiveSession,session_id);queue=db.scalars(select(SessionMaterial).where(SessionMaterial.session_id==session_id).order_by(SessionMaterial.position)).all()
    if payload.action in {"start_rehearsal","start_operation"}:
        if not queue: raise HTTPException(422,"Monte a fila antes de iniciar")
        runtime.mode="rehearsal" if payload.action=="start_rehearsal" else "assisted";runtime.status="running";runtime.started_at=datetime.now(timezone.utc);runtime.elapsed_seconds=0;runtime.ended_at=None;runtime.current_index=0;live.status="ensaio" if runtime.mode=="rehearsal" else "ao-vivo-assistida"
    elif payload.action=="pause":
        current=runtime_state(db,session_id);runtime.elapsed_seconds=current["elapsed_seconds"];runtime.started_at=None;runtime.status="paused";runtime.teleprompter_paused=True
    elif payload.action=="resume": runtime.status="running";runtime.started_at=datetime.now(timezone.utc)-timedelta(seconds=runtime.elapsed_seconds)
    elif payload.action=="next": runtime.current_index=min(runtime.current_index+1,max(0,len(queue)-1));runtime.script_index=0
    elif payload.action=="previous": runtime.current_index=max(0,runtime.current_index-1);runtime.script_index=0
    elif payload.action=="stop":
        current=runtime_state(db,session_id);runtime.elapsed_seconds=current["elapsed_seconds"];runtime.status="completed";runtime.started_at=None;runtime.ended_at=datetime.now(timezone.utc);runtime.teleprompter_paused=True;live.status="encerrada"
    elif payload.action=="teleprompter":
        if payload.speed is not None: runtime.teleprompter_speed=payload.speed
        if payload.font_size is not None: runtime.teleprompter_font_size=payload.font_size
        if payload.teleprompter_paused is not None: runtime.teleprompter_paused=payload.teleprompter_paused
    db.commit();audit(db,f"runtime.{payload.action}",payload.model_dump(exclude_none=True),session_id);result=runtime_state(db,session_id);await broadcast({"type":"session.runtime","payload":result});return result

@router.post("/sessions/{session_id}/diagnostics")
async def diagnostics(session_id:str,payload:DiagnosticIn,db:Session=Depends(get_db)):
    if not db.get(LiveSession,session_id): raise HTTPException(404,"Sessão inexistente")
    problems=[]
    if payload.camera in {"missing","denied","frozen"}: problems.append(f"camera_{payload.camera}")
    if payload.microphone in {"missing","denied","silent"}: problems.append(f"microphone_{payload.microphone}")
    if payload.connection != "ok": problems.append(f"connection_{payload.connection}")
    kind="diagnostic.alert" if problems else "diagnostic.ok";audit(db,kind,{**payload.model_dump(),"problems":problems},session_id,"warning" if problems else "ok")
    event={"type":"operation.alert" if problems else "operation.diagnostic","payload":{"problems":problems,**payload.model_dump()}};await broadcast(event);return event["payload"]

@router.post("/sessions/{session_id}/comments/simulated",status_code=201)
async def simulated_comment(session_id:str,text:str=Query(min_length=1,max_length=300),author:str=Query(default="Pessoa simulada",max_length=80),db:Session=Depends(get_db)):
    if not db.get(LiveSession,session_id): raise HTTPException(404,"Sessão inexistente")
    payload={"text":text,"author":author,"simulated":True,"source":"test-interface"};audit(db,"comment.simulated",payload,session_id);await broadcast({"type":"comment.simulated","payload":payload});return payload

@router.get("/sessions/{session_id}/report")
def report(session_id:str,format:str="json",db:Session=Depends(get_db)):
    live=db.get(LiveSession,session_id)
    if not live: raise HTTPException(404,"Sessão inexistente")
    events=db.scalars(select(AuditEvent).where(AuditEvent.session_id==session_id).order_by(AuditEvent.created_at)).all();runtime=db.get(SessionRuntime,session_id);materials=db.scalars(select(SessionMaterial).where(SessionMaterial.session_id==session_id).order_by(SessionMaterial.position)).all()
    payload={"session":serialize(live),"runtime":serialize(runtime) if runtime else None,"summary":{"events":len(events),"problems":sum(1 for x in events if x.result not in {"ok"}),"pauses":sum(1 for x in events if "pause" in x.type),"materials":len(materials)},"materials":[serialize(x) for x in materials],"events":[serialize(x) for x in events]}
    audit(db,"report.exported",{"format":format},session_id)
    if format=="json": return payload
    if format!="csv": raise HTTPException(422,"Formato deve ser json ou csv")
    output=io.StringIO();writer=csv.writer(output);writer.writerow(["timestamp","type","result","source","payload"])
    for item in events: writer.writerow([item.created_at.isoformat(),item.type,item.result,item.source,json.dumps(item.payload,ensure_ascii=False)])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="shop-live-{session_id}.csv"'})

@router.get("/settings")
def settings(db:Session=Depends(get_db)): return {row.key:row.value for row in db.scalars(select(LocalSetting)).all()}

@router.put("/settings/{key}")
def save_setting(key:str,payload:SettingIn,db:Session=Depends(get_db)):
    if key not in {"hotkeys","devices","checklist","storage","ui"}: raise HTTPException(422,"Configuração não permitida")
    if key=="hotkeys" and (set(payload.value.values())!={"pause","next","previous","teleprompter"} or len(payload.value)!=4): raise HTTPException(422,"Atalhos conflitantes ou incompletos")
    item=db.get(LocalSetting,key) or LocalSetting(key=key);item.value=payload.value;db.add(item);db.commit();audit(db,"settings.updated",{"key":key});return serialize(item)

@router.get("/storage")
def storage(db:Session=Depends(get_db)):
    root=storage_root();used=sum(path.stat().st_size for path in root.iterdir() if path.is_file());limit=int(os.getenv("SHOP_LIVE_MEDIA_TOTAL_MAX_BYTES",str(10*1024**3)));return {"root":str(root),"used_bytes":used,"limit_bytes":limit,"free_bytes":max(0,limit-used),"file_count":sum(1 for x in root.iterdir() if x.is_file())}

@router.get("/paths")
def paths(): return {"data":str(DATA_ROOT),"database":str(DATABASE_PATH),"media":str(storage_root()),"backups":str(BACKUP_ROOT),"run":str(RUN_ROOT)}

@router.post("/storage/cleanup")
def cleanup_storage(db:Session=Depends(get_db)):
    known={x.stored_name for x in db.scalars(select(MediaAsset)).all() if x.stored_name};removed=[]
    for path in storage_root().iterdir():
        if path.is_file() and path.name not in known: removed.append(path.name);path.unlink()
    audit(db,"storage.cleaned",{"removed":removed});return {"removed":removed,"count":len(removed)}

@router.post("/backup")
def backup(db:Session=Depends(get_db)):
    target=BACKUP_ROOT/f"shop-live-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.zip";descriptor,snapshot_name=tempfile.mkstemp(prefix="snapshot-",suffix=".db",dir=BACKUP_ROOT);os.close(descriptor);snapshot=Path(snapshot_name)
    try:
        source=sqlite3.connect(DATABASE_PATH);destination=sqlite3.connect(snapshot)
        try: source.backup(destination)
        finally: destination.close();source.close()
        with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot,"database.sqlite")
            for path in storage_root().iterdir():
                if path.is_file(): archive.write(path,f"media/{path.name}")
    finally: snapshot.unlink(missing_ok=True)
    audit(db,"backup.created",{"filename":target.name,"size_bytes":target.stat().st_size});return {"filename":target.name,"size_bytes":target.stat().st_size,"root":str(BACKUP_ROOT)}

@router.get("/integrations/tiktok")
def tiktok_status():
    return {"status":"requires_platform_approval","connected":False,"external_actions":False,"supported_adapter_scope":["catalog_read","orders_webhooks"],"unsupported_without_official_api":["live_studio_control","comments_write","live_start_stop"],"required":["Partner Center app","approved scopes","seller authorization","development shop"]}
