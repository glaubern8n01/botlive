"""Sessoes por conta + plataforma.

Regras: uma pasta por conta+plataforma, fora do repositorio, nunca commitada,
nunca lida para dentro de log. O cofre guarda apenas o caminho e o estado -
o conteudo (cookies/storage_state) fica com o adapter que sabe usa-lo.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..core import store
from ..core.errors import CodigoErro, VexPublishError


ESTADOS = ("missing", "valid", "expired", "manual_required")

RAIZ_PADRAO = Path(__file__).resolve().parents[1] / "data" / "sessions"


def raiz() -> Path:
    return Path(os.getenv("VEXPUBLISH_SESSIONS_DIR", RAIZ_PADRAO)).resolve()


def caminho(account_id: str, platform: str) -> Path:
    destino = raiz() / platform / account_id
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def registrar(account_id: str, platform: str, estado: str = "missing") -> dict:
    if estado not in ESTADOS:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, f"Estado de sessao invalido: {estado}")
    destino = caminho(account_id, platform)
    stamp = store.agora()
    with store.conectar() as db:
        linha = db.execute(
            "SELECT * FROM vexpublish_sessions WHERE account_id=? AND platform=?",
            (account_id, platform),
        ).fetchone()
        if linha:
            db.execute(
                "UPDATE vexpublish_sessions SET storage_path=?,state=?,updated_at=? WHERE id=?",
                (str(destino), estado, stamp, linha["id"]),
            )
            return store.obter("vexpublish_sessions", linha["id"])
    return store.inserir(
        "vexpublish_sessions",
        {
            "account_id": account_id,
            "platform": platform,
            "storage_path": str(destino),
            "state": estado,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )


def obter(account_id: str, platform: str) -> dict | None:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT * FROM vexpublish_sessions WHERE account_id=? AND platform=?",
            (account_id, platform),
        ).fetchone()
    return dict(linha) if linha else None


def marcar(account_id: str, platform: str, estado: str, expires_at: str | None = None) -> dict:
    if estado not in ESTADOS:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, f"Estado de sessao invalido: {estado}")
    sessao = obter(account_id, platform) or registrar(account_id, platform)
    payload = {"state": estado, "last_checked_at": store.agora(), "updated_at": store.agora()}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    return store.atualizar("vexpublish_sessions", sessao["id"], payload)


def exigir_acao_manual(account_id: str, platform: str, motivo: str = "captcha/2fa") -> None:
    """Captcha e 2FA nunca sao contornados: a sessao para e pede humano."""
    marcar(account_id, platform, "manual_required")
    raise VexPublishError(
        CodigoErro.MANUAL_ACTION_REQUIRED,
        f"Acao manual necessaria em {platform}: {motivo}",
        {"account_id": account_id, "platform": platform},
    )
