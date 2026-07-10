from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from yt_dlp import YoutubeDL

from clipper import preparar_pastas
from runtime_paths import sources_dir, temp_dir
from ytdlp_config import com_opcoes_env


def _is_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "rtmp://", "m3u8://"))


def _find_source_video(work_dir: Path) -> Path:
    candidates = [
        path
        for path in work_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not candidates:
        raise FileNotFoundError("yt-dlp nao gerou arquivo de video para analisar.")
    return max(candidates, key=lambda path: path.stat().st_size)


def resolver_fonte_video(source: str) -> Path:
    """Aceita arquivo local ou URL. URL e baixada no Drive D para analise offline."""
    preparar_pastas()
    if not _is_url(source):
        source_path = Path(source)
        if source_path.exists() and source_path.is_file():
            return source_path

    job_id = uuid4().hex[:12]
    work_dir = sources_dir() / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/best[height<=1080]/best",
        "outtmpl": str(work_dir / "source_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "paths": {"home": str(work_dir), "temp": str(temp_dir())},
    }

    with YoutubeDL(com_opcoes_env(ydl_opts)) as ydl:
        ydl.download([source])

    return _find_source_video(work_dir)
