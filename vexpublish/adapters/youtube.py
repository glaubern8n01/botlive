"""Adapter YouTube Shorts. Estado: NAO VALIDADO nesta fase.

O fluxo atual usa yt_publisher.py com OAuth do app em producao. Este adapter
so assume o envio depois de dry-run e de um teste com publicacao unlisted.
"""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter, validar_midia


LIMITE_TITULO = 100


class YouTubeAdapter(Adapter):
    plataforma = "youtube"
    compatibilidade = "NAO VALIDADO"

    def validate(self, job: dict, conta: dict) -> None:
        validar_midia(job)
        if not (job.get("title") or "").strip():
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, "YouTube exige titulo")

    def prepare(self, job: dict, conta: dict) -> dict:
        return {
            "video_path": job["media_path"],
            "title": (job.get("title") or "")[:LIMITE_TITULO],
            "description": job.get("caption") or "",
            "tags": job.get("hashtags") or "[]",
            "privacy_status": "private",
            "account": conta["handle"],
        }

    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED,
            "Publicacao real do YouTube ainda nao ligada ao VexPublish",
            {"platform": self.plataforma},
        )
