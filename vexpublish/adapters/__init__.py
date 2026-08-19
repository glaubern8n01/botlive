"""Registro de adapters por plataforma."""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter, executar
from .instagram import InstagramAdapter
from .kwai import KwaiAdapter
from .tiktok import TikTokAdapter
from .youtube import YouTubeAdapter


REGISTRO = {
    "tiktok": TikTokAdapter,
    "instagram": InstagramAdapter,
    "youtube": YouTubeAdapter,
    "kwai": KwaiAdapter,
}


def obter(plataforma: str) -> Adapter:
    classe = REGISTRO.get((plataforma or "").strip().lower())
    if not classe:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, f"Sem adapter para {plataforma}", {"platform": plataforma}
        )
    return classe()


def compatibilidade() -> dict:
    return {nome: classe.compatibilidade for nome, classe in REGISTRO.items()}


__all__ = ["Adapter", "executar", "obter", "compatibilidade", "REGISTRO"]
