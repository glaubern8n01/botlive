from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg
import numpy as np
from PIL import Image
from yt_dlp import YoutubeDL

try:
    from moviepy.editor import VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import VideoFileClip

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
    football_score: float = 0.0
    football_label: str = "nao_avaliado"
    football_reason: str = ""


@dataclass(frozen=True)
class FootballFilterResult:
    is_game: bool
    score: float
    label: str
    green_ratio: float
    motion_grid_ratio: float
    brightness: float
    contrast: float
    reason: str


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


def _green_ratio(frame: np.ndarray) -> float:
    arr = frame.astype(np.float32)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    max_channel = np.max(arr, axis=2)
    min_channel = np.min(arr, axis=2)
    saturation = max_channel - min_channel
    green_mask = (
        (green > 45)
        & (green > red * 1.08)
        & (green > blue * 1.04)
        & (saturation > 18)
    )
    return float(np.mean(green_mask))


def _motion_grid_ratio(previous_gray: np.ndarray, current_gray: np.ndarray) -> float:
    diff = np.abs(current_gray - previous_gray)
    rows, cols = 6, 8
    active = 0
    total = rows * cols
    height, width = diff.shape
    for row in range(rows):
        for col in range(cols):
            y0 = row * height // rows
            y1 = (row + 1) * height // rows
            x0 = col * width // cols
            x1 = (col + 1) * width // cols
            if float(np.mean(diff[y0:y1, x0:x1])) > 0.035:
                active += 1
    return active / total


