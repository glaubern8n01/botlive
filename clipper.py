from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Optional
from PIL import Image
from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

try:
    from moviepy.editor import VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import VideoFileClip


BASE_DIR = Path("D:/robo-cortes-dark")
CACHE_DIR = BASE_DIR / "cache"
CORTES_DIR = BASE_DIR / "cortes"
TEMP_DIR = CACHE_DIR / "tmp"


def preparar_pastas() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CORTES_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(TEMP_DIR)
    os.environ["TEMP"] = str(TEMP_DIR)
    os.environ["TMPDIR"] = str(TEMP_DIR)


def limpar_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for item in CACHE_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def _find_downloaded_video(work_dir: Path) -> Path:
    candidates = [
        path
        for path in work_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not candidates:
        raise FileNotFoundError("yt-dlp nao gerou nenhum arquivo de video no cache.")
    return max(candidates, key=lambda path: path.stat().st_size)


def baixar_trecho(
    video_url: str,
    peak_timestamp: int,
    clip_id: str,
    seconds_before: int = 30,
    seconds_after: int = 30,
) -> Path:
    preparar_pastas()
    limpar_cache()

    start = max(0, int(peak_timestamp) - seconds_before)
    end = int(peak_timestamp) + seconds_after
    work_dir = CACHE_DIR / f"job_{clip_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "outtmpl": str(work_dir / "raw_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "paths": {"home": str(work_dir), "temp": str(TEMP_DIR)},
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    return _find_downloaded_video(work_dir)


def aplicar_crop_vertical(
    input_path: Path,
    output_path: Path,
    target_width: int = 1080,
    target_height: int = 1920,
    focus_x: float = 0.5,
) -> None:
    preparar_pastas()
    focus_x = min(1.0, max(0.0, focus_x))

    clip = VideoFileClip(str(input_path))
    try:
        source_w, source_h = clip.size
        target_ratio = target_width / target_height
        source_ratio = source_w / source_h

        if source_ratio > target_ratio:
            crop_h = source_h
            crop_w = int(crop_h * target_ratio)
            x1 = int((source_w - crop_w) * focus_x)
            y1 = 0
        else:
            crop_w = source_w
            crop_h = int(crop_w / target_ratio)
            x1 = 0
            y1 = max(0, int((source_h - crop_h) / 2))

        x2 = min(source_w, x1 + crop_w)
        y2 = min(source_h, y1 + crop_h)

        vertical = clip.crop(x1=x1, y1=y1, x2=x2, y2=y2).resize((target_width, target_height))
        try:
            vertical.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="medium",
                threads=os.cpu_count() or 4,
                temp_audiofile=str(TEMP_DIR / f"{output_path.stem}_audio.m4a"),
                remove_temp=True,
                verbose=False,
                logger=None,
            )
        finally:
            vertical.close()
    finally:
        clip.close()


def criar_corte_vertical_de_arquivo(
    input_video_path: str | Path,
    peak_timestamp: int,
    clip_id: str,
    seconds_before: int = 30,
    seconds_after: int = 30,
    focus_x: float = 0.5,
    overlay_config: Optional[Any] = None,
) -> Path:
    preparar_pastas()
    input_video_path = Path(input_video_path)
    output_path = CORTES_DIR / f"corte_{clip_id}.mp4"

    source = VideoFileClip(str(input_video_path))
    try:
        start = max(0, int(peak_timestamp) - seconds_before)
        end = min(float(source.duration), int(peak_timestamp) + seconds_after)
        if end <= start:
            raise ValueError(f"Janela invalida para corte: start={start}, end={end}")

        segment_path = CACHE_DIR / f"segment_{clip_id}.mp4"
        segment = source.subclip(start, end)
        try:
            segment.write_videofile(
                str(segment_path),
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="ultrafast",
                threads=os.cpu_count() or 4,
                temp_audiofile=str(TEMP_DIR / f"{clip_id}_segment_audio.m4a"),
                remove_temp=True,
                verbose=False,
                logger=None,
            )
        finally:
            segment.close()
    finally:
        source.close()

    try:
        aplicar_crop_vertical(
            input_path=segment_path,
            output_path=output_path,
            focus_x=focus_x,
        )
        if overlay_config and getattr(overlay_config, "enabled", False):
            from overlay_editor import aplicar_overlay_no_video

            return aplicar_overlay_no_video(output_path, overlay_config)
        return output_path
    finally:
        segment_path.unlink(missing_ok=True)


def criar_corte_vertical(
    video_url: str,
    peak_timestamp: int,
    clip_id: str,
    seconds_before: int = 30,
    seconds_after: int = 30,
    focus_x: float = 0.5,
) -> Path:
    preparar_pastas()
    output_path = CORTES_DIR / f"corte_{clip_id}.mp4"

    try:
        input_path = baixar_trecho(
            video_url=video_url,
            peak_timestamp=peak_timestamp,
            clip_id=clip_id,
            seconds_before=seconds_before,
            seconds_after=seconds_after,
        )
        aplicar_crop_vertical(
            input_path=input_path,
            output_path=output_path,
            focus_x=focus_x,
        )
        return output_path
    finally:
        limpar_cache()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Baixa trecho e renderiza corte vertical 9:16.")
    parser.add_argument("url", help="URL do video/live.")
    parser.add_argument("timestamp", type=int, help="Timestamp do pico em segundos.")
    parser.add_argument("--id", default="teste", help="ID usado no nome final do corte.")
    args = parser.parse_args()

    path = criar_corte_vertical(args.url, args.timestamp, args.id)
    print(f"Corte finalizado: {path}")
