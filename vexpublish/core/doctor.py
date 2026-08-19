"""Doctor: diagnostico de saude antes de escalar.

Cobre o que o documento pede na aba Saude: dependencias, sessoes, jobs
travados, storage e filas. Cada checagem devolve status proprio - `ok`,
`alerta` ou `erro` - e o relatorio nunca diz que esta tudo bem so porque
nenhuma checagem estourou excecao.

Dependencia ausente e `alerta`, nao `erro`: o modulo inteiro nasce desligado,
entao faltar ffmpeg numa maquina que ainda nao publica nao e falha.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone

from . import quotas, store
from .flags import PLATAFORMAS, carregar


DEPENDENCIAS = ("ffmpeg", "ffprobe", "yt-dlp")


def _check(nome: str, status: str, detalhe: dict | None = None, mensagem: str = "") -> dict:
    return {"check": nome, "status": status, "mensagem": mensagem, "detalhe": detalhe or {}}


def dependencias() -> dict:
    encontrados = {nome: bool(shutil.which(nome)) for nome in DEPENDENCIAS}
    faltando = [nome for nome, existe in encontrados.items() if not existe]
    return _check(
        "dependencias",
        "ok" if not faltando else "alerta",
        encontrados,
        "Todas presentes" if not faltando else f"Ausentes: {', '.join(faltando)}",
    )


def banco() -> dict:
    try:
        with store.conectar() as db:
            versao = db.execute("PRAGMA user_version").fetchone()[0]
            tabelas = [
                x[0]
                for x in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vexpublish_%'"
                )
            ]
    except Exception as erro:  # pragma: no cover - banco corrompido
        return _check("banco", "erro", {"erro": str(erro)}, "Banco inacessivel")
    esperado = len(store.TABELAS)
    return _check(
        "banco",
        "ok" if len(tabelas) == esperado else "erro",
        {"schema_version": versao, "tabelas": len(tabelas), "esperado": esperado},
        "Schema completo" if len(tabelas) == esperado else "Migracao pendente",
    )


def jobs_travados(minutos: int = 30) -> dict:
    corte = (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()
    with store.conectar() as db:
        linhas = db.execute(
            "SELECT id, channel_id, platform, locked_at, heartbeat_at FROM vexpublish_jobs "
            "WHERE status='publishing' AND COALESCE(heartbeat_at, locked_at) < ?",
            (corte,),
        ).fetchall()
    travados = [dict(x) for x in linhas]
    return _check(
        "jobs_travados",
        "ok" if not travados else "alerta",
        {"quantidade": len(travados), "ids": [x["id"] for x in travados][:20]},
        "Nenhum job travado" if not travados else f"{len(travados)} job(s) sem batida ha {minutos} min",
    )


def sessoes() -> dict:
    with store.conectar() as db:
        linhas = db.execute(
            "SELECT state, COUNT(*) AS total FROM vexpublish_sessions GROUP BY state"
        ).fetchall()
    por_estado = {x["state"]: int(x["total"]) for x in linhas}
    pendentes = por_estado.get("manual_required", 0) + por_estado.get("expired", 0)
    return _check(
        "sessoes",
        "ok" if not pendentes else "alerta",
        por_estado,
        "Nenhuma sessao pendente" if not pendentes else f"{pendentes} sessao(oes) exigem acao humana",
    )


def storage() -> dict:
    livre = quotas.disco_livre_gb()
    minimo = quotas.limites()["min_free_disk_gb"]
    if livre < 0:
        return _check("storage", "alerta", {"livre_gb": None}, "Nao foi possivel medir o disco")
    status = "ok" if livre >= minimo else "erro"
    return _check(
        "storage",
        status,
        {"livre_gb": livre, "minimo_gb": minimo},
        "Espaco suficiente" if status == "ok" else "Disco abaixo do minimo: a fila para",
    )


def filas() -> dict:
    with store.conectar() as db:
        por_status = {
            x["status"]: int(x["total"])
            for x in db.execute(
                "SELECT status, COUNT(*) AS total FROM vexpublish_jobs GROUP BY status"
            )
        }
        falhas = {
            x["last_error_code"]: int(x["total"])
            for x in db.execute(
                "SELECT last_error_code, COUNT(*) AS total FROM vexpublish_jobs "
                "WHERE last_error_code IS NOT NULL GROUP BY last_error_code"
            )
        }
    profundidade = sum(por_status.get(x, 0) for x in ("pending", "scheduled", "retry"))
    concluidos = por_status.get("posted", 0)
    falhados = por_status.get("failed", 0)
    total = concluidos + falhados
    taxa = round(falhados / total, 4) if total else None
    status = "alerta" if taxa is not None and taxa > 0.5 else "ok"
    return _check(
        "filas",
        status,
        {
            "por_status": por_status,
            "profundidade": profundidade,
            "taxa_de_falha": taxa,
            "falhas_por_codigo": falhas,
        },
        "Fila saudavel" if status == "ok" else "Mais da metade dos jobs esta falhando",
    )


def configuracao() -> dict:
    flags = carregar()
    liberadas = [x for x in PLATAFORMAS if flags.pode_publicar_de_verdade(x)]
    return _check(
        "configuracao",
        "ok",
        {
            "modulo_ligado": flags.enabled,
            "dry_run": flags.dry_run,
            "auto_publish": flags.auto_publish,
            "aprovacao_obrigatoria": flags.require_approval,
            "plataformas_liberadas_para_publicacao_real": liberadas,
        },
        "Publicacao real bloqueada" if not liberadas else f"Publicacao real liberada em: {liberadas}",
    )


CHECAGENS = (dependencias, banco, jobs_travados, sessoes, storage, filas, configuracao)


def diagnostico() -> dict:
    """Roda tudo e resume. `ok` so quando nenhuma checagem virou erro."""
    resultados = [checagem() for checagem in CHECAGENS]
    erros = [x for x in resultados if x["status"] == "erro"]
    alertas = [x for x in resultados if x["status"] == "alerta"]
    return {
        "ok": not erros,
        "resumo": {
            "erros": [x["check"] for x in erros],
            "alertas": [x["check"] for x in alertas],
            "verificado_em": store.agora(),
        },
        "checagens": resultados,
        "quotas": quotas.estado(),
    }
