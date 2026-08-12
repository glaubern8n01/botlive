import importlib.util,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
class MigrationTests(unittest.TestCase):
 def test_upgrade_and_rollback_only_campaign_database(self):
  root=Path(__file__).resolve().parents[1];db=Path(tempfile.mkdtemp())/"migration.db";os.environ["CAMPAIGNS_DATABASE_PATH"]=str(db);sys.path.insert(0,str(root/"local-agent"));
  for name in [x for x in list(sys.modules) if x=="app.store"]:del sys.modules[name]
  spec=importlib.util.spec_from_file_location("campaign_migration",root/"migrations"/"manage.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.upgrade()
  with sqlite3.connect(db) as conn:self.assertIn("campaign_jobs",{x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
  module.downgrade(True)
  with sqlite3.connect(db) as conn:self.assertFalse(any(x[0].startswith("campaign_") for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")))
if __name__=="__main__":unittest.main()
