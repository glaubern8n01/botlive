from __future__ import annotations
import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
REPO_ROOT=Path(__file__).resolve().parents[3]
DB_PATH=Path(os.getenv("CAMPAIGNS_DATABASE_PATH",ROOT/"data"/"campaigns.db")).resolve()
TABLES={"campaign_campaigns","campaign_sources","campaign_materials","campaign_candidates","campaign_channels","campaign_publications","campaign_results","campaign_metrics","campaign_jobs","campaign_rule_checks","campaign_audit","campaign_settings","campaign_export_tokens"}
SCHEMA="""
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS campaign_campaigns(id TEXT PRIMARY KEY,platform TEXT NOT NULL,name TEXT NOT NULL,url TEXT DEFAULT '',niche TEXT DEFAULT '',status TEXT DEFAULT 'draft',starts_at TEXT,ends_at TEXT,reward_model TEXT DEFAULT '',reward_value REAL DEFAULT 0,budget REAL DEFAULT 0,networks TEXT DEFAULT '[]',rules TEXT DEFAULT '{}',hashtags TEXT DEFAULT '[]',mentions TEXT DEFAULT '[]',min_duration INTEGER,max_duration INTEGER,target_profile TEXT DEFAULT '',duplicate_policy TEXT DEFAULT 'deny',automation_policy TEXT DEFAULT 'manual-only',archived INTEGER DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_materials(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id) ON DELETE RESTRICT,name TEXT NOT NULL,source_url TEXT DEFAULT '',stored_name TEXT DEFAULT '',local_path TEXT DEFAULT '',sha256 TEXT DEFAULT '',declared_mime TEXT DEFAULT '',detected_mime TEXT DEFAULT '',size_bytes INTEGER DEFAULT 0,authorized INTEGER DEFAULT 0,authorization_source TEXT DEFAULT '',rights_notes TEXT DEFAULT '',expires_at TEXT,status TEXT DEFAULT 'registered',metadata TEXT DEFAULT '{}',created_at TEXT NOT NULL,UNIQUE(campaign_id,sha256));
CREATE TABLE IF NOT EXISTS campaign_candidates(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id) ON DELETE RESTRICT,material_id TEXT REFERENCES campaign_materials(id) ON DELETE RESTRICT,source_start REAL DEFAULT 0,source_end REAL DEFAULT 0,score REAL DEFAULT 0,algorithm_version TEXT DEFAULT '',parameters TEXT DEFAULT '{}',version INTEGER DEFAULT 1,output_path TEXT DEFAULT '',output_sha256 TEXT DEFAULT '',caption TEXT DEFAULT '',hook TEXT DEFAULT '',layout TEXT DEFAULT 'vertical-fit',status TEXT DEFAULT 'queued',checklist_status TEXT DEFAULT 'pending',idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_rule_checks(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL REFERENCES campaign_candidates(id) ON DELETE CASCADE,rule_key TEXT NOT NULL,status TEXT NOT NULL,severity TEXT NOT NULL,reason TEXT DEFAULT '',evidence TEXT DEFAULT '{}',checked_at TEXT NOT NULL,UNIQUE(candidate_id,rule_key));
CREATE TABLE IF NOT EXISTS campaign_sources(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id) ON DELETE CASCADE,network TEXT NOT NULL,url TEXT NOT NULL,influencer TEXT DEFAULT '',authorization_source TEXT NOT NULL,notes TEXT DEFAULT '',enabled INTEGER DEFAULT 1,last_checked_at TEXT,last_error TEXT DEFAULT '',created_at TEXT NOT NULL,UNIQUE(campaign_id,url));
CREATE TABLE IF NOT EXISTS campaign_channels(id TEXT PRIMARY KEY,network TEXT NOT NULL,handle TEXT NOT NULL,niche TEXT DEFAULT '',auth_state TEXT DEFAULT 'manual',permissions TEXT DEFAULT '[]',daily_limit INTEGER DEFAULT 0,token_hint TEXT DEFAULT '',archived INTEGER DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(network,handle));
CREATE TABLE IF NOT EXISTS campaign_publications(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id) ON DELETE RESTRICT,candidate_id TEXT NOT NULL REFERENCES campaign_candidates(id) ON DELETE RESTRICT,channel_id TEXT REFERENCES campaign_channels(id) ON DELETE RESTRICT,mode TEXT DEFAULT 'manual-export',status TEXT DEFAULT 'draft',description TEXT DEFAULT '',hashtags TEXT DEFAULT '[]',package_path TEXT DEFAULT '',published_url TEXT DEFAULT '',attempts INTEGER DEFAULT 0,error TEXT DEFAULT '',idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_results(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id) ON DELETE RESTRICT,publication_id TEXT REFERENCES campaign_publications(id) ON DELETE RESTRICT,reported_views INTEGER DEFAULT 0,validated_views INTEGER DEFAULT 0,ranking INTEGER,estimated_revenue REAL DEFAULT 0,confirmed_revenue REAL DEFAULT 0,processing_cost REAL DEFAULT 0,payment_status TEXT DEFAULT 'pending',notes TEXT DEFAULT '',updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_metrics(id TEXT PRIMARY KEY,publication_id TEXT NOT NULL REFERENCES campaign_publications(id) ON DELETE CASCADE,reported_views INTEGER DEFAULT 0,validated_views INTEGER DEFAULT 0,source TEXT DEFAULT 'manual',recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,entity_id TEXT NOT NULL,payload TEXT DEFAULT '{}',status TEXT DEFAULT 'queued',progress REAL DEFAULT 0,attempts INTEGER DEFAULT 0,max_attempts INTEGER DEFAULT 3,idempotency_key TEXT NOT NULL UNIQUE,worker_id TEXT,claimed_at TEXT,heartbeat_at TEXT,run_after TEXT,timeout_seconds INTEGER DEFAULT 1800,error TEXT DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'operator',action TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT,result TEXT NOT NULL,payload TEXT DEFAULT '{}',correlation_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_export_tokens(id TEXT PRIMARY KEY,publication_id TEXT NOT NULL REFERENCES campaign_publications(id) ON DELETE CASCADE,token_hash TEXT NOT NULL UNIQUE,expires_at TEXT NOT NULL,revoked INTEGER DEFAULT 0,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_campaign_sources_checar ON campaign_sources(enabled,last_checked_at);
CREATE INDEX IF NOT EXISTS idx_campaign_jobs_claim ON campaign_jobs(status,run_after,created_at);
CREATE INDEX IF NOT EXISTS idx_campaign_materials_campaign ON campaign_materials(campaign_id,status);
CREATE INDEX IF NOT EXISTS idx_campaign_candidates_campaign ON campaign_candidates(campaign_id,status);
PRAGMA user_version=3;
"""
def now():return datetime.now(timezone.utc).isoformat()
def uid():return str(uuid4())
@contextmanager
def connect():
 DB_PATH.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(DB_PATH,timeout=30);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA journal_mode=WAL")
 try:yield db;db.commit()
 except Exception:db.rollback();raise
 finally:db.close()
