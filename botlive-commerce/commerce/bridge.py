"""Publicacao de criativo comercial pelo VexPublish.

O documento e explicito: "Shop e Shopee devem produzir jobs, nao controlar
diretamente navegador/API" e "nao duplicar VexPublish se o BotLive ja possuir".
Este modulo so cria PublishJob.

Antes da fila, a checagem obrigatoria do documento: produto, claims, direitos
dos assets, CTA, link e plataforma.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import creatives, products
from .store import CommerceError, REPO_ROOT, agora, atualizar, obter


def flags() -> dict:
    def ligado(nome, padrao):
        return os.getenv(nome, padrao).strip().lower() in {"1", "true", "yes", "sim"}

    return {
        "auto_publish": ligado("COMMERCE_AUTO_PUBLISH", "false"),
        "require_approval": ligado("COMMERCE_REQUIRE_APPROVAL", "true"),
        "dry_run": ligado("COMMERCE_DRY_RUN", "true"),
        "enabled": ligado("COMMERCE_ENABLED", "false"),
    }


def _vexpublish():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from vexpublish.accounts import registry
        from vexpublish.core import models, store
    except ImportError as erro:  # pragma: no cover - so acontece fora do repo
        raise CommerceError(f"VexPublish indisponivel: {erro}") from erro
    return models, registry, store


def checar_antes_de_publicar(creative_id: str) -> dict:
    """As seis conferencias do documento. Devolve o relatorio, nao publica."""
    criativo = obter("commerce_creatives", creative_id)
    if not criativo:
        raise CommerceError("Criativo inexistente")
    ficha = products.ficha(criativo["product_id"])

    problemas = []
    if criativo["status"] != "approved":
        problemas.append("criativo sem aprovacao humana")

    qa = json.loads(criativo["qa"] or "{}")
    if not qa.get("ok"):
        problemas.append("QA nao esta limpo")

    if not ficha["claims_allowed"]:
        problemas.append("produto sem claim sustentado")

    assets = creatives.biblioteca(criativo["product_id"])
    ids = set(json.loads(criativo["asset_ids"] or "[]"))
    usados = [x for x in assets if x["id"] in ids]
    if not usados:
        problemas.append("criativo sem asset registrado")
    if any(not x["rights"].strip() for x in usados):
        problemas.append("asset sem direito de uso declarado")

    if not criativo["cta"].strip():
        problemas.append("sem CTA")
    if not ficha["affiliate_url"]:
        problemas.append("produto sem link")
    if ficha["platform"] not in products.PLATAFORMAS:
        problemas.append("plataforma comercial invalida")

    return {"ok": not problemas, "problemas": problemas, "creative_id": creative_id}


def enfileirar(creative_id: str, channel_id: str, platform: str | None = None) -> dict:
    """Cria um PublishJob por conta ativa do canal, em draft e dry-run."""
    estado = flags()
    if not estado["enabled"]:
        raise CommerceError("Modulo desligado: defina COMMERCE_ENABLED=true")
    if estado["auto_publish"]:
        raise CommerceError(
            "COMMERCE_AUTO_PUBLISH=true nao e suportado nesta fase: a fila exige aprovacao"
        )

    relatorio = checar_antes_de_publicar(creative_id)
    if not relatorio["ok"]:
        raise CommerceError("Bloqueado antes da fila: " + "; ".join(relatorio["problemas"]))

    criativo = obter("commerce_creatives", creative_id)
    saida = criativo["output_path"]
    if not saida or not Path(saida).is_file():
        raise CommerceError("Arquivo do criativo indisponivel")

    models, registry, store_vex = _vexpublish()
    if not store_vex.obter("vexpublish_channels", channel_id):
        raise CommerceError("Canal nao existe no VexPublish")

    contas = [x for x in registry.por_canal(channel_id) if x["status"] == "active"]
    if platform:
        contas = [x for x in contas if x["platform"] == platform]
    if not contas:
        raise CommerceError("Canal sem conta ativa para receber a fila")

    ficha = products.ficha(criativo["product_id"])
    legenda = " ".join(filter(None, [criativo["script"], criativo["cta"], ficha["affiliate_url"]]))

    criados = []
    for conta in contas:
        job = models.PublishJob(
            channel_id=conta["channel_id"],
            platform=conta["platform"],
            account=conta["id"],
            media_path=saida,
            title=criativo["hook"][:160],
            caption=legenda,
            requires_approval=True,
        ).criar()
        criados.append(
            {
                "publish_job_id": job["id"],
                "platform": job["platform"],
                "account_handle": conta["handle"],
                "status": job["status"],
                "dry_run": bool(job["dry_run"]),
            }
        )

    atualizar(
        "commerce_creatives",
        creative_id,
        {
            "status": "queued",
            "publish_job_ids": json.dumps([x["publish_job_id"] for x in criados]),
            "updated_at": agora(),
        },
    )
    return {"creative_id": creative_id, "jobs": criados, "total": len(criados)}
