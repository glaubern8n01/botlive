from __future__ import annotations

import os
from pathlib import Path

SHOP_ROOT = Path(__file__).resolve().parents[3]
_test_root = os.getenv("SHOP_LIVE_TEST_DATA_ROOT") if os.getenv("SHOP_LIVE_TESTING", "false").lower() == "true" else None
DATA_ROOT = Path(_test_root).resolve() if _test_root else (SHOP_ROOT / "data").resolve()
MEDIA_ROOT = (DATA_ROOT / "media").resolve()
BACKUP_ROOT = (DATA_ROOT / "backups").resolve()
RUN_ROOT = (DATA_ROOT / "run").resolve()
DATABASE_PATH = (DATA_ROOT / "shop-live.db").resolve()

def load_local_env() -> None:
    env_file = SHOP_ROOT / ".env.local"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

def ensure_data_layout() -> None:
    for path in (DATA_ROOT, MEDIA_ROOT, BACKUP_ROOT, RUN_ROOT):
        path.mkdir(parents=True, exist_ok=True)

def sqlite_url() -> str:
    return f"sqlite:///{DATABASE_PATH.as_posix()}"

load_local_env()
ensure_data_layout()
