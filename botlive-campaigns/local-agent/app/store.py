from __future__ import annotations
import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(os.getenv("CAMPAIGNS_DATABASE_PATH", ROOT / "data" / "campaigns.db")).resolve()
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS campaign_campaigns(id TEXT PRIMARY KEY,platform TEXT NOT NULL,name TEXT NOT NULL,url TEXT DEFAULT '',niche TEXT DEFAULT '',status TEXT DEFAULT 'draft',starts_at TEXT,ends_at TEXT,reward_model TEXT DEFAULT '',reward_value REAL DEFAULT 0,budget REAL DEFAULT 0,networks TEXT DEFAULT '[]',rules TEXT DEFAULT '',hashtags TEXT DEFAULT '[]',mentions TEXT DEFAULT '[]',min_duration INTEGER,max_duration INTEGER,target_profile TEXT DEFAULT '',duplicate_policy TEXT DEFAULT 'deny',automation_policy TEXT DEFAULT 'manual-only',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_materials(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id),name TEXT NOT NULL,source_url TEXT DEFAULT '',local_path TEXT DEFAULT '',sha256 TEXT DEFAULT '',mime_type TEXT DEFAULT '',size_bytes INTEGER DEFAULT 0,authorized INTEGER DEFAULT 0,rights_notes TEXT DEFAULT '',expires_at TEXT,status TEXT DEFAULT 'registered',UNIQUE(campaign_id,sha256));
CREATE TABLE IF NOT EXISTS campaign_candidates(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id),material_id TEXT REFERENCES campaign_materials(id),source_start REAL DEFAULT 0,source_end REAL DEFAULT 0,score REAL DEFAULT 0,version INTEGER DEFAULT 1,output_path TEXT DEFAULT '',caption TEXT DEFAULT '',hook TEXT DEFAULT '',status TEXT DEFAULT 'queued',checklist TEXT DEFAULT '{}',idempotency_key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS campaign_channels(id TEXT PRIMARY KEY,network TEXT NOT NULL,handle TEXT NOT NULL,niche TEXT DEFAULT '',auth_state TEXT DEFAULT 'manual',permissions TEXT DEFAULT '[]',daily_limit INTEGER DEFAULT 0,UNIQUE(network,handle));
CREATE TABLE IF NOT EXISTS campaign_publications(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id),candidate_id TEXT NOT NULL REFERENCES campaign_candidates(id),channel_id TEXT REFERENCES campaign_channels(id),mode TEXT DEFAULT 'manual-export',status TEXT DEFAULT 'draft',description TEXT DEFAULT '',hashtags TEXT DEFAULT '[]',published_url TEXT DEFAULT '',attempts INTEGER DEFAULT 0,error TEXT DEFAULT '',idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_results(id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaign_campaigns(id),publication_id TEXT REFERENCES campaign_publications(id),reported_views INTEGER DEFAULT 0,validated_views INTEGER DEFAULT 0,ranking INTEGER,estimated_revenue REAL DEFAULT 0,confirmed_revenue REAL DEFAULT 0,processing_cost REAL DEFAULT 0,payment_status TEXT DEFAULT 'pending',updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,entity_id TEXT NOT NULL,payload TEXT DEFAULT '{}',status TEXT DEFAULT 'queued',attempts INTEGER DEFAULT 0,idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT,result TEXT NOT NULL,payload TEXT DEFAULT '{}',correlation_id TEXT NOT NULL,created_at TEXT NOT NULL);
"""
TABLES={"campaign_campaigns","campaign_materials","campaign_candidates","campaign_channels","campaign_publications","campaign_results","campaign_jobs","campaign_audit"}
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid4())
@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(DB_PATH); db.row_factory=sqlite3.Row; db.execute("PRAGMA foreign_keys=ON")
    try: yield db; db.commit()
    except Exception: db.rollback(); raise
    finally: db.close()
def migrate():
    with connect() as db: db.executescript(SCHEMA)
def rows(table):
    if table not in TABLES: raise ValueError("Tabela inválida")
    with connect() as db: return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid DESC")]
def insert(table,payload):
    if table not in TABLES: raise ValueError("Tabela inválida")
    values={**payload}; values.setdefault("id",uid()); columns=",".join(values); marks=",".join("?" for _ in values)
    with connect() as db: db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})",tuple(values.values()))
    return values
def audit(action,entity_type,entity_id=None,payload=None,result="ok",actor="operator"):
    insert("campaign_audit",{"actor":actor,"action":action,"entity_type":entity_type,"entity_id":entity_id,"result":result,"payload":json.dumps(payload or {},ensure_ascii=False),"correlation_id":uid(),"created_at":now()})
