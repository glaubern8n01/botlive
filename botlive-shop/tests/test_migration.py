import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from sqlalchemy import create_engine, inspect

class MigrationTests(unittest.TestCase):
    def test_upgrade_creates_only_shop_live_tables(self):
        root = Path(__file__).parents[1] / "apps" / "local-agent"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            database = Path(temp) / "migration.db"
            env = {**os.environ, "SHOP_LIVE_DATABASE_URL": f"sqlite:///{database.as_posix()}"}
            result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            engine = create_engine(f"sqlite:///{database.as_posix()}")
            tables = set(inspect(engine).get_table_names())
            engine.dispose()
            self.assertEqual(tables, {"alembic_version", "shop_live_products", "shop_live_sessions", "shop_live_session_products", "shop_live_audit_events"})
