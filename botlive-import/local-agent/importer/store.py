"""Persistencia do modulo Importar / Adaptar / Publicar.

Banco proprio (import.db), separado de campaigns.db, de vexpublish.db e do
banco do BotLive. A biblioteca guarda proveniencia e autorizacao de cada
arquivo: sem isso o item nao pode ser adaptado nem enfileirado.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


RAIZ = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(os.getenv("IMPORT_DATABASE_PATH", RAIZ / "data" / "import.db")).resolve()

TABELAS = {
    "import_sources",
    "import_items",
    "import_adaptations",
    "import_jobs",
    "import_audit",
}

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS import_sources(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    channel_id TEXT DEFAULT '',
    authorized INTEGER NOT NULL DEFAULT 0,
    authorization_source TEXT NOT NULL DEFAULT '',
    license TEXT NOT NULL DEFAULT '',
    rights_notes TEXT DEFAULT '',
    allow_download INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS import_items(
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES import_sources(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    local_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    mime TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    has_audio INTEGER DEFAULT 0,
    origin_url TEXT DEFAULT '',
    credit TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'library',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(sha256)
);

CREATE TABLE IF NOT EXISTS import_adaptations(
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES import_items(id) ON DELETE RESTRICT,
    channel_id TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '{}',
    output_path TEXT DEFAULT '',
    output_sha256 TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planned',
    validation TEXT DEFAULT '{}',
    publish_job_id TEXT DEFAULT '',
    error TEXT DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_jobs(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    idempotency_key TEXT NOT NULL UNIQUE,
    worker_id TEXT,
    claimed_at TEXT,
    run_after TEXT,
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_audit(
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    result TEXT NOT NULL DEFAULT 'ok',
    payload TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_import_items_source ON import_items(source_id, status);
CREATE INDEX IF NOT EXISTS idx_import_adaptations_item ON import_adaptations(item_id, status);
CREATE INDEX IF NOT EXISTS idx_import_jobs_claim ON import_jobs(status, run_after, created_at);

PRAGMA user_version=1;
"""


class ImportError_(RuntimeError):
    """Erro de importacao com mensagem legivel para a API."""


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


def _validar(tabela: str) -> None:
    if tabela not in TABELAS:
        raise ValueError(f"Tabela invalida: {tabela}")


def listar(tabela: str, limite: int = 100, offset: int = 0, where: str = "", params=()):
    _validar(tabela)
    sql = f"SELECT * FROM {tabela}"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY rowid DESC LIMIT ? OFFSET ?"
    with conectar() as db:
        return [dict(x) for x in db.execute(sql, (*params, min(limite, 500), max(offset, 0)))]


def obter(tabela: str, item_id: str):
    _validar(tabela)
    with conectar() as db:
        linha = db.execute(f"SELECT * FROM {tabela} WHERE id=?", (item_id,)).fetchone()
    return dict(linha) if linha else None


def inserir(tabela: str, payload: dict) -> dict:
    _validar(tabela)
    valores = {**payload}
    valores.setdefault("id", uid())
    colunas = ",".join(valores)
    marcas = ",".join("?" for _ in valores)
    with conectar() as db:
        db.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcas})", tuple(valores.values()))
    return valores


def atualizar(tabela: str, item_id: str, payload: dict) -> dict:
    _validar(tabela)
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


def auditar(action, entity_type, entity_id=None, payload=None, result="ok", actor="operator", role="operator"):
    return inserir(
        "import_audit",
        {
            "actor": actor,
            "role": role,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "result": result,
            "payload": json.dumps(payload or {}, ensure_ascii=False),
            "created_at": agora(),
        },
    )
