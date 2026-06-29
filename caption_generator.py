from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaptionLine:
    start_seconds: float
    end_seconds: float
    text: str


def gerar_legendas_basicas(video_path: str | Path) -> list[CaptionLine]:
    """Stub para futura integracao com Whisper/faster-whisper.

    Nesta etapa nao instalamos modelo pesado. A funcao existe para o pipeline
    aceitar legenda automatica no futuro sem mudar a arquitetura.
    """
    return []
