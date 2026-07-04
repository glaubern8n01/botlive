from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Modelo small em portugues, int8/CPU: roda na VPS sem GPU. O download do
# modelo (~460MB) acontece uma vez; no Docker ele entra no build da imagem.
MODEL_SIZE = "small"
MODEL_COMPUTE_TYPE = "int8"
MODEL_LANGUAGE = "pt"

_model = None


@dataclass(frozen=True)
class TranscricaoResultado:
    text: str
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    segments: list[str] = field(default_factory=list)

    @property
    def has_speech(self) -> bool:
        return bool(self.text.strip())


def _carregar_modelo():
    """Carrega o modelo uma unica vez por processo (lazy singleton)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type=MODEL_COMPUTE_TYPE)
    return _model


def transcrever_fala(video_path: str | Path) -> TranscricaoResultado:
    """Transcreve a FALA de um corte curto (30-40s) com faster-whisper local.

    Nunca levanta excecao: corte sem fala, arquivo ruim ou modelo indisponivel
    retornam resultado vazio com o motivo em .error — o pipeline nunca quebra.
    O vad_filter descarta trechos sem voz (musica/barulho de jogo).
    """
    video_path = Path(video_path)
    started = time.monotonic()
    if not video_path.exists():
        return TranscricaoResultado(text="", error=f"arquivo nao existe: {video_path}")

    try:
        model = _carregar_modelo()
        segments, info = model.transcribe(
            str(video_path),
            language=MODEL_LANGUAGE,
            vad_filter=True,
            beam_size=5,
        )
        parts = [segment.text.strip() for segment in segments if segment.text.strip()]
        return TranscricaoResultado(
            text=" ".join(parts),
            duration_seconds=float(info.duration or 0.0),
            elapsed_seconds=time.monotonic() - started,
            segments=parts,
        )
    except Exception as exc:
        return TranscricaoResultado(
            text="",
            elapsed_seconds=time.monotonic() - started,
            error=str(exc),
        )


if __name__ == "__main__":
    import argparse

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Transcreve a fala de cortes curtos com faster-whisper (small/pt/int8).")
    parser.add_argument("inputs", nargs="+", help="Um ou mais arquivos de corte (.mp4).")
    args = parser.parse_args()

    for input_path in args.inputs:
        result = transcrever_fala(input_path)
        print(f"\n=== {input_path}")
        print(f"    duracao={result.duration_seconds:.1f}s tempo_transcricao={result.elapsed_seconds:.1f}s")
        if result.error:
            print(f"    [sem quebra] erro tratado: {result.error}")
        elif not result.has_speech:
            print("    [sem fala] nenhum trecho de voz detectado.")
        else:
            print(f"    texto: {result.text}")