def avaliar_bloco_futebol(block_path: Path) -> FootballFilterResult:
    clip = VideoFileClip(str(block_path))
    try:
        duration = float(clip.duration or 0)
        if duration <= 1:
            return FootballFilterResult(False, 0.0, "nao-jogo", 0.0, 0.0, 0.0, 0.0, "duracao muito curta")

        sample_count = min(8, max(4, int(duration // 8) + 1))
        timestamps = np.linspace(0.5, max(0.5, duration - 0.5), sample_count)
        green_values: list[float] = []
        brightness_values: list[float] = []
        contrast_values: list[float] = []
        motion_values: list[float] = []
        previous_gray: Optional[np.ndarray] = None

        for timestamp in timestamps:
            frame = clip.get_frame(float(timestamp))
            image = Image.fromarray(frame).resize((160, 90))
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
            gray = np.asarray(image.convert("L"), dtype=np.float32) / 255.0

            green_values.append(_green_ratio(rgb))
            brightness_values.append(float(np.mean(gray)))
            contrast_values.append(float(np.std(gray)))
            if previous_gray is not None:
                motion_values.append(_motion_grid_ratio(previous_gray, gray))
            previous_gray = gray

        green_ratio = float(np.mean(green_values))
        motion_grid_ratio = float(np.mean(motion_values)) if motion_values else 0.0
        brightness = float(np.mean(brightness_values))
        contrast = float(np.mean(contrast_values))

        if brightness < 0.05 or contrast < 0.015:
            return FootballFilterResult(
                False,
                0.0,
                "nao-jogo",
                round(green_ratio, 4),
                round(motion_grid_ratio, 4),
                round(brightness, 4),
                round(contrast, 4),
                "imagem escura/parada",
            )

        score = min(1.0, (green_ratio / 0.18) * 0.70 + min(1.0, motion_grid_ratio / 0.22) * 0.30)
        is_game = green_ratio >= 0.08 and motion_grid_ratio >= 0.05
        if green_ratio >= 0.14:
            is_game = True
        label = "jogo" if is_game else "nao-jogo"
        reason = (
            f"{label}: verde={green_ratio:.3f} "
            f"movimento_tela={motion_grid_ratio:.3f} brilho={brightness:.3f} contraste={contrast:.3f}"
        )
        return FootballFilterResult(
            is_game=is_game,
            score=round(float(score), 4),
            label=label,
            green_ratio=round(green_ratio, 4),
            motion_grid_ratio=round(motion_grid_ratio, 4),
            brightness=round(brightness, 4),
            contrast=round(contrast, 4),
            reason=reason,
        )
    except Exception as exc:
        return FootballFilterResult(False, 0.0, "nao-jogo", 0.0, 0.0, 0.0, 0.0, f"falha filtro futebol: {exc}")
    finally:
        clip.close()


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
    content_filter: str = "none",
    focus_final_minutes: Optional[int] = None,
    start_seconds: Optional[int] = None,
    end_seconds: Optional[int] = None,
    max_scan_blocks: Optional[int] = None,
) -> list[ScannedMoment]:
    if block_seconds < 30 or block_seconds > 60:
        raise ValueError("--block-seconds deve ficar entre 30 e 60 segundos.")
    if content_filter not in {"none", "football"}:
        raise ValueError("--content-filter deve ser none ou football.")
    if focus_final_minutes is not None and focus_final_minutes <= 0:
        raise ValueError("--focus-final-minutes deve ser maior que zero.")
    if start_seconds is not None and start_seconds < 0:
        raise ValueError("--start-seconds nao pode ser negativo.")
    if end_seconds is not None and end_seconds <= 0:
        raise ValueError("--end-seconds deve ser maior que zero.")
    if max_scan_blocks is not None and max_scan_blocks <= 0:
        raise ValueError("--max-scan-blocks deve ser maior que zero.")

    print("[scan-vod] resolvendo VOD com yt-dlp...")
    vod = resolver_vod_para_scan(source_url)
    if vod.duration_seconds <= 0:
        raise RuntimeError("Nao consegui detectar duracao do VOD.")

    scan_start = 0
    scan_end = vod.duration_seconds
    if focus_final_minutes:
        scan_start = max(0, vod.duration_seconds - (focus_final_minutes * 60))
    if start_seconds is not None:
        scan_start = min(start_seconds, vod.duration_seconds)
    if end_seconds is not None:
        scan_end = min(end_seconds, vod.duration_seconds)
    if scan_end <= scan_start:
        raise ValueError(f"Janela de scan invalida: inicio={scan_start}s fim={scan_end}s")

    scan_duration = max(0, scan_end - scan_start)
    total_blocks = (scan_duration + block_seconds - 1) // block_seconds
    effective_max_blocks = max_scan_blocks if max_scan_blocks is not None else max_blocks
    if effective_max_blocks is not None:
        total_blocks = min(total_blocks, effective_max_blocks)

    print(f"[scan-vod] titulo: {vod.title}")
    print(f"[scan-vod] duracao total: {vod.duration_seconds}s")
    if focus_final_minutes:
        print(f"[scan-vod] foco final: ultimos {focus_final_minutes}min inicio={scan_start}s")
    print(f"[scan-vod] inicio analise: {scan_start}s")
    print(f"[scan-vod] fim analise: {scan_end}s")
    print(f"[scan-vod] filtro conteudo: {content_filter}")
    if effective_max_blocks is not None:
        print(f"[scan-vod] limite de blocos: {effective_max_blocks}")
    print(f"[scan-vod] blocos planejados: {total_blocks} de {block_seconds}s")

    all_candidates: list[ScannedMoment] = []
    captured_blocks = 0
    game_blocks = 0
    non_game_blocks = 0
    failed_blocks = 0
    for block_index in range(total_blocks):
        start = scan_start + (block_index * block_seconds)
        current_duration = min(block_seconds, max(1, scan_end - start))
        print(f"[scan-vod] bloco {block_index + 1}/{total_blocks} inicio={start}s duracao={current_duration}s")

        block_path = capturar_bloco_vod(
            stream_url=vod.stream_url,
            session_id=session_id,
            block_index=block_index,
            start_seconds=start,
            block_seconds=current_duration,
        )
        if block_path is None:
            failed_blocks += 1
            continue
        captured_blocks += 1

        football_result = FootballFilterResult(
            True,
            1.0,
            "nao_avaliado",
            0.0,
            0.0,
            0.0,
            0.0,
            "sem filtro de conteudo",
        )
        if content_filter == "football":
            football_result = avaliar_bloco_futebol(block_path)
            if football_result.is_game:
                game_blocks += 1
            else:
                non_game_blocks += 1
                print(f"[scan-vod] bloco ignorado pelo filtro football: {football_result.reason}")
                continue
            print(f"[scan-vod] filtro football: {football_result.reason}")

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
        adjusted_score = candidate.score
        reason = candidate.reason
        if content_filter == "football":
            adjusted_score = min(1.0, round(candidate.score * (0.70 + football_result.score * 0.45), 4))
            reason = f"{candidate.reason}; football={football_result.reason}"
        scanned = ScannedMoment(
            timestamp_seconds=global_timestamp,
            score=adjusted_score,
            reason=reason,
            block_index=block_index,
            block_file=str(block_path),
            candidate=candidate,
            football_score=football_result.score,
            football_label=football_result.label,
            football_reason=football_result.reason,
        )
        all_candidates.append(scanned)
        print(
            f"[scan-vod] candidato: timestamp={global_timestamp}s "
            f"score={scanned.score} motivo={scanned.reason}"
        )

    selected, ignored = _selecionar_melhores(
        all_candidates,
        max_cortes=max_cortes,
        min_gap_seconds=min_gap_seconds,
    )

    print(f"[scan-vod] candidatos encontrados: {len(all_candidates)}")
    print(f"[scan-vod] blocos capturados: {captured_blocks}")
    print(f"[scan-vod] blocos falhos: {failed_blocks}")
    if content_filter == "football":
        print(f"[scan-vod] blocos classificados como jogo: {game_blocks}")
        print(f"[scan-vod] blocos ignorados como nao-jogo: {non_game_blocks}")
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
                "content_filter": content_filter,
                "focus_final_minutes": focus_final_minutes,
                "scan_start_seconds": scan_start,
                "scan_end_seconds": scan_end,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "max_scan_blocks": max_scan_blocks,
                "football_score": moment.football_score,
                "football_label": moment.football_label,
                "football_reason": moment.football_reason,
            },
        )
        print(f"[scan-vod] salvo {record.id}: {moment.timestamp_seconds}s score={moment.score}")

    return selected
