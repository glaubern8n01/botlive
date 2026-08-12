from __future__ import annotations
import json,os,secrets,time,zipfile
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from fastapi import Depends,FastAPI,File,Form,Header,HTTPException,Query,Request,UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,PlainTextResponse
from pydantic import BaseModel,Field
from .adapters import public_adapters
from .auth import require,rate_limit,token_hash
from .media import accepted_root,safe_path,validate_upload
from .platform_catalog import PLATFORMS
from .queue import cancel,enqueue,recover_orphans
from .store import ROOT,audit,connect,get,insert,migrate,now,rows,uid,update

@asynccontextmanager
async def lifespan(_:FastAPI):migrate();recover_orphans();yield
app=FastAPI(title="BotLive Campanhas",version="1.0.0",lifespan=lifespan)
origins=[x.strip() for x in os.getenv("CAMPAIGNS_ALLOWED_ORIGINS","http://localhost:3000,http://127.0.0.1:3000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,allow_methods=["GET","POST","PUT","DELETE"],allow_headers=["Content-Type","X-Campaigns-Token"])

class CampaignIn(BaseModel):
 platform:str=Field(min_length=2,max_length=80);name:str=Field(min_length=2,max_length=160);url:str="";niche:str="";status:str="draft";starts_at:str|None=None;ends_at:str|None=None;reward_model:str="";reward_value:float=0;budget:float=0;networks:list[str]=[];rules:dict={};hashtags:list[str]=[];mentions:list[str]=[];min_duration:int|None=None;max_duration:int|None=None;target_profile:str="";duplicate_policy:str="deny";automation_policy:str="manual-only"
class ChannelIn(BaseModel):network:str;handle:str;niche:str="";auth_state:str="manual";permissions:list[str]=[];daily_limit:int=0;token_hint:str=""
class ReviewIn(BaseModel):action:str;notes:str="";caption:str|None=None;hook:str|None=None
class JobIn(BaseModel):material_id:str;max_candidates:int=Field(8,ge=1,le=50);clip_duration:int=Field(45,ge=6,le=180);min_gap_seconds:int=Field(45,ge=0,le=3600);min_score:float=Field(0,ge=0,le=1);layout:str="vertical-fit";idempotency_key:str
class RenderIn(BaseModel):idempotency_key:str
class PublicationIn(BaseModel):campaign_id:str;candidate_id:str;channel_id:str|None=None;description:str="";hashtags:list[str]=[];idempotency_key:str
class ResultIn(BaseModel):campaign_id:str;publication_id:str|None=None;reported_views:int=0;validated_views:int=0;ranking:int|None=None;estimated_revenue:float=0;confirmed_revenue:float=0;processing_cost:float=0;payment_status:str="pending";notes:str=""
class PublishedIn(BaseModel):published_url:str=Field(pattern=r"^https://");status:str="published_manual"
class SettingIn(BaseModel):value:dict

def page(table,limit,offset):return {"items":rows(table,limit,offset),"limit":limit,"offset":offset}
def encoded_campaign(value):
 data=value.model_dump();data.update(networks=json.dumps(data["networks"]),rules=json.dumps(data["rules"]),hashtags=json.dumps(data["hashtags"]),mentions=json.dumps(data["mentions"]));return data
@app.get("/campaigns/v1/health")
def health():return {"ok":True,"enabled":os.getenv("CAMPAIGNS_ENABLED","false").lower()=="true","dry_run":os.getenv("CAMPAIGNS_DRY_RUN","true").lower()=="true","paused":os.getenv("CAMPAIGNS_PAUSED","false").lower()=="true","legacy_untouched":True,"schema_version":2}
@app.get("/campaigns/v1/adapters",dependencies=[Depends(require("read"))])
def adapters():return public_adapters()
@app.get("/campaigns/v1/platforms",dependencies=[Depends(require("read"))])
def platforms():return {"items":PLATFORMS,"verified_at":"2026-08-12"}
@app.get("/campaigns/v1/campaigns",dependencies=[Depends(require("read"))])
def campaigns(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):return page("campaign_campaigns",limit,offset)
@app.post("/campaigns/v1/campaigns",status_code=201)
def create_campaign(value:CampaignIn,user=Depends(require("write"))):
 stamp=now();data=encoded_campaign(value);data.update(id=uid(),archived=0,created_at=stamp,updated_at=stamp);insert("campaign_campaigns",data);audit("campaign.created","campaign",data["id"],actor=user["actor"],role=user["role"]);return data
@app.put("/campaigns/v1/campaigns/{item_id}")
def edit_campaign(item_id:str,value:CampaignIn,user=Depends(require("write"))):
 data=encoded_campaign(value);data["updated_at"]=now()
 try:result=update("campaign_campaigns",item_id,data)
 except KeyError:raise HTTPException(404,"Campanha inexistente")
 audit("campaign.updated","campaign",item_id,actor=user["actor"],role=user["role"]);return result
@app.delete("/campaigns/v1/campaigns/{item_id}")
def archive_campaign(item_id:str,user=Depends(require("write"))):
 if not get("campaign_campaigns",item_id):raise HTTPException(404,"Campanha inexistente")
 update("campaign_campaigns",item_id,{"archived":1,"status":"archived","updated_at":now()});audit("campaign.archived","campaign",item_id,actor=user["actor"],role=user["role"]);return {"archived":True}
@app.get("/campaigns/v1/materials",dependencies=[Depends(require("read"))])
def materials(limit:int=50,offset:int=0):return page("campaign_materials",limit,offset)
@app.post("/campaigns/v1/materials/upload",status_code=201)
async def upload_material(request:Request,file:UploadFile=File(...),campaign_id:str=Form(...),authorized:bool=Form(...),authorization_source:str=Form(...),rights_notes:str=Form(""),expires_at:str|None=Form(None),user=Depends(require("upload"))):
 rate_limit(request,"upload",10,60);campaign=get("campaign_campaigns",campaign_id)
 if not campaign:raise HTTPException(404,"Campanha inexistente")
 if not authorized or not authorization_source.strip():raise HTTPException(422,"Confirme e descreva a autorização")
 try:stored=await validate_upload(file)
 except ValueError as exc:audit("material.rejected","material",payload={"reason":str(exc)},result="blocked",actor=user["actor"],role=user["role"]);raise HTTPException(422,str(exc))
 if rows("campaign_materials",1,0,"campaign_id=? AND sha256=?",(campaign_id,stored["sha256"])):stored["path"].unlink(missing_ok=True);raise HTTPException(409,"Material duplicado")
 item=insert("campaign_materials",{"campaign_id":campaign_id,"name":Path(file.filename or "video").name[:160],"stored_name":stored["stored_name"],"local_path":str(stored["path"]),"sha256":stored["sha256"],"declared_mime":stored["declared_mime"],"detected_mime":stored["detected_mime"],"size_bytes":stored["size"],"authorized":1,"authorization_source":authorization_source.strip(),"rights_notes":rights_notes,"expires_at":expires_at,"status":"validated","metadata":json.dumps(stored["metadata"]),"created_at":now()});audit("material.uploaded","material",item["id"],{"sha256":item["sha256"],"size":item["size_bytes"]},actor=user["actor"],role=user["role"]);return item
@app.get("/campaigns/v1/materials/{item_id}/content")
def material_content(item_id:str,user=Depends(require("read"))):
 item=get("campaign_materials",item_id)
 if not item:raise HTTPException(404,"Material inexistente")
 path=Path(item["local_path"])
 if not path.is_file() or path.parent!=accepted_root():raise HTTPException(404,"Arquivo indisponível")
 return FileResponse(path,media_type=item["detected_mime"],filename=item["name"])
@app.post("/campaigns/v1/jobs/detect",status_code=201)
def detect_job(request:Request,value:JobIn,user=Depends(require("jobs"))):
 rate_limit(request,"jobs",20,60);material=get("campaign_materials",value.material_id)
 if not material or material["status"]!="validated":raise HTTPException(422,"Material não validado")
 item=enqueue("detect",value.material_id,value.model_dump(exclude={"material_id","idempotency_key"}),value.idempotency_key);audit("job.queued","job",item["id"],actor=user["actor"],role=user["role"]);return item
@app.post("/campaigns/v1/jobs/render/{candidate_id}",status_code=201)
def render_job(candidate_id:str,value:RenderIn,user=Depends(require("jobs"))):
 candidate=get("campaign_candidates",candidate_id)
 if not candidate:raise HTTPException(404,"Candidato inexistente")
 return enqueue("render",candidate_id,{},value.idempotency_key)
@app.get("/campaigns/v1/jobs",dependencies=[Depends(require("read"))])
def jobs(limit:int=50,offset:int=0):return page("campaign_jobs",limit,offset)
@app.post("/campaigns/v1/jobs/{job_id}/cancel")
def cancel_job(job_id:str,user=Depends(require("jobs"))):
 if not cancel(job_id):raise HTTPException(409,"Job não pode ser cancelado")
 audit("job.cancelled","job",job_id,actor=user["actor"],role=user["role"]);return {"cancelled":True}
@app.get("/campaigns/v1/candidates",dependencies=[Depends(require("read"))])
def candidates(limit:int=50,offset:int=0):return page("campaign_candidates",limit,offset)
@app.get("/campaigns/v1/candidates/{candidate_id}/checks",dependencies=[Depends(require("read"))])
def checks(candidate_id:str):
 if not get("campaign_candidates",candidate_id):raise HTTPException(404,"Candidato inexistente")
 return {"items":rows("campaign_rule_checks",200,0,"candidate_id=?",(candidate_id,))}
@app.post("/campaigns/v1/candidates/{candidate_id}/review")
def review(candidate_id:str,value:ReviewIn,user=Depends(require("review"))):
 candidate=get("campaign_candidates",candidate_id)
 if not candidate:raise HTTPException(404,"Candidato inexistente")
 status={"approve":"approved","reject":"rejected","redo":"redo"}.get(value.action)
 if not status:raise HTTPException(422,"Ação inválida")
 data={"status":status,"updated_at":now()};data.update({k:v for k,v in {"caption":value.caption,"hook":value.hook}.items() if v is not None});result=update("campaign_candidates",candidate_id,data);audit(f"candidate.{status}","candidate",candidate_id,{"notes":value.notes},actor=user["actor"],role=user["role"]);return result
@app.get("/campaigns/v1/channels",dependencies=[Depends(require("read"))])
def channels(limit:int=50,offset:int=0):return page("campaign_channels",limit,offset)
@app.post("/campaigns/v1/channels",status_code=201)
def create_channel(value:ChannelIn,user=Depends(require("write"))):
 data=value.model_dump();data["permissions"]=json.dumps(data["permissions"]);data.update(id=uid(),archived=0,created_at=now());insert("campaign_channels",data);audit("channel.created","channel",data["id"],actor=user["actor"],role=user["role"]);return data
@app.put("/campaigns/v1/channels/{item_id}")
def edit_channel(item_id:str,value:ChannelIn,user=Depends(require("write"))):
 data=value.model_dump();data["permissions"]=json.dumps(data["permissions"])
 try:result=update("campaign_channels",item_id,data)
 except KeyError:raise HTTPException(404,"Canal inexistente")
 audit("channel.updated","channel",item_id,actor=user["actor"],role=user["role"]);return result
@app.delete("/campaigns/v1/channels/{item_id}")
def archive_channel(item_id:str,user=Depends(require("write"))):
 try:update("campaign_channels",item_id,{"archived":1})
 except KeyError:raise HTTPException(404,"Canal inexistente")
 audit("channel.archived","channel",item_id,actor=user["actor"],role=user["role"]);return {"archived":True}
@app.get("/campaigns/v1/publications",dependencies=[Depends(require("read"))])
def publications(limit:int=50,offset:int=0):return page("campaign_publications",limit,offset)
@app.post("/campaigns/v1/publications",status_code=201)
def create_publication(value:PublicationIn,user=Depends(require("export"))):
 candidate=get("campaign_candidates",value.candidate_id)
 if not candidate or candidate["status"]!="approved" or candidate["checklist_status"]=="blocked":raise HTTPException(422,"Candidato não aprovado ou bloqueado pelas regras")
 stamp=now();data=value.model_dump();data["hashtags"]=json.dumps(data["hashtags"]);data.update(id=uid(),mode="manual-export",status="ready_for_manual_publication",package_path="",published_url="",attempts=0,error="",created_at=stamp,updated_at=stamp);insert("campaign_publications",data);audit("publication.prepared","publication",data["id"],actor=user["actor"],role=user["role"]);return data
@app.put("/campaigns/v1/publications/{item_id}/published")
def confirm_published(item_id:str,value:PublishedIn,user=Depends(require("export"))):
 try:result=update("campaign_publications",item_id,{"published_url":value.published_url,"status":value.status,"updated_at":now()})
 except KeyError:raise HTTPException(404,"Publicação inexistente")
 audit("publication.confirmed_manual","publication",item_id,{"url":value.published_url},actor=user["actor"],role=user["role"]);return result
@app.post("/campaigns/v1/publications/{item_id}/export")
def export_package(request:Request,item_id:str,user=Depends(require("export"))):
 rate_limit(request,"export",10,60);publication=get("campaign_publications",item_id);candidate=get("campaign_candidates",publication["candidate_id"]) if publication else None
 if not publication or not candidate or not Path(candidate["output_path"]).is_file():raise HTTPException(422,"Arquivo final indisponível")
 folder=ROOT/"data"/"exports";folder.mkdir(parents=True,exist_ok=True);package=folder/f"{item_id}.zip"
 with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as archive:
  archive.write(candidate["output_path"],"video.mp4");archive.writestr("post.txt",publication["description"]+"\n"+" ".join(json.loads(publication["hashtags"])));archive.writestr("manifest.json",json.dumps({"publication_id":item_id,"campaign_id":publication["campaign_id"],"status":"ready_for_manual_publication"},ensure_ascii=False))
 token=secrets.token_urlsafe(32);expires=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat();insert("campaign_export_tokens",{"publication_id":item_id,"token_hash":token_hash(token),"expires_at":expires,"revoked":0,"created_at":now()});update("campaign_publications",item_id,{"package_path":str(package),"updated_at":now()});audit("publication.exported","publication",item_id,actor=user["actor"],role=user["role"]);return {"status":"ready_for_manual_publication","download_url":f"/campaigns/v1/mobile/{token}","expires_at":expires}
@app.get("/campaigns/v1/mobile/{token}")
def mobile_download(token:str):
 with connect() as db:row=db.execute("SELECT e.*,p.package_path FROM campaign_export_tokens e JOIN campaign_publications p ON p.id=e.publication_id WHERE e.token_hash=?",(token_hash(token),)).fetchone()
 if not row or row["revoked"] or row["expires_at"]<now():raise HTTPException(404,"Link expirado ou revogado")
 return FileResponse(row["package_path"],media_type="application/zip",filename="botlive-publicacao.zip")
@app.get("/campaigns/v1/results",dependencies=[Depends(require("read"))])
def results(limit:int=50,offset:int=0):return page("campaign_results",limit,offset)
@app.post("/campaigns/v1/results",status_code=201)
def create_result(value:ResultIn,user=Depends(require("write"))):
 if value.confirmed_revenue and value.payment_status not in {"approved","received","disputed"}:raise HTTPException(422,"Receita confirmada exige status financeiro compatível")
 data=value.model_dump();data.update(id=uid(),updated_at=now());insert("campaign_results",data);audit("result.created","result",data["id"],{"financial":True},actor=user["actor"],role=user["role"]);return data
@app.put("/campaigns/v1/results/{item_id}")
def edit_result(item_id:str,value:ResultIn,user=Depends(require("write"))):
 if value.confirmed_revenue and value.payment_status not in {"approved","received","disputed"}:raise HTTPException(422,"Receita confirmada exige status financeiro compatível")
 data=value.model_dump();data["updated_at"]=now()
 try:result=update("campaign_results",item_id,data)
 except KeyError:raise HTTPException(404,"Resultado inexistente")
 audit("result.updated","result",item_id,{"financial":True},actor=user["actor"],role=user["role"]);return result
@app.get("/campaigns/v1/results.csv",response_class=PlainTextResponse)
def results_csv(user=Depends(require("read"))):
 items=rows("campaign_results",200,0);header="campaign_id,reported_views,validated_views,estimated_revenue,confirmed_revenue,payment_status\n";return header+"".join(f"{x['campaign_id']},{x['reported_views']},{x['validated_views']},{x['estimated_revenue']},{x['confirmed_revenue']},{x['payment_status']}\n" for x in items)
@app.get("/campaigns/v1/audit",dependencies=[Depends(require("read"))])
def audit_log(limit:int=50,offset:int=0):return page("campaign_audit",limit,offset)
@app.get("/campaigns/v1/settings",dependencies=[Depends(require("read"))])
def settings():return {x["key"]:json.loads(x["value"]) for x in rows("campaign_settings",200,0)}
@app.put("/campaigns/v1/settings/{key}")
def save_setting(key:str,value:SettingIn,user=Depends(require("write"))):
 if key not in {"limits","review","safe_areas","module"}:raise HTTPException(422,"Configuração desconhecida")
 with connect() as db:db.execute("INSERT INTO campaign_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,json.dumps(value.value),now()))
 audit("setting.updated","setting",key,actor=user["actor"],role=user["role"]);return {"key":key,"value":value.value}
@app.get("/campaigns/v1/candidates/{item_id}/content")
def candidate_content(item_id:str,user=Depends(require("read"))):
 item=get("campaign_candidates",item_id)
 if not item or not item["output_path"] or not Path(item["output_path"]).is_file():raise HTTPException(404,"Corte indisponível")
 return FileResponse(item["output_path"],media_type="video/mp4",filename=f"corte-{item_id}.mp4")
@app.post("/campaigns/v1/module/pause")
def pause(user=Depends(require("write"))):audit("module.pause_requested","module",payload={"legacy_affected":False},actor=user["actor"],role=user["role"]);return {"campaign_automation_paused":True,"legacy_affected":False,"instruction":"Defina CAMPAIGNS_PAUSED=true apenas no agente de campanhas"}
