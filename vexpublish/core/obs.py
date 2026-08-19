"""Log estruturado do VexPublish.

Nenhum cookie, token, senha ou header de autorizacao pode sair daqui. O
redator roda sobre todo dicionario antes de virar JSON, inclusive aninhado.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

from .errors import CODIGOS


CAMPOS = (
    "job_id",
    "channel_id",
    "platform",
    "account",
    "action",
    "status",
    "timestamp",
    "error_code",
)

CHAVES_SENSIVEIS = re.compile(
    r"(cookie|token|senha|password|secret|authorization|bearer|session_id|api_key|refresh)",
    re.IGNORECASE,
)

VALOR_MASCARADO = "***"


def _mascarar(valor):
    if isinstance(valor, dict):
        return {
            chave: (VALOR_MASCARADO if CHAVES_SENSIVEIS.search(str(chave)) else _mascarar(item))
            for chave, item in valor.items()
        }
    if isinstance(valor, (list, tuple)):
        return [_mascarar(item) for item in valor]
    return valor


def redigir(payload: dict) -> dict:
    """Devolve copia do payload sem valores sensiveis. Usada tambem nos testes."""
    return _mascarar(dict(payload or {}))


def evento(
    action: str,
    status: str,
    job_id: str | None = None,
    channel_id: str | None = None,
    platform: str | None = None,
    account: str | None = None,
    error_code: str | None = None,
    **extra,
) -> dict:
    if error_code and error_code not in CODIGOS:
        error_code = "UNKNOWN"
    registro = {
        "job_id": job_id,
        "channel_id": channel_id,
        "platform": platform,
        "account": account,
        "action": action,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error_code": error_code,
    }
    if extra:
        registro["detail"] = redigir(extra)
    return registro


def registrar(*args, **kwargs) -> dict:
    """Monta o evento e escreve uma linha JSON em stderr."""
    registro = evento(*args, **kwargs)
    if os.getenv("VEXPUBLISH_LOG_SILENT", "false").strip().lower() not in {"1", "true", "yes"}:
        print(json.dumps(registro, ensure_ascii=False), file=sys.stderr, flush=True)
    return registro
