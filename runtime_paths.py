from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_OUTPUT_ROOT = Path("D:/robo-cortes-dark")
_output_root = DEFAULT_OUTPUT_ROOT
_output_tag: Optional[str] = None


def set_output_root(path: Optional[str | Path]) -> Path:
    global _output_root
    if path:
        _output_root = Path(path)
    else:
        _output_root = DEFAULT_OUTPUT_ROOT
    return _output_root


def get_output_root() -> Path:
    return _output_root


def set_output_tag(tag: Optional[str]) -> Optional[str]:
    """Define um sufixo opcional para as subpastas de cortes (testes lado a lado).

    Ex.: --output-tag smart -> live_preview_smart, ready_hd_smart, etc.
    Nao mexe em cache/ nem em fila_local.jsonl, so nas subpastas de cortes/.
    """
    global _output_tag
    _output_tag = tag.strip() if tag else None
    return _output_tag


def get_output_tag() -> Optional[str]:
    return _output_tag


def _tagged(name: str) -> str:
    return f"{name}_{_output_tag}" if _output_tag else name


def cache_dir() -> Path:
    return get_output_root() / "cache"


def cortes_dir() -> Path:
    return get_output_root() / "cortes"


def tagged_cortes_subdir(name: str) -> Path:
    return cortes_dir() / _tagged(name)


def live_preview_dir() -> Path:
    return tagged_cortes_subdir("live_preview")


def ready_hd_dir() -> Path:
    return tagged_cortes_subdir("ready_hd")


def needs_review_dir() -> Path:
    return tagged_cortes_subdir("needs_review")


def rejected_dir() -> Path:
    return tagged_cortes_subdir("rejected")


def temp_dir() -> Path:
    return cache_dir() / "tmp"


def live_blocks_dir() -> Path:
    return cache_dir() / "live_blocks"


def vod_blocks_dir() -> Path:
    return cache_dir() / "vod_blocks"


def sources_dir() -> Path:
    return cache_dir() / "sources"


def queue_file() -> Path:
    return get_output_root() / "fila_local.jsonl"


def run_logs_dir() -> Path:
    return get_output_root() / "run_logs"


def status_fallback_file() -> Path:
    return run_logs_dir() / "fila_local_status_fallback.jsonl"


def moment_fallback_file() -> Path:
    return run_logs_dir() / "fila_local_moment_fallback.jsonl"


def ensure_output_dirs() -> None:
    for path in (
        cache_dir(),
        live_blocks_dir(),
        vod_blocks_dir(),
        sources_dir(),
        temp_dir(),
        cortes_dir(),
        live_preview_dir(),
        ready_hd_dir(),
        needs_review_dir(),
        rejected_dir(),
        run_logs_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)
