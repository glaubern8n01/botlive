"""Quotas globais, acima dos limites por conta.

Limite por conta protege a conta. Quota global protege a maquina e o canal:
foi disco cheio que derrubou a VPS inteira uma vez, e nenhum limite por conta
teria impedido aquilo.

Todas nascem em 0 (sem teto), menos o disco - porque ficar sem espaco no meio
de um upload e a falha mais cara que ja aconteceu neste projeto.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone

from . import store


LIVRE = (True, "")


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


def _float(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


def limites() -> dict:
    return {
        "max_jobs_per_hour": _int("VEXPUBLISH_MAX_JOBS_PER_HOUR", 0),
        "max_queue_depth": _int("VEXPUBLISH_MAX_QUEUE_DEPTH", 0),
        "max_publishing": _int("VEXPUBLISH_MAX_PUBLISHING", 0),
        "min_free_disk_gb": _float("VEXPUBLISH_MIN_FREE_DISK_GB", 5.0),
    }


def disco_livre_gb(caminho=None) -> float:
    alvo = caminho or store.DB_PATH.parent
    try:
        return round(shutil.disk_usage(alvo).free / (1024 ** 3), 2)
    except OSError:
        return -1.0


def publicados_na_ultima_hora() -> int:
    corte = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with store.conectar() as db:
        linha = db.execute(
            "SELECT COUNT(*) AS total FROM vexpublish_jobs "
            "WHERE status='posted' AND posted_at>=?",
            (corte,),
        ).fetchone()
    return int(linha["total"]) if linha else 0


def profundidade_da_fila() -> int:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT COUNT(*) AS total FROM vexpublish_jobs "
            "WHERE status IN ('pending','scheduled','retry')"
        ).fetchone()
    return int(linha["total"]) if linha else 0


def publicando_agora() -> int:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT COUNT(*) AS total FROM vexpublish_jobs WHERE status='publishing'"
        ).fetchone()
    return int(linha["total"]) if linha else 0


def verificar() -> tuple[bool, str]:
    """Checagem barata rodada antes de reivindicar qualquer job."""
    atual = limites()

    livre = disco_livre_gb()
    if 0 <= livre < atual["min_free_disk_gb"]:
        return False, "disco_cheio"

    if atual["max_publishing"] and publicando_agora() >= atual["max_publishing"]:
        return False, "publicacoes_simultaneas"

    if atual["max_jobs_per_hour"] and publicados_na_ultima_hora() >= atual["max_jobs_per_hour"]:
        return False, "teto_por_hora"

    return LIVRE


def aceita_novo_job() -> tuple[bool, str]:
    """Trava de entrada: fila funda demais para de aceitar producao nova."""
    atual = limites()
    if atual["max_queue_depth"] and profundidade_da_fila() >= atual["max_queue_depth"]:
        return False, "fila_cheia"
    return LIVRE


def estado() -> dict:
    atual = limites()
    livre = disco_livre_gb()
    return {
        "limites": atual,
        "uso": {
            "publicados_ultima_hora": publicados_na_ultima_hora(),
            "profundidade_da_fila": profundidade_da_fila(),
            "publicando_agora": publicando_agora(),
            "disco_livre_gb": livre,
        },
        "bloqueios": [
            motivo
            for permitido, motivo in (verificar(), aceita_novo_job())
            if not permitido
        ],
    }
