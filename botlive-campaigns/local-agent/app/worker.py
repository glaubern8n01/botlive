from __future__ import annotations
import json,os,socket,time,traceback
from datetime import datetime,timedelta,timezone
from pathlib import Path
from . import engine
from .queue import claim,heartbeat,recover_orphans,transition
from .rules import evaluate,summary
from .store import ROOT,audit,connect,get,insert,now,uid,update

def process(job,worker_id):
 payload=json.loads(job["payload"]);transition(job["id"],"running",heartbeat_at=now());heartbeat(job["id"],worker_id,.05)
 if job["kind"]=="detect":
  material=get("campaign_materials",job["entity_id"]);campaign=get("campaign_campaigns",material["campaign_id"]);items=engine.detect(material["local_path"],payload.get("max_candidates",8),payload.get("min_gap_seconds",45),payload.get("min_score",0));duration=payload.get("clip_duration",45)
  for index,item in enumerate(items):
   start=max(0,item["timestamp"]-duration/2);end=start+duration;key=f"{material['id']}:{round(start,2)}:{duration}:{payload.get('layout','vertical-fit')}"
   candidate=insert("campaign_candidates",{"campaign_id":campaign["id"],"material_id":material["id"],"source_start":start,"source_end":end,"score":item["score"],"algorithm_version":engine.ALGORITHM_VERSION,"parameters":json.dumps(payload),"version":1,"caption":" ".join(json.loads(campaign["hashtags"]) + json.loads(campaign["mentions"])),"hook":"","layout":payload.get("layout","vertical-fit"),"status":"detected","checklist_status":"pending","idempotency_key":key,"created_at":now(),"updated_at":now()});heartbeat(job["id"],worker_id,.1+.8*(index+1)/max(len(items),1));audit("candidate.detected","candidate",candidate["id"],item)
  return {"candidates":len(items)}
 if job["kind"]=="render":
  candidate=get("campaign_candidates",job["entity_id"]);material=get("campaign_materials",candidate["material_id"]);campaign=get("campaign_campaigns",candidate["campaign_id"]);out=ROOT/"data"/"outputs"/campaign["id"]/f"{candidate['id']}.mp4";mentions=json.loads(campaign["mentions"]);rules=json.loads(campaign["rules"]);result=engine.render(material["local_path"],out,candidate["source_start"],candidate["source_end"],candidate["layout"],candidate["caption"],candidate["hook"]," ".join(mentions),rules.get("cta", ""));update("campaign_candidates",candidate["id"],{"output_path":result["path"],"output_sha256":result["sha256"],"status":"review","updated_at":now()});candidate=get("campaign_candidates",candidate["id"]);campaign["rules"]=rules;campaign["hashtags"]=json.loads(campaign["hashtags"]);campaign["mentions"]=mentions;checks=evaluate(campaign,candidate,{**result,"authorized":bool(material["authorized"])});state=summary(checks)
  with connect() as db:
   for check in checks:db.execute("INSERT OR REPLACE INTO campaign_rule_checks(id,candidate_id,rule_key,status,severity,reason,evidence,checked_at) VALUES(?,?,?,?,?,?,?,?)",(uid(),candidate["id"],check["rule_key"],check["status"],check["severity"],check["reason"],json.dumps(check["evidence"]),check["checked_at"]))
  update("campaign_candidates",candidate["id"],{"checklist_status":state,"updated_at":now()});return result
 raise ValueError("Tipo de job desconhecido")

def run_once(worker_id=None):
 worker_id=worker_id or f"{socket.gethostname()}-{os.getpid()}";recover_orphans();job=claim(worker_id)
 if not job:return False
 try:result=process(job,worker_id);transition(job["id"],"completed",progress=1,error="");audit("job.completed","job",job["id"],result);return True
 except Exception as exc:
  attempts=int(job["attempts"]);maximum=int(job["max_attempts"]);status="retry_wait" if attempts<maximum else "failed";run_after=(datetime.now(timezone.utc)+timedelta(seconds=min(300,2**attempts))).isoformat();transition(job["id"],status,error=str(exc)[:1000],run_after=run_after,worker_id=None);audit("job.failed","job",job["id"],{"error":str(exc),"retry":status=="retry_wait"},result="failed");return True
def main():
 if os.getenv("CAMPAIGNS_ENABLED","false").lower()!="true":raise SystemExit("Campanhas desativadas")
 while True:
  if os.getenv("CAMPAIGNS_PAUSED","false").lower()=="true" or not run_once():time.sleep(2)
if __name__=="__main__":main()
