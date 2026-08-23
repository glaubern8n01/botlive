import importlib.util,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"local-agent"))
from app import store
class MigrationTests(unittest.TestCase):
 def test_upgrade_and_rollback_only_campaign_database(self):
  root=Path(__file__).resolve().parents[1];db=Path(tempfile.mkdtemp())/"migration.db";os.environ["CAMPAIGNS_DATABASE_PATH"]=str(db);sys.path.insert(0,str(root/"local-agent"));
  for name in [x for x in list(sys.modules) if x=="app.store"]:del sys.modules[name]
  spec=importlib.util.spec_from_file_location("campaign_migration",root/"migrations"/"manage.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.upgrade()
  with sqlite3.connect(db) as conn:self.assertIn("campaign_jobs",{x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
  module.downgrade(True)
  with sqlite3.connect(db) as conn:self.assertFalse(any(x[0].startswith("campaign_") for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")))
class TestColunaNova(unittest.TestCase):
    def test_banco_antigo_ganha_a_coluna_desde(self):
        """CREATE TABLE IF NOT EXISTS nao mexe em tabela existente: sem o ALTER,
        o banco de producao ficava sem `desde` e todo cadastro de fonte dava
        500."""
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "antigo.db"
            with mock.patch.object(store, "DB_PATH", caminho):
                antigo = store.SCHEMA.replace(
                    "notes TEXT DEFAULT '',desde TEXT DEFAULT ''", "notes TEXT DEFAULT ''")
                with store.connect() as db:
                    db.executescript(antigo)
                    self.assertNotIn("desde", {x["name"] for x in
                                               db.execute("PRAGMA table_info(campaign_sources)")})
                store.migrate()
                with store.connect() as db:
                    self.assertIn("desde", {x["name"] for x in
                                            db.execute("PRAGMA table_info(campaign_sources)")})
                store.migrate()  # idempotente


if __name__ == "__main__":
    unittest.main()
