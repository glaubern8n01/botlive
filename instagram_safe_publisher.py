from __future__ import annotations

"""Camada de compatibilidade para o upload de Reels.

A Meta pode aceitar o container e rejeitar o binario com
ProcessingFailedError quando o MP4 possui perfil, pixel format, timestamps ou
moov atom fora do esperado. Este adaptador cria uma copia deterministica e
compativel antes de delegar ao publicador existente.
"""

import json
import subprocess
from pathlib import Path

import instagram_publisher


def _normalizado_path(original: Path) -> Path:
    return original.with_name(f"{original.stem}_instagram.mp4")


def _normalizar(original: Path) -> Path:
    destino = _normalizado_path(original)
    if destino.is_file() and destino.stat().st_size > 0 and destino.stat().st_mtime >= original.stat().st_mtime:
        print(f"[ig-normalize] reutilizando {destino.name}")
        return destino

    temporario = destino.with_suffix(".rendering.mp4")
    temporario.unlink(missing_ok=True)
    comando = [
        "ffmpeg", "-y", "-i", str(original),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-g", "60", "-keyint_min", "30", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-avoid_negative_ts", "make_zero",
        "-max_muxing_queue_size", "2048",
        str(temporario),
    ]
    print(f"[ig-normalize] preparando MP4 compativel para a Meta: {original.name}")
    concluido = subprocess.run(comando, capture_output=True, text=True, timeout=1200)
    if concluido.returncode != 0 or not temporario.is_file() or temporario.stat().st_size == 0:
        detalhe = (concluido.stderr or concluido.stdout or "ffmpeg falhou")[-2000:]
        temporario.unlink(missing_ok=True)
        raise RuntimeError(f"normalizacao Instagram falhou: {detalhe}")
    temporario.replace(destino)
    print(f"[ig-normalize] pronto: {destino.name} ({destino.stat().st_size / 1e6:.1f}MB)")
    return destino


def postar_corte_registro(registro: dict, config) -> dict:
    if config.dry_run:
        return instagram_publisher.postar_corte_registro(registro, config)

    raw = registro.get("vertical")
    if not raw:
        return instagram_publisher.postar_corte_registro(registro, config)
    original = Path(str(raw))
    if not original.is_file():
        return instagram_publisher.postar_corte_registro(registro, config)

    seguro = _normalizar(original)
    registro_seguro = dict(registro)
    registro_seguro["vertical"] = str(seguro)
    resultado = instagram_publisher.postar_corte_registro(registro_seguro, config)
    resultado.setdefault("normalizacao_instagram", {})
    resultado["normalizacao_instagram"].update({
        "original": str(original),
        "arquivo_enviado": str(seguro),
        "formato": "h264-high-4.1-yuv420p-aac-1080x1920-30fps-faststart",
    })
    return resultado
