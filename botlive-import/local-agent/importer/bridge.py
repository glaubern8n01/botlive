"""Fila por canal: adaptacao pronta -> PublishJob no VexPublish.

Como em Campanhas de Cortes, este modulo nao fala com navegador nem com API
de rede social. Ele entrega um job e para por ai. O job nasce em draft, com
dry-run e aprovacao obrigatoria.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .store import ImportError_, REPO_ROOT, agora, atualizar, obter


def habilitado() -> bool:
    return os.getenv("IMPORT_ADAPT_PUBLISH_ENABLED", "false").strip().lower() == "true"


def _vexpublish():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from vexpublish.accounts import registry
        from vexpublish.core import models, store
    except ImportError as erro:  # pragma: no cover - so acontece fora do repo
        raise ImportError_(f"VexPublish indisponivel: {erro}") from erro
    return models, registry, store


def contas_do_canal(channel_id: str) -> list:
    _, registry, _ = _vexpublish()
    return [x for x in registry.por_canal(channel_id) if x["status"] == "active"]


def enfileirar(adaptation_id: str, platform: str | None = None, caption: str = "") -> dict:
    """Cria um PublishJob por conta ativa do canal.

    Sem conta ativa nao ha fila: o modulo recusa em vez de escolher conta
    sozinho ou publicar em canal errado.
    """
    if not habilitado():
        raise ImportError_("Modulo desligado: defina IMPORT_ADAPT_PUBLISH_ENABLED=true")

    adaptacao = obter("import_adaptations", adaptation_id)
    if not adaptacao:
        raise ImportError_("Adaptacao inexistente")
    # "queued" tambem passa: enfileirar de novo e seguro (a chave de
    # idempotencia do VexPublish devolve o mesmo job) e e o caminho normal
    # quando uma conta nova entra no canal depois da primeira fila.
    if adaptacao["status"] not in {"rendered", "queued"}:
        raise ImportError_("Adaptacao ainda nao foi renderizada")
    if not adaptacao["channel_id"]:
        raise ImportError_("Adaptacao sem canal de destino")
    saida = adaptacao["output_path"]
    if not saida or not Path(saida).is_file():
        raise ImportError_("Arquivo adaptado indisponivel")

    models, _, store_vex = _vexpublish()
    if not store_vex.obter("vexpublish_channels", adaptacao["channel_id"]):
        raise ImportError_("Canal nao existe no VexPublish")

    contas = contas_do_canal(adaptacao["channel_id"])
    if platform:
        contas = [x for x in contas if x["platform"] == platform]
    if not contas:
        raise ImportError_("Canal sem conta ativa para receber a fila")

    plano = json.loads(adaptacao["plan"])
    criados = []
    for conta in contas:
        job = models.PublishJob(
            channel_id=conta["channel_id"],
            platform=conta["platform"],
            account=conta["id"],
            media_path=saida,
            title=plano.get("title") or "",
            caption=caption or plano.get("description") or "",
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
        "import_adaptations",
        adaptation_id,
        {
            "status": "queued",
            "publish_job_id": ",".join(x["publish_job_id"] for x in criados),
            "updated_at": agora(),
        },
    )
    return {"adaptation_id": adaptation_id, "jobs": criados, "total": len(criados)}
