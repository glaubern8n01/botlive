"""Registro de contas: consulta, ativacao e ajuste de limites.

Ativar conta e uma acao separada de habilitar a plataforma. Uma conta ativa em
plataforma desligada continua sem publicar nada.
"""

from __future__ import annotations

import json

from ..core import store
from ..core.errors import CodigoErro, VexPublishError
from ..core.flags import PLATAFORMAS


CAMPOS_DE_LIMITE = {"max_posts_per_day", "minimum_interval_minutes", "allowed_hours", "timezone"}


def por_canal(channel_id: str, platform: str | None = None) -> list:
    where = "channel_id=?"
    params = [channel_id]
    if platform:
        where += " AND platform=?"
        params.append(platform)
    return store.listar("vexpublish_accounts", where=where, params=tuple(params))


def por_handle(platform: str, handle: str) -> dict | None:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT * FROM vexpublish_accounts WHERE platform=? AND handle=?",
            (platform, handle),
        ).fetchone()
    return dict(linha) if linha else None


def ativar(account_id: str) -> dict:
    return store.atualizar(
        "vexpublish_accounts", account_id, {"status": "active", "updated_at": store.agora()}
    )


def pausar(account_id: str, motivo: str = "") -> dict:
    return store.atualizar(
        "vexpublish_accounts",
        account_id,
        {"status": "paused", "label": motivo or "", "updated_at": store.agora()},
    )


def definir_limites(account_id: str, **limites) -> dict:
    desconhecidos = set(limites) - CAMPOS_DE_LIMITE
    if desconhecidos:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, f"Campos de limite invalidos: {sorted(desconhecidos)}"
        )
    payload = dict(limites)
    if "allowed_hours" in payload:
        horas = payload["allowed_hours"] or []
        for hora in horas:
            if not isinstance(hora, int) or not 0 <= hora <= 23:
                raise VexPublishError(
                    CodigoErro.VALIDATION_ERROR, "allowed_hours aceita apenas horas 0-23"
                )
        payload["allowed_hours"] = json.dumps(sorted(horas), ensure_ascii=False)
    for chave in ("max_posts_per_day", "minimum_interval_minutes"):
        if chave in payload and int(payload[chave]) < 0:
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, f"{chave} nao pode ser negativo")
    payload["updated_at"] = store.agora()
    return store.atualizar("vexpublish_accounts", account_id, payload)


def resumo() -> dict:
    """Contagem por plataforma e status, para a aba Saude do dashboard."""
    with store.conectar() as db:
        linhas = db.execute(
            "SELECT platform, status, COUNT(*) AS total FROM vexpublish_accounts "
            "GROUP BY platform, status"
        ).fetchall()
    dados = {plataforma: {} for plataforma in PLATAFORMAS}
    for linha in linhas:
        dados.setdefault(linha["platform"], {})[linha["status"]] = int(linha["total"])
    return dados
