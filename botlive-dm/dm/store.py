"""Persistencia do respondedor de comentarios (o "ManyChat proprio").

Banco isolado (dm.db). O ponto central do schema e a tabela dm_respostas com
comment_id UNIQUE: o Instagram permite UMA private reply por comentario, e a
trava fica no banco para que retry, webhook duplicado ou reprocessamento
nunca virem duas mensagens para a mesma pessoa.
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
DB_PATH = Path(os.getenv("DM_DATABASE_PATH", RAIZ / "data" / "dm.db")).resolve()

TABELAS = {"dm_regras", "dm_comentarios", "dm_respostas", "dm_audit"}

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS dm_regras(
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    conta TEXT NOT NULL,
    palavras TEXT NOT NULL DEFAULT '[]',
    resposta TEXT NOT NULL,
    link TEXT DEFAULT '',
    media_id TEXT DEFAULT '',
    ativa INTEGER NOT NULL DEFAULT 0,
    prioridade INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(conta, nome)
);

CREATE TABLE IF NOT EXISTS dm_comentarios(
    id TEXT PRIMARY KEY,
    comment_id TEXT NOT NULL UNIQUE,
    media_id TEXT DEFAULT '',
    conta TEXT NOT NULL,
    autor TEXT DEFAULT '',
    texto TEXT NOT NULL DEFAULT '',
    recebido_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dm_respostas(
    id TEXT PRIMARY KEY,
    comment_id TEXT NOT NULL UNIQUE,
    regra_id TEXT REFERENCES dm_regras(id) ON DELETE SET NULL,
    conta TEXT NOT NULL,
    texto TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    erro TEXT DEFAULT '',
    dry_run INTEGER NOT NULL DEFAULT 1,
    enviado_em TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dm_audit(
    id TEXT PRIMARY KEY,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id TEXT,
    resultado TEXT NOT NULL DEFAULT 'ok',
    detalhe TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dm_respostas_conta ON dm_respostas(conta, status, enviado_em);
CREATE INDEX IF NOT EXISTS idx_dm_regras_conta ON dm_regras(conta, ativa, prioridade);

PRAGMA user_version=1;
"""


class DmError(RuntimeError):
    """Erro do modulo de DM, com mensagem legivel."""


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


def listar(tabela: str, limite: int = 100, where: str = "", params=()):
    _validar(tabela)
    sql = f"SELECT * FROM {tabela}" + (f" WHERE {where}" if where else "")
    sql += " ORDER BY rowid DESC LIMIT ?"
    with conectar() as db:
        return [dict(x) for x in db.execute(sql, (*params, min(limite, 500)))]


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
    setters = ",".join(f"{c}=?" for c in payload)
    with conectar() as db:
        resultado = db.execute(
            f"UPDATE {tabela} SET {setters} WHERE id=?", (*payload.values(), item_id)
        )
        if not resultado.rowcount:
            raise KeyError(item_id)
    return obter(tabela, item_id)


def auditar(acao, entidade, entidade_id=None, detalhe=None, resultado="ok"):
    return inserir("dm_audit", {
        "acao": acao,
        "entidade": entidade,
        "entidade_id": entidade_id,
        "resultado": resultado,
        "detalhe": json.dumps(detalhe or {}, ensure_ascii=False),
        "created_at": agora(),
    })
