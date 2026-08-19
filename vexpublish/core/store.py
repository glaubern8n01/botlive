"""Persistencia do VexPublish.

Banco proprio e isolado (vexpublish.db). Nao aponte VEXPUBLISH_DATABASE_PATH
para campaigns.db nem para o banco do BotLive: os modulos precisam poder ser
migrados e revertidos separadamente.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


RAIZ = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("VEXPUBLISH_DATABASE_PATH", RAIZ / "data" / "vexpublish.db")).resolve()

TABELAS = {
    "vexpublish_channels",
    "vexpublish_accounts",
    "vexpublish_sessions",
    "vexpublish_media_assets",
    "vexpublish_jobs",
    "vexpublish_job_events",
    "vexpublish_settings",
    "vexpublish_metric_snapshots",
}

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS vexpublish_channels(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    niche TEXT DEFAULT '',
    identity TEXT DEFAULT '{}',
    voice TEXT DEFAULT '',
    platforms TEXT DEFAULT '[]',
    calendar TEXT DEFAULT '{}',
    content_rules TEXT DEFAULT '{}',
    preferred_providers TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'paused',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vexpublish_accounts(
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES vexpublish_channels(id) ON DELETE RESTRICT,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    label TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'inactive',
    max_posts_per_day INTEGER NOT NULL DEFAULT 0,
    minimum_interval_minutes INTEGER NOT NULL DEFAULT 0,
    allowed_hours TEXT DEFAULT '[]',
    timezone TEXT DEFAULT 'UTC',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, handle)
);

CREATE TABLE IF NOT EXISTS vexpublish_sessions(
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES vexpublish_accounts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'missing',
    last_checked_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, platform)
);

CREATE TABLE IF NOT EXISTS vexpublish_media_assets(
    id TEXT PRIMARY KEY,
    channel_id TEXT REFERENCES vexpublish_channels(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    sha256 TEXT DEFAULT '',
    mime TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    size_bytes INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    rights TEXT DEFAULT '',
    authorized INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vexpublish_jobs(
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES vexpublish_channels(id) ON DELETE RESTRICT,
    platform TEXT NOT NULL,
    account TEXT NOT NULL REFERENCES vexpublish_accounts(id) ON DELETE RESTRICT,
    media_path TEXT NOT NULL,
    title TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    hashtags TEXT DEFAULT '[]',
    scheduled_at TEXT,
    requires_approval INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    idempotency_key TEXT NOT NULL UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    dry_run INTEGER NOT NULL DEFAULT 1,
    worker_id TEXT,
    locked_at TEXT,
    heartbeat_at TEXT,
    run_after TEXT,
    last_error_code TEXT,
    last_error TEXT DEFAULT '',
    published_url TEXT DEFAULT '',
    posted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vexpublish_job_events(
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES vexpublish_jobs(id) ON DELETE CASCADE,
    from_status TEXT DEFAULT '',
    to_status TEXT DEFAULT '',
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    detail TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vexpublish_metric_snapshots(
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES vexpublish_channels(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES vexpublish_jobs(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    watch_seconds REAL NOT NULL DEFAULT 0,
    retention REAL NOT NULL DEFAULT 0,
    revenue REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'BRL',
    source TEXT NOT NULL DEFAULT 'manual',
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vexpublish_settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vexpublish_jobs_claim ON vexpublish_jobs(status, run_after, created_at);
CREATE INDEX IF NOT EXISTS idx_vexpublish_jobs_account ON vexpublish_jobs(account, status, posted_at);
CREATE INDEX IF NOT EXISTS idx_vexpublish_accounts_channel ON vexpublish_accounts(channel_id, platform);
CREATE INDEX IF NOT EXISTS idx_vexpublish_events_job ON vexpublish_job_events(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_vexpublish_metrics_channel ON vexpublish_metric_snapshots(channel_id, recorded_at);

PRAGMA user_version=2;
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid4())


@contextmanager
def conectar():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
    finally:
        db.close()


def migrar() -> None:
    with conectar() as db:
        db.executescript(SCHEMA)


def _validar_tabela(tabela: str) -> None:
    if tabela not in TABELAS:
        raise ValueError(f"Tabela invalida: {tabela}")


def listar(tabela: str, limite: int = 100, offset: int = 0, where: str = "", params=()):
    _validar_tabela(tabela)
    sql = f"SELECT * FROM {tabela}"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY rowid DESC LIMIT ? OFFSET ?"
    with conectar() as db:
        cursor = db.execute(sql, (*params, min(limite, 500), max(offset, 0)))
        return [dict(linha) for linha in cursor]


def obter(tabela: str, item_id: str):
    _validar_tabela(tabela)
    with conectar() as db:
        linha = db.execute(f"SELECT * FROM {tabela} WHERE id=?", (item_id,)).fetchone()
    return dict(linha) if linha else None


def inserir(tabela: str, payload: dict) -> dict:
    _validar_tabela(tabela)
    valores = {**payload}
    valores.setdefault("id", uid())
    colunas = ",".join(valores)
    marcas = ",".join("?" for _ in valores)
    with conectar() as db:
        db.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcas})", tuple(valores.values()))
    return valores


def atualizar(tabela: str, item_id: str, payload: dict) -> dict:
    _validar_tabela(tabela)
    if not payload:
        raise ValueError("Atualizacao vazia")
    setters = ",".join(f"{chave}=?" for chave in payload)
    with conectar() as db:
        resultado = db.execute(
            f"UPDATE {tabela} SET {setters} WHERE id=?", (*payload.values(), item_id)
        )
        if not resultado.rowcount:
            raise KeyError(item_id)
    return obter(tabela, item_id)


def registrar_evento(job_id: str, action: str, status: str, **campos) -> dict:
    return inserir(
        "vexpublish_job_events",
        {
            "job_id": job_id,
            "from_status": campos.get("from_status", ""),
            "to_status": campos.get("to_status", ""),
            "action": action,
            "status": status,
            "error_code": campos.get("error_code"),
            "detail": json.dumps(campos.get("detail") or {}, ensure_ascii=False),
            "created_at": agora(),
        },
    )
