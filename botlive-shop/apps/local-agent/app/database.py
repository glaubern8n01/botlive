from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DB = Path(__file__).parents[2] / "data" / "shop-live.db"
DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("SHOP_LIVE_DATABASE_URL", f"sqlite:///{DEFAULT_DB.as_posix()}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
