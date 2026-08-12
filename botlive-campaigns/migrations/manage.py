from __future__ import annotations
import argparse,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"local-agent"))
from app.store import DB_PATH,SCHEMA,connect
TABLES=["campaign_export_tokens","campaign_metrics","campaign_rule_checks","campaign_jobs","campaign_results","campaign_publications","campaign_channels","campaign_candidates","campaign_materials","campaign_settings","campaign_audit","campaign_campaigns"]
def upgrade():
 with connect() as db:db.executescript(SCHEMA)
def downgrade(confirm=False):
 if not confirm:raise SystemExit("Rollback destrutivo exige --confirm e deve ser usado somente no banco isolado")
 with connect() as db:
  for table in TABLES:db.execute(f"DROP TABLE IF EXISTS {table}")
  db.execute("PRAGMA user_version=0")
def main():
 parser=argparse.ArgumentParser();parser.add_argument("action",choices=["upgrade","downgrade"]);parser.add_argument("--confirm",action="store_true");args=parser.parse_args();upgrade() if args.action=="upgrade" else downgrade(args.confirm)
if __name__=="__main__":main()
