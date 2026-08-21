"""Persistencia do Producao em Massa (Content Studio).

Banco proprio (massa.db), isolado dos outros modulos. Com
MASS_CONTENT_STUDIO_ENABLED=false nada aqui e tocado e o BotLive segue
exatamente como hoje.

O conceito central e PROJETO: cada lote de trabalho tem pastas proprias
(downloads, editados, exports) para o operador conseguir retomar depois sem
misturar material de campanhas diferentes.
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
DB_PATH = Path(os.getenv("MASS_DATABASE_PATH", RAIZ / "data" / "massa.db")).resolve()

TABELAS = {
    "mass_projetos",
    "mass_downloads",
    "mass_edicoes",
    "mass_templates",
    "mass_publicacoes",
    "mass_audit",
}

# queued -> downloading/editing/posting -> completed | failed | cancelled
ESTADOS_FILA = ("queued", "running", "completed", "failed", "cancelled", "paused")

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS mass_projetos(
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    pasta TEXT NOT NULL,
    template_id TEXT,
    status TEXT NOT NULL DEFAULT 'aberto',
    notas TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mass_downloads(
    id TEXT PRIMARY KEY,
    projeto_id TEXT NOT NULL REFERENCES mass_projetos(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    plataforma TEXT NOT NULL DEFAULT 'generico',
    status TEXT NOT NULL DEFAULT 'queued',
    arquivo TEXT DEFAULT '',
    sha256 TEXT DEFAULT '',
    titulo TEXT DEFAULT '',
    autor TEXT DEFAULT '',
    duracao REAL DEFAULT 0,
    largura INTEGER DEFAULT 0,
    altura INTEGER DEFAULT 0,
    tamanho_bytes INTEGER DEFAULT 0,
    tentativas INTEGER NOT NULL DEFAULT 0,
    erro TEXT DEFAULT '',
    baixado_em TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(projeto_id, url)
);

CREATE TABLE IF NOT EXISTS mass_templates(
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    formato TEXT NOT NULL DEFAULT '9:16',
    modo_horizontal TEXT NOT NULL DEFAULT 'blur',
    logo_path TEXT DEFAULT '',
    logo_posicao TEXT DEFAULT 'inferior-direita',
    logo_escala REAL DEFAULT 0.15,
    logo_opacidade REAL DEFAULT 0.9,
    mockup_path TEXT DEFAULT '',
    mockup_posicao TEXT DEFAULT 'cobrir',
    mockup_opacidade REAL DEFAULT 1.0,
    cta_texto TEXT DEFAULT '',
    cta_posicao TEXT DEFAULT 'inferior',
    cta_tamanho REAL DEFAULT 0.055,
    audio TEXT NOT NULL DEFAULT 'manter',
    volume REAL DEFAULT 1.0,
    cortar_inicio REAL DEFAULT 0,
    cortar_fim REAL DEFAULT 0,
    velocidade REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mass_edicoes(
    id TEXT PRIMARY KEY,
    projeto_id TEXT NOT NULL REFERENCES mass_projetos(id) ON DELETE CASCADE,
    download_id TEXT REFERENCES mass_downloads(id) ON DELETE SET NULL,
    template_id TEXT REFERENCES mass_templates(id) ON DELETE SET NULL,
    entrada TEXT NOT NULL,
    saida TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    progresso REAL DEFAULT 0,
    largura INTEGER DEFAULT 0,
    altura INTEGER DEFAULT 0,
    duracao REAL DEFAULT 0,
    tentativas INTEGER NOT NULL DEFAULT 0,
    erro TEXT DEFAULT '',
    editado_em TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mass_publicacoes(
    id TEXT PRIMARY KEY,
    projeto_id TEXT NOT NULL REFERENCES mass_projetos(id) ON DELETE CASCADE,
    edicao_id TEXT REFERENCES mass_edicoes(id) ON DELETE SET NULL,
    plataforma TEXT NOT NULL DEFAULT 'instagram',
    conta TEXT DEFAULT '',
    arquivo TEXT NOT NULL,
    descricao TEXT DEFAULT '',
    hashtags TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    dry_run INTEGER NOT NULL DEFAULT 1,
    url_publicada TEXT DEFAULT '',
    erro TEXT DEFAULT '',
    publicado_em TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mass_audit(
    id TEXT PRIMARY KEY,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id TEXT,
    resultado TEXT NOT NULL DEFAULT 'ok',
    detalhe TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mass_downloads_fila ON mass_downloads(projeto_id, status);
CREATE INDEX IF NOT EXISTS idx_mass_edicoes_fila ON mass_edicoes(projeto_id, status);
CREATE INDEX IF NOT EXISTS idx_mass_pub_fila ON mass_publicacoes(projeto_id, status);

PRAGMA user_version=1;
"""


class MassaError(RuntimeError):
    """Erro do modulo, com mensagem legivel para a interface."""


def modulo_ligado() -> bool:
    return os.getenv("MASS_CONTENT_STUDIO_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "sim"
    }


def exigir_modulo() -> None:
    if not modulo_ligado():
        raise MassaError("Modulo desligado: defina MASS_CONTENT_STUDIO_ENABLED=true")


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


def listar(tabela: str, limite: int = 200, where: str = "", params=()):
    _validar(tabela)
    sql = f"SELECT * FROM {tabela}" + (f" WHERE {where}" if where else "")
    sql += " ORDER BY rowid ASC LIMIT ?"
    with conectar() as db:
        return [dict(x) for x in db.execute(sql, (*params, min(limite, 2000)))]


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


def contar(tabela: str, where: str = "", params=()) -> dict:
    """Contagem por status - alimenta as barras de progresso da interface."""
    _validar(tabela)
    sql = f"SELECT status, COUNT(*) AS total FROM {tabela}"
    if where:
        sql += f" WHERE {where}"
    sql += " GROUP BY status"
    with conectar() as db:
        return {linha["status"]: int(linha["total"]) for linha in db.execute(sql, params)}


def auditar(acao, entidade, entidade_id=None, detalhe=None, resultado="ok"):
    return inserir("mass_audit", {
        "acao": acao,
        "entidade": entidade,
        "entidade_id": entidade_id,
        "resultado": resultado,
        "detalhe": json.dumps(detalhe or {}, ensure_ascii=False),
        "created_at": agora(),
    })
