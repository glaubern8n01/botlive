"""Adapter TikTok. Estado: NAO VALIDADO nesta fase.

O BotLive ja possui tiktok_publisher.py (fluxo legado de rascunho via inbox).
Este adapter nao o substitui ainda: ele existe para que os jobs passem a ser
criados no formato PublishJob antes de qualquer troca de motor.
"""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter, validar_midia


LIMITE_TITULO = 150


class TikTokAdapter(Adapter):
    plataforma = "tiktok"
    compatibilidade = "NAO VALIDADO"

    def validate(self, job: dict, conta: dict) -> None:
        validar_midia(job)
        if len(job.get("caption") or "") > LIMITE_TITULO * 10:
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Legenda longa demais para TikTok")

    def prepare(self, job: dict, conta: dict) -> dict:
        return {
            "video_path": job["media_path"],
            "title": (job.get("title") or "")[:LIMITE_TITULO],
            "caption": job.get("caption") or "",
            "hashtags": job.get("hashtags") or "[]",
            "account": conta["handle"],
        }

    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED,
            "Publicacao real do TikTok ainda nao ligada ao VexPublish",
            {"platform": self.plataforma},
        )
