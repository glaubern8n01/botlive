from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg
from yt_dlp import YoutubeDL

from clipper import CACHE_DIR, preparar_pastas


LIVE_BLOCKS_DIR = CACHE_DIR / "live_blocks"


def _is_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "rtmp://", "m3u8://"))


def _source_label(value: str) -> str:
    lowered = value.lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return "YouTube"
    if "twitch.tv" in lowered:
        return "Twitch"
    if _is_url(value):
        return "URL"
    return "arquivo local"


@dataclass(frozen=True)
class LiveBlock:
    path: Path
    block_index: int
    start_offset_seconds: int
    duration_seconds: int


def _resolve_stream_url(live_url: str) -> str:
    ydl_opts = {
        "format": "best[height<=720]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(live_url, download=False)

    direct_url = info.get("url")
    if direct_url:
        return str(direct_url)

    formats = info.get("formats") or []
    for fmt in reversed(formats):
        if fmt.get("url"):
            return str(fmt["url"])

    raise RuntimeError("Nao consegui resolver a URL direta do stream com yt-dlp.")


def _run_ffmpeg(command: list[str], timeout_seconds: int) -> None:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr[-1200:] if stderr else "ffmpeg falhou sem mensagem.")


def capturar_bloco(
    source_url: str,
    session_id: str,
    block_index: int,
    start_offset_seconds: int,
    block_seconds: int = 45,
    retries: int = 2,
) -> Optional[LiveBlock]:
    preparar_pastas()
    session_dir = LIVE_BLOCKS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    block_path = session_dir / f"block_{block_index:06d}.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    local_source = None if _is_url(source_url) else Path(source_url)

    for attempt in range(1, retries + 2):
        try:
            if block_path.exists():
                block_path.unlink()

            if local_source and local_source.exists() and local_source.is_file():
                print("[modo live] fonte: arquivo local")
                command = [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(start_offset_seconds),
                    "-i",
                    str(local_source),
                    "-t",
                    str(block_seconds),
                    "-c",
                    "copy",
                    str(block_path),
                ]
            else:
                print(f"[modo live] fonte: {_source_label(source_url)}")
                print("[stream] tentando abrir com ffmpeg direto...")
                command = [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    source_url,
                    "-t",
                    str(block_seconds),
                    "-c",
                    "copy",
                    str(block_path),
                ]
                try:
                    _run_ffmpeg(command, timeout_seconds=block_seconds + 45)
                    if block_path.exists() and block_path.stat().st_size > 0:
                        print("[stream] ffmpeg direto funcionou")
                        print(f"[bloco] bloco {block_index} capturado: {block_path}")
                        print(f"[bloco] duracao alvo: {block_seconds}s")
                        return LiveBlock(
                            path=block_path,
                            block_index=block_index,
                            start_offset_seconds=start_offset_seconds,
                            duration_seconds=block_seconds,
                        )
                except Exception as exc:
                    print(f"[stream] ffmpeg direto falhou: {exc}")
                    print("[stream] tentando resolver com yt-dlp...")
                    stream_url = _resolve_stream_url(source_url)
                    print("[stream] URL resolvida com yt-dlp")
                    command = [
                        ffmpeg,
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        stream_url,
                        "-t",
                        str(block_seconds),
                        "-c",
                        "copy",
                        str(block_path),
                    ]

            _run_ffmpeg(command, timeout_seconds=block_seconds + 90)
            if block_path.exists() and block_path.stat().st_size > 0:
                print(f"[bloco] bloco {block_index} capturado: {block_path}")
                print(f"[bloco] duracao alvo: {block_seconds}s")
                return LiveBlock(
                    path=block_path,
                    block_index=block_index,
                    start_offset_seconds=start_offset_seconds,
                    duration_seconds=block_seconds,
                )
        except Exception as exc:
            print(f"[live-buffer] Falha no bloco {block_index} tentativa {attempt}: {exc}")

    return None
