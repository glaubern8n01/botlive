"""Ponte entre Campanhas de Cortes e o VexPublish.

Campanhas nao controla navegador nem API de rede social: ela produz um
PublishJob e entrega para o VexPublish, que cuida de fila, limites, sessoes e
tentativas. O corte segue exportavel manualmente - a ponte e um caminho a
mais, desligado por padrao.

Barreiras antes de enfileirar:
  1. CAMPAIGNS_VEXPUBLISH_ENABLED=true;
  2. campanha com automation_policy diferente de manual-only;
  3. candidato aprovado por humano e nao bloqueado pelas regras;
  4. conta correspondente ja cadastrada no VexPublish.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .store import REPO_ROOT


class BridgeError(RuntimeError):
    """Falha de ponte com motivo legivel para a API."""


def habilitada() -> bool:
    return os.getenv("CAMPAIGNS_VEXPUBLISH_ENABLED", "false").strip().lower() == "true"


def _vexpublish():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from vexpublish.accounts import registry
        from vexpublish.core import models
    except ImportError as erro:  # pragma: no cover - so acontece fora do repo
        raise BridgeError(f"VexPublish indisponivel: {erro}") from erro
    return models, registry


def resolver_conta(channel: dict) -> dict:
    """Casa o canal da campanha com a conta ja cadastrada no VexPublish."""
    _, registry = _vexpublish()
    conta = registry.por_handle(channel["network"], channel["handle"])
    if not conta:
        raise BridgeError(
            f"Conta {channel['network']}/{channel['handle']} nao existe no VexPublish. "
            "Cadastre a conta e o canal la antes de enfileirar."
        )
    return conta


def enfileirar(publication: dict, candidate: dict, campaign: dict, channel: dict | None) -> dict:
    """Cria o PublishJob correspondente a uma publicacao ja preparada."""
    if not habilitada():
        raise BridgeError("Ponte desligada: defina CAMPAIGNS_VEXPUBLISH_ENABLED=true")
    if (campaign.get("automation_policy") or "manual-only") == "manual-only":
        raise BridgeError("Campanha marcada como manual-only; publicacao segue por exportacao")
    if candidate.get("status") != "approved":
        raise BridgeError("Candidato sem aprovacao humana")
    if candidate.get("checklist_status") == "blocked":
        raise BridgeError("Candidato bloqueado pelas regras da campanha")
    if not channel:
        raise BridgeError("Publicacao sem canal de destino")

    saida = candidate.get("output_path") or ""
    if not saida or not Path(saida).is_file():
        raise BridgeError("Arquivo final do corte indisponivel")

    models, _ = _vexpublish()
    conta = resolver_conta(channel)

    try:
        hashtags = json.loads(publication.get("hashtags") or "[]")
    except (TypeError, ValueError):
        hashtags = []

    job = models.PublishJob(
        channel_id=conta["channel_id"],
        platform=conta["platform"],
        account=conta["id"],
        media_path=saida,
        title=(candidate.get("hook") or campaign.get("name") or "")[:160],
        caption=publication.get("description") or candidate.get("caption") or "",
        hashtags=hashtags,
        requires_approval=True,
    ).criar()

    return {
        "publish_job_id": job["id"],
        "status": job["status"],
        "dry_run": bool(job["dry_run"]),
        "requires_approval": bool(job["requires_approval"]),
        "platform": job["platform"],
        "account_handle": conta["handle"],
    }
