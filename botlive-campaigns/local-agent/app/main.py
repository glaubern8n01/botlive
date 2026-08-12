from __future__ import annotations
import json, os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .adapters import public_adapters
from .security import valid_token
from .store import audit, connect, insert, migrate, now, rows, uid

flag=lambda name,default: os.getenv(name,default).lower()=="true"
def authorize(x_campaigns_token:str|None=Header(default=None)):
    if not flag("CAMPAIGNS_ENABLED","false"): raise HTTPException(404,"Módulo desativado")
    if not valid_token(x_campaigns_token): raise HTTPException(401,"Token local inválido")
@asynccontextmanager
async def lifespan(_:FastAPI): migrate(); yield
app=FastAPI(title="BotLive Campanhas",version="0.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],allow_methods=["GET","POST","PUT"],allow_headers=["Content-Type","X-Campaigns-Token"])
AUTH=[Depends(authorize)]

class CampaignIn(BaseModel):
    platform:str=Field(min_length=2,max_length=80); name:str=Field(min_length=2,max_length=160); url:str=""; niche:str=""; status:str="draft"; starts_at:str|None=None; ends_at:str|None=None; reward_model:str=""; reward_value:float=0; budget:float=0; networks:list[str]=[]; rules:str=""; hashtags:list[str]=[]; mentions:list[str]=[]; min_duration:int|None=None; max_duration:int|None=None; target_profile:str=""; duplicate_policy:str="deny"; automation_policy:str="manual-only"
class CandidateIn(BaseModel):
    campaign_id:str; material_id:str|None=None; source_start:float=0; source_end:float=0; score:float=0; caption:str=""; hook:str=""; idempotency_key:str=Field(min_length=8,max_length=200)
class ReviewIn(BaseModel): action:str; actor:str="operator"; notes:str=""
class PublicationIn(BaseModel): campaign_id:str; candidate_id:str; channel_id:str|None=None; description:str=""; hashtags:list[str]=[]; idempotency_key:str

@app.get("/campaigns/v1/health")
def health(): return {"enabled":flag("CAMPAIGNS_ENABLED","false"),"dry_run":flag("CAMPAIGNS_DRY_RUN","true"),"paused":flag("CAMPAIGNS_PAUSED","false"),"legacy_untouched":True}
@app.get("/campaigns/v1/adapters",dependencies=AUTH)
def adapters(): return public_adapters()
@app.get("/campaigns/v1/campaigns",dependencies=AUTH)
def list_campaigns(): return rows("campaign_campaigns")
@app.post("/campaigns/v1/campaigns",dependencies=AUTH,status_code=201)
def create_campaign(value:CampaignIn):
    data=value.model_dump(); data.update(id=uid(),networks=json.dumps(data["networks"]),hashtags=json.dumps(data["hashtags"]),mentions=json.dumps(data["mentions"]),created_at=now()); insert("campaign_campaigns",data); audit("campaign.created","campaign",data["id"],{"platform":data["platform"]}); return data
@app.get("/campaigns/v1/candidates",dependencies=AUTH)
def list_candidates(): return rows("campaign_candidates")
@app.post("/campaigns/v1/candidates",dependencies=AUTH,status_code=201)
def create_candidate(value:CandidateIn):
    data=value.model_dump(); data.update(id=uid(),version=1,output_path="",status="queued",checklist=json.dumps({"duration":value.source_end>value.source_start,"human_review":False}))
    try: insert("campaign_candidates",data)
    except Exception as exc:
        if "UNIQUE" in str(exc): raise HTTPException(409,"Candidato duplicado") from exc
        raise
    audit("candidate.queued","candidate",data["id"]); return data
@app.post("/campaigns/v1/candidates/{candidate_id}/review",dependencies=AUTH)
def review(candidate_id:str,value:ReviewIn):
    status={"approve":"approved","reject":"rejected","redo":"redo"}.get(value.action)
    if not status: raise HTTPException(422,"Ação inválida")
    with connect() as db:
        if not db.execute("SELECT 1 FROM campaign_candidates WHERE id=?",(candidate_id,)).fetchone(): raise HTTPException(404,"Candidato inexistente")
        db.execute("UPDATE campaign_candidates SET status=? WHERE id=?",(status,candidate_id))
    audit(f"candidate.{status}","candidate",candidate_id,{"notes":value.notes},actor=value.actor); return {"id":candidate_id,"status":status}
@app.get("/campaigns/v1/publications",dependencies=AUTH)
def list_publications(): return rows("campaign_publications")
@app.post("/campaigns/v1/publications",dependencies=AUTH,status_code=201)
def prepare_publication(value:PublicationIn):
    if not flag("CAMPAIGNS_DRY_RUN","true"): raise HTTPException(403,"MVP permite somente exportação manual em dry-run")
    data=value.model_dump(); data.update(id=uid(),mode="manual-export",status="draft",hashtags=json.dumps(data["hashtags"]),published_url="",attempts=0,error="",created_at=now()); insert("campaign_publications",data); audit("publication.draft_prepared","publication",data["id"]); return data
@app.get("/campaigns/v1/audit",dependencies=AUTH)
def list_audit(): return rows("campaign_audit")
@app.post("/campaigns/v1/module/pause",dependencies=AUTH)
def pause_module(): audit("module.pause_requested","module",payload={"legacy_affected":False}); return {"campaign_automation_paused":True,"legacy_affected":False}
