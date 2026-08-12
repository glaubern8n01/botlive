from __future__ import annotations
import json,os
from datetime import datetime,timedelta,timezone
from .store import connect,now,uid
def enqueue(kind,entity_id,payload,key,max_attempts=3):
 stamp=now()
 with connect() as db:
  existing=db.execute("SELECT * FROM campaign_jobs WHERE idempotency_key=?",(key,)).fetchone()
  if existing:return dict(existing)
  item={"id":uid(),"kind":kind,"entity_id":entity_id,"payload":json.dumps(payload),"status":"queued","attempts":0,"max_attempts":max_attempts,"idempotency_key":key,"created_at":stamp,"updated_at":stamp}
  db.execute("INSERT INTO campaign_jobs(id,kind,entity_id,payload,status,attempts,max_attempts,idempotency_key,created_at,updated_at) VALUES(:id,:kind,:entity_id,:payload,:status,:attempts,:max_attempts,:idempotency_key,:created_at,:updated_at)",item);return item
def claim(worker_id):
 with connect() as db:
  db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT * FROM campaign_jobs WHERE status IN ('queued','retry_wait') AND (run_after IS NULL OR run_after<=?) ORDER BY created_at LIMIT 1",(now(),)).fetchone()
  if not row:return None
  stamp=now();updated=db.execute("UPDATE campaign_jobs SET status='claimed',worker_id=?,claimed_at=?,heartbeat_at=?,attempts=attempts+1,updated_at=? WHERE id=? AND status IN ('queued','retry_wait')",(worker_id,stamp,stamp,stamp,row["id"]))
  return dict(db.execute("SELECT * FROM campaign_jobs WHERE id=?",(row["id"],)).fetchone()) if updated.rowcount else None
def transition(job_id,status,**fields):
 allowed={"queued","claimed","running","completed","failed","cancelled","retry_wait"}
 if status not in allowed:raise ValueError("Estado inválido")
 fields={"status":status,"updated_at":now(),**fields};sets=",".join(f"{k}=?" for k in fields)
 with connect() as db:db.execute(f"UPDATE campaign_jobs SET {sets} WHERE id=?",(*fields.values(),job_id))
def heartbeat(job_id,worker_id,progress):
 with connect() as db:db.execute("UPDATE campaign_jobs SET heartbeat_at=?,progress=?,updated_at=? WHERE id=? AND worker_id=? AND status='running'",(now(),max(0,min(progress,1)),now(),job_id,worker_id))
def recover_orphans():
 cutoff=(datetime.now(timezone.utc)-timedelta(seconds=int(os.getenv("CAMPAIGNS_ORPHAN_SECONDS","120")))).isoformat();count=0
 with connect() as db:
  for row in db.execute("SELECT id,attempts,max_attempts FROM campaign_jobs WHERE status IN ('claimed','running') AND COALESCE(heartbeat_at,claimed_at)<?",(cutoff,)).fetchall():
   status="retry_wait" if row["attempts"]<row["max_attempts"] else "failed";delay=min(300,2**row["attempts"]);run_after=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat();db.execute("UPDATE campaign_jobs SET status=?,run_after=?,error='worker_orphaned',worker_id=NULL,updated_at=? WHERE id=?",(status,run_after,now(),row["id"]));count+=1
 return count
def cancel(job_id):
 with connect() as db:
  result=db.execute("UPDATE campaign_jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','retry_wait','claimed')",(now(),job_id));return bool(result.rowcount)
