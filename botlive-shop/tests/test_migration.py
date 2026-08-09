import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from sqlalchemy import create_engine, inspect

class MigrationTests(unittest.TestCase):
    def test_upgrade_creates_only_shop_live_tables(self):
        root = Path(__file__).parents[1] / "apps" / "local-agent"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            data = Path(temp) / "data"
            env = {**os.environ, "SHOP_LIVE_TESTING":"true", "SHOP_LIVE_TEST_DATA_ROOT":str(data)}
            previous = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "20260808_0004"], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(previous.returncode, 0, previous.stderr)
            result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            database=data/"shop-live.db";engine = create_engine(f"sqlite:///{database.as_posix()}")
            tables = set(inspect(engine).get_table_names())
            engine.dispose()
            self.assertEqual(tables, {"alembic_version", "shop_live_products", "shop_live_sessions", "shop_live_session_products", "shop_live_audit_events", "shop_live_media_assets", "shop_live_script_blocks", "shop_live_session_materials", "shop_live_media_playback", "shop_live_session_runtime", "shop_live_local_settings"})
