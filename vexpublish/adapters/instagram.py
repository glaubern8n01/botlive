"""Adapter Instagram/Reels. Estado: NAO VALIDADO nesta fase.

Hoje o BotLive publica Reels por instagram_publisher.py com token de System
User. A migracao para este adapter e uma fase posterior, com dry-run antes.
"""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter, validar_midia


class InstagramAdapter(Adapter):
    plataforma = "instagram"
    compatibilidade = "NAO VALIDADO"

    def validate(self, job: dict, conta: dict) -> None:
        validar_midia(job)

    def prepare(self, job: dict, conta: dict) -> dict:
        return {
            "video_path": job["media_path"],
            "caption": job.get("caption") or "",
            "account": conta["handle"],
            "share_to_feed": True,
        }

    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED,
            "Publicacao real do Instagram ainda nao ligada ao VexPublish",
            {"platform": self.plataforma},
        )
