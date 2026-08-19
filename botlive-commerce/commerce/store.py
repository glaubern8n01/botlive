"""Persistencia do Commerce Studio.

Banco proprio (commerce.db). Nao encosta em shop-live.db: o Live Pilot e uma
operacao separada e continua dono do proprio estado. A integracao entre os
dois e por pacote de assets, nunca por tabela compartilhada.
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
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("COMMERCE_DATABASE_PATH", RAIZ / "data" / "commerce.db")).resolve()

TABELAS = {
    "commerce_products",
    "commerce_evidence",
    "commerce_claims",
    "commerce_creatives",
    "commerce_assets",
    "commerce_packages",
    "commerce_audit",
}

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS commerce_products(
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    brand TEXT DEFAULT '',
    affiliate_url TEXT DEFAULT '',
    price REAL DEFAULT 0,
    currency TEXT DEFAULT 'BRL',
    features TEXT DEFAULT '[]',
    target_audience TEXT DEFAULT '',
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commerce_evidence(
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES commerce_products(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    source_label TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    reliability TEXT NOT NULL DEFAULT 'baixa',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commerce_claims(
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES commerce_products(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'proposed',
    evidence_ids TEXT DEFAULT '[]',
    blocked_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, text)
);

CREATE TABLE IF NOT EXISTS commerce_creatives(
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES commerce_products(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    objective TEXT DEFAULT '',
    hook TEXT DEFAULT '',
    script TEXT DEFAULT '',
    cta TEXT DEFAULT '',
    claim_ids TEXT DEFAULT '[]',
    asset_ids TEXT DEFAULT '[]',
    provider TEXT DEFAULT '',
    seed TEXT DEFAULT '',
    config TEXT DEFAULT '{}',
    output_path TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    qa TEXT DEFAULT '{}',
    publish_job_ids TEXT DEFAULT '[]',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commerce_assets(
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES commerce_products(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    rights TEXT NOT NULL DEFAULT '',
    source TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commerce_packages(
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES commerce_products(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    checksum TEXT NOT NULL,
    exported_to TEXT DEFAULT 'live-pilot',
    created_at TEXT NOT NULL,
    UNIQUE(product_id, version)
);

CREATE TABLE IF NOT EXISTS commerce_audit(
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

CREATE INDEX IF NOT EXISTS idx_commerce_evidence_product ON commerce_evidence(product_id);
CREATE INDEX IF NOT EXISTS idx_commerce_claims_product ON commerce_claims(product_id, state);
CREATE INDEX IF NOT EXISTS idx_commerce_creatives_product ON commerce_creatives(product_id, status);

PRAGMA user_version=1;
"""


class CommerceError(RuntimeError):
    """Erro de regra comercial com mensagem legivel para a API."""


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
        "commerce_audit",
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