def migrate():
 with connect() as db:db.executescript(SCHEMA)
def rows(table,limit=100,offset=0,where="",params=()):
 if table not in TABLES:raise ValueError("Tabela inválida")
 sql=f"SELECT * FROM {table}"+(f" WHERE {where}" if where else "")+" ORDER BY rowid DESC LIMIT ? OFFSET ?"
 with connect() as db:return [dict(x) for x in db.execute(sql,(*params,min(limit,200),max(offset,0)))]
def get(table,item_id):
 if table not in TABLES:raise ValueError("Tabela inválida")
 with connect() as db:
  row=db.execute(f"SELECT * FROM {table} WHERE id=?",(item_id,)).fetchone();return dict(row) if row else None
def insert(table,payload):
 if table not in TABLES:raise ValueError("Tabela inválida")
 values={**payload};values.setdefault("id",uid());cols=",".join(values);marks=",".join("?" for _ in values)
 with connect() as db:db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",tuple(values.values()))
 return values
def update(table,item_id,payload):
 if table not in TABLES or not payload:raise ValueError("Atualização inválida")
 setters=",".join(f"{key}=?" for key in payload)
 with connect() as db:
  result=db.execute(f"UPDATE {table} SET {setters} WHERE id=?",(*payload.values(),item_id))
  if not result.rowcount:raise KeyError(item_id)
 return get(table,item_id)
def audit(action,entity_type,entity_id=None,payload=None,result="ok",actor="operator",role="operator"):
 return insert("campaign_audit",{"actor":actor,"role":role,"action":action,"entity_type":entity_type,"entity_id":entity_id,"result":result,"payload":json.dumps(payload or {},ensure_ascii=False),"correlation_id":uid(),"created_at":now()})
