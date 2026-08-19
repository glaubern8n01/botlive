"""Comparacao entre canais.

O documento pede comparar canais por views, retencao, frequencia, falhas,
monetizacao e receita "quando os dados estiverem disponiveis". Aqui essa
ressalva e literal: metrica sem snapshot registrado volta zerada e com
`sem_metricas: True`, em vez de virar numero inventado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import store
from .errors import CodigoErro, VexPublishError
from .flags import PLATAFORMAS


JANELA_PADRAO_DIAS = 30


def _corte(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


def registrar_snapshot(
    channel_id: str,
    platform: str,
    views: int = 0,
    watch_seconds: float = 0.0,
    retention: float = 0.0,
    revenue: float = 0.0,
    job_id: str | None = None,
    source: str = "manual",
    currency: str = "BRL",
) -> dict:
    """Grava uma medicao. Receita e views informadas a mao ficam com source=manual."""
    if platform not in PLATAFORMAS:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, f"Plataforma invalida: {platform}")
    if not store.obter("vexpublish_channels", channel_id):
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Canal inexistente")
    if views < 0 or revenue < 0 or watch_seconds < 0:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Metrica negativa")
    if not 0 <= retention <= 1:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Retencao deve ficar entre 0 e 1")
    if job_id and not store.obter("vexpublish_jobs", job_id):
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Job inexistente")
    return store.inserir(
        "vexpublish_metric_snapshots",
        {
            "channel_id": channel_id,
            "job_id": job_id,
            "platform": platform,
            "views": int(views),
            "watch_seconds": float(watch_seconds),
            "retention": float(retention),
            "revenue": float(revenue),
            "currency": currency,
            "source": source,
            "recorded_at": store.agora(),
        },
    )


def _jobs_do_canal(channel_id: str, desde: str) -> dict:
    with store.conectar() as db:
        por_status = db.execute(
            "SELECT status, COUNT(*) AS total FROM vexpublish_jobs "
            "WHERE channel_id=? GROUP BY status",
            (channel_id,),
        ).fetchall()
        publicados = db.execute(
            "SELECT COUNT(*) AS total, MAX(posted_at) AS ultimo FROM vexpublish_jobs "
            "WHERE channel_id=? AND status='posted' AND posted_at>=?",
            (channel_id, desde),
        ).fetchone()
        falhas = db.execute(
            "SELECT last_error_code AS codigo, COUNT(*) AS total FROM vexpublish_jobs "
            "WHERE channel_id=? AND status IN ('failed','retry') AND last_error_code IS NOT NULL "
            "GROUP BY last_error_code",
            (channel_id,),
        ).fetchall()
    return {
        "por_status": {linha["status"]: int(linha["total"]) for linha in por_status},
        "publicados": int(publicados["total"]) if publicados else 0,
        "ultima_publicacao": publicados["ultimo"] if publicados else None,
        "falhas_por_codigo": {linha["codigo"]: int(linha["total"]) for linha in falhas},
    }


def _metricas_do_canal(channel_id: str, desde: str) -> dict:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT COUNT(*) AS amostras, COALESCE(SUM(views),0) AS views, "
            "COALESCE(SUM(revenue),0) AS receita, COALESCE(AVG(retention),0) AS retencao "
            "FROM vexpublish_metric_snapshots WHERE channel_id=? AND recorded_at>=?",
            (channel_id, desde),
        ).fetchone()
    amostras = int(linha["amostras"]) if linha else 0
    return {
        "amostras": amostras,
        "views": int(linha["views"]) if linha else 0,
        "receita": round(float(linha["receita"]), 2) if linha else 0.0,
        "retencao_media": round(float(linha["retencao"]), 4) if linha else 0.0,
        "sem_metricas": amostras == 0,
    }


def resumo_canal(channel_id: str, dias: int = JANELA_PADRAO_DIAS) -> dict:
    canal = store.obter("vexpublish_channels", channel_id)
    if not canal:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Canal inexistente")
    desde = _corte(dias)
    jobs = _jobs_do_canal(channel_id, desde)
    metricas = _metricas_do_canal(channel_id, desde)
    contas = store.listar("vexpublish_accounts", where="channel_id=?", params=(channel_id,))

    publicados = jobs["publicados"]
    falhados = sum(jobs["falhas_por_codigo"].values())
    tentados = publicados + falhados
    return {
        "channel_id": channel_id,
        "name": canal["name"],
        "slug": canal["slug"],
        "niche": canal["niche"],
        "status": canal["status"],
        "janela_dias": dias,
        "contas": len(contas),
        "contas_ativas": sum(1 for x in contas if x["status"] == "active"),
        "plataformas": sorted({x["platform"] for x in contas}),
        "publicados": publicados,
        "frequencia_por_dia": round(publicados / dias, 3) if dias else 0.0,
        "falhas": falhados,
        "falhas_por_codigo": jobs["falhas_por_codigo"],
        "taxa_sucesso": round(publicados / tentados, 4) if tentados else None,
        "ultima_publicacao": jobs["ultima_publicacao"],
        "fila": jobs["por_status"],
        **metricas,
    }


def comparar_canais(dias: int = JANELA_PADRAO_DIAS, incluir_pausados: bool = True) -> dict:
    """Uma linha por canal, ordenada por views e depois por publicacoes."""
    canais = store.listar("vexpublish_channels", limite=500)
    if not incluir_pausados:
        canais = [x for x in canais if x["status"] == "active"]
    linhas = [resumo_canal(canal["id"], dias) for canal in canais]
    linhas.sort(key=lambda x: (x["views"], x["publicados"]), reverse=True)
    return {
        "janela_dias": dias,
        "canais": linhas,
        "totais": {
            "canais": len(linhas),
            "publicados": sum(x["publicados"] for x in linhas),
            "falhas": sum(x["falhas"] for x in linhas),
            "views": sum(x["views"] for x in linhas),
            "receita": round(sum(x["receita"] for x in linhas), 2),
        },
        "canais_sem_metricas": [x["slug"] for x in linhas if x["sem_metricas"]],
    }


def historico_canal(channel_id: str, limite: int = 50) -> list:
    """Ultimos jobs do canal, do mais recente para o mais antigo."""
    return store.listar(
        "vexpublish_jobs", limite=limite, where="channel_id=?", params=(channel_id,)
    )
