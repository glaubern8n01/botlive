from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg
from yt_dlp import YoutubeDL

from clipper import CACHE_DIR, preparar_pastas
from highlight_detector import HighlightCandidate, detectar_melhores_momentos
from moment_logger import salvar_momento


VOD_BLOCKS_DIR = CACHE_DIR / "vod_blocks"


@dataclass(frozen=True)
class VodInfo:
    duration_seconds: int
    stream_url: str
    title: str


@dataclass(frozen=True)
class ScannedMoment:
    timestamp_seconds: int
    score: float
    reason: str
    block_index: int
    block_file: str
    candidate: HighlightCandidate


def resolver_vod_para_scan(source_url: str) -> VodInfo:
    ydl_opts = {
        "format": "18/best[height<=480][ext=mp4][acodec!=none][vcodec!=none]/best[height<=480]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source_url, download=False)

    direct_url = info.get("url")
    if not direct_url:
        formats = info.get("formats") or []
        for fmt in reversed(formats):
            if fmt.get("url") and fmt.get("vcodec") != "none" and fmt.get("acodec") != "none":
                direct_url = fmt["url"]
                break

    if not direct_url:
        raise RuntimeError("Nao consegui resolver URL direta progressiva para scan do VOD.")

    return VodInfo(
        duration_seconds=int(info.get("duration") or 0),
        stream_url=str(direct_url),
        title=str(info.get("title") or ""),
    )


def capturar_bloco_vod(
    stream_url: str,
    session_id: str,
    block_index: int,
    start_seconds: int,
    block_seconds: int,
) -> Optional[Path]:
    preparar_pastas()
    session_dir = VOD_BLOCKS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    output_path = session_dir / f"vod_block_{block_index:06d}_{start_seconds:06d}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start_seconds),
        "-i",
        stream_url,
        "-t",
        str(block_seconds),
        "-c",
        "copy",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=block_seconds + 90,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            print(f"[scan-vod] bloco {block_index} falhou: {stderr[-500:]}")
            return None
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
    except Exception as exc:
        print(f"[scan-vod] bloco {block_index} falhou: {exc}")
    return None


def _selecionar_melhores(
    moments: list[ScannedMoment],
    max_cortes: int,
    min_gap_seconds: int,
) -> tuple[list[ScannedMoment], int]:
    ranked = sorted(moments, key=lambda item: item.score, reverse=True)
    selected: list[ScannedMoment] = []
    ignored = 0
    for moment in ranked:
        duplicate = any(
            abs(moment.timestamp_seconds - kept.timestamp_seconds) < min_gap_seconds
            for kept in selected
        )
        if duplicate:
            ignored += 1
            print(f"[scan-vod] ignorado por proximidade: {moment.timestamp_seconds}s score={moment.score}")
            continue
        selected.append(moment)
        if len(selected) >= max_cortes:
            break
    return sorted(selected, key=lambda item: item.timestamp_seconds), ignored


def scan_vod_completo(
    source_url: str,
    session_id: str,
    block_seconds: int = 45,
    max_cortes: int = 25,
    score_threshold: float = 0.55,
    min_gap_seconds: int = 120,
    sample_every_seconds: int = 3,
    analysis_window_seconds: int = 6,
    max_blocks: Optional[int] = None,
) -> list[ScannedMoment]:
    if block_seconds < 30 or block_seconds > 60:
        raise ValueError("--block-seconds deve ficar entre 30 e 60 segundos.")

    print("[scan-vod] resolvendo VOD com yt-dlp...")
    vod = resolver_vod_para_scan(source_url)
    if vod.duration_seconds <= 0:
        raise RuntimeError("Nao consegui detectar duracao do VOD.")

    total_blocks = (vod.duration_seconds + block_seconds - 1) // block_seconds
    if max_blocks is not None:
        total_blocks = min(total_blocks, max_blocks)

    print(f"[scan-vod] titulo: {vod.title}")
    print(f"[scan-vod] duracao total: {vod.duration_seconds}s")
    print(f"[scan-vod] blocos planejados: {total_blocks} de {block_seconds}s")

    all_candidates: list[ScannedMoment] = []
    for block_index in range(total_blocks):
        start = block_index * block_seconds
        current_duration = min(block_seconds, max(1, vod.duration_seconds - start))
        print(f"[scan-vod] bloco {block_index + 1}/{total_blocks} inicio={start}s duracao={current_duration}s")

        block_path = capturar_bloco_vod(
            stream_url=vod.stream_url,
            session_id=session_id,
            block_index=block_index,
            start_seconds=start,
            block_seconds=current_duration,
        )
        if block_path is None:
            continue

        candidates = detectar_melhores_momentos(
            video_path=block_path,
            max_cortes=1,
            sample_every_seconds=sample_every_seconds,
            analysis_window_seconds=analysis_window_seconds,
            min_gap_seconds=max(10, block_seconds // 2),
            ignore_first_seconds=0,
            min_score=score_threshold,
        )
        if not candidates:
            print("[scan-vod] bloco sem momento acima do threshold")
            continue

        candidate = candidates[0]
        global_timestamp = start + candidate.timestamp_seconds
        scanned = ScannedMoment(
            timestamp_seconds=global_timestamp,
            score=candidate.score,
            reason=candidate.reason,
            block_index=block_index,
            block_file=str(block_path),
            candidate=candidate,
        )
        all_candidates.append(scanned)
        print(
            f"[scan-vod] candidato: timestamp={global_timestamp}s "
            f"score={candidate.score} motivo={candidate.reason}"
        )

    selected, ignored = _selecionar_melhores(
        all_candidates,
        max_cortes=max_cortes,
        min_gap_seconds=min_gap_seconds,
    )

    print(f"[scan-vod] candidatos encontrados: {len(all_candidates)}")
    print(f"[scan-vod] ignorados por duplicidade/proximidade: {ignored}")
    print(f"[scan-vod] selecionados: {len(selected)}")

    for moment in selected:
        record = salvar_momento(
            source_url=source_url,
            timestamp_seconds=moment.timestamp_seconds,
            score=moment.score,
            reason=moment.reason,
            session_id=session_id,
            block_index=moment.block_index,
            block_file=moment.block_file,
            metadata={
                "mode": "scan_vod",
                "block_timestamp_seconds": moment.candidate.timestamp_seconds,
                "audio_score": moment.candidate.audio_score,
                "motion_score": moment.candidate.motion_score,
                "brightness_score": moment.candidate.brightness_score,
                "block_seconds": block_seconds,
                "min_gap_seconds": min_gap_seconds,
                "duration_seconds": vod.duration_seconds,
            },
        )
        print(f"[scan-vod] salvo {record.id}: {moment.timestamp_seconds}s score={moment.score}")

    return selected
