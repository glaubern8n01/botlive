"""Narracao local com Piper TTS. Sem GPU, sem API, sem token.

Escolhido depois de medir o hardware real: a VPS nao tem GPU e o PC tem uma
AMD RX 580 (4GB, sem CUDA e fora do ROCm). Isso derruba WanGP, Chatterbox e
qualquer TTS baseado em torch/GPU.

Piper roda em onnxruntime na CPU: ~1x tempo real (3.8s de fala em 3.6s de
processamento) e voz pt-BR nativa. O modelo fica em disco, entao depois do
primeiro download nao ha rede nenhuma envolvida.

Modelo: pt_BR-faber-medium (61 MB), licenca MIT do projeto piper-voices.
"""

from __future__ import annotations

import os
import wave
from dataclasses import dataclass
from pathlib import Path


RAIZ_VOZES = Path(__file__).resolve().parents[2] / "data" / "vozes"
VOZ_PADRAO = "pt_BR-faber-medium"


def diretorio_vozes() -> Path:
    return Path(os.getenv("MEDIA_VOICES_DIR", RAIZ_VOZES))


def vozes_disponiveis() -> list:
    pasta = diretorio_vozes()
    if not pasta.is_dir():
        return []
    return sorted(p.stem for p in pasta.glob("*.onnx"))


def caminho_da_voz(nome: str | None = None) -> Path:
    nome = nome or VOZ_PADRAO
    caminho = diretorio_vozes() / f"{nome}.onnx"
    if not caminho.is_file():
        raise FileNotFoundError(
            f"Voz {nome!r} nao encontrada em {diretorio_vozes()}. "
            f"Disponiveis: {vozes_disponiveis() or 'nenhuma'}"
        )
    return caminho


@dataclass
class Narracao:
    """Um trecho de fala. O texto e usado como esta - nada e reescrito aqui."""

    texto: str
    voz: str | None = None

    def render(self, destino: str | Path) -> Path:
        if not self.texto.strip():
            raise ValueError("Texto vazio: nao ha o que narrar")

        from piper import PiperVoice  # import tardio: so custa quando usado

        modelo = PiperVoice.load(str(caminho_da_voz(self.voz)))
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destino), "wb") as arquivo:
            modelo.synthesize_wav(self.texto, arquivo)
        return destino

    def duracao(self, destino: str | Path) -> float:
        import contextlib

        with contextlib.closing(wave.open(str(destino))) as arquivo:
            return arquivo.getnframes() / arquivo.getframerate()


def capacidades() -> dict:
    return {
        "provider": "piper-local",
        "tier": "local",
        "custo": 0.0,
        "gpu": False,
        "idioma": "pt-BR",
        "vozes": vozes_disponiveis(),
        "gera": ["narracao_wav"],
        "nao_gera": ["clonagem de voz", "voz de pessoa real"],
    }
