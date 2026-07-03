from __future__ import annotations

import subprocess
from collections import Counter
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

from clipper import preparar_pastas
from football_content_filter import FootballContentResult, classify_football_content
from highlight_detector import HighlightCandidate, detectar_melhores_momentos
from moment_logger import salvar_momento
from runtime_paths import vod_blocks_dir


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
    football_action: str = "save_ready"
    football_emotion_score: float = 0.0
    football_penalty_score: float = 0.0
    football_interview_penalty: float = 0.0
    football_studio_penalty: float = 0.0
    football_static_penalty: float = 0.0


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
    session_dir = vod_blocks_dir() / session_id
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
    command_for_log = (
        f'{ffmpeg} -y -hide_banner -loglevel error -ss {start_seconds} '
        f'-i <stream_url> -t {block_seconds} -c copy "{output_path}"'
    )

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
            print(
                "[scan-vod][falha] "
                f"timestamp={start_seconds}s etapa=ffmpeg_bloco "
                f"motivo={stderr[-500:]} comando={command_for_log} continuou=sim"
            )
            return None
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
    except Exception as exc:
        print(
            "[scan-vod][falha] "
            f"timestamp={start_seconds}s etapa=ffmpeg_bloco "
            f"motivo={exc} comando={command_for_log} continuou=sim"
        )
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
    result = classify_football_content(block_path)
    return FootballFilterResult(
        is_game=result.action != "reject",
        score=result.football_confidence,
        label=result.content_type,
        green_ratio=result.green_field_ratio,
        motion_grid_ratio=result.motion_score,
        brightness=0.0,
        contrast=0.0,
        reason=result.reason,
    )


def _log_football_filter(timestamp: int, result: FootballContentResult) -> None:
    print(
        "[football-filter] "
        f"t={timestamp}s "
        f"type={result.content_type} "
        f"football={result.football_confidence} "
        f"emotion={result.emotion_score} "
        f"penalty={result.penalty_score} "
        f"interview={result.interview_penalty} "
        f"studio={result.studio_penalty} "
        f"static={result.static_penalty} "
        f"final={result.score_final} "
        f"action={result.action} "
        f"reason=\"{result.reason}\""
    )


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
    strict_football_filter: bool = False,
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
    print(f"[scan-vod] filtro football rigoroso: {strict_football_filter}")
    if effective_max_blocks is not None:
        print(f"[scan-vod] limite de blocos: {effective_max_blocks}")
    print(f"[scan-vod] blocos planejados: {total_blocks} de {block_seconds}s")

    all_candidates: list[ScannedMoment] = []
    captured_blocks = 0
    game_blocks = 0
    non_game_blocks = 0
    failed_blocks = 0
    content_type_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    candidate_action_counts: Counter[str] = Counter()
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

        football_content = FootballContentResult(
            content_type="match_action",
            football_confidence=1.0,
            interview_penalty=0.0,
            studio_penalty=0.0,
            static_penalty=0.0,
            green_field_ratio=0.0,
            motion_score=0.0,
            visual_change_score=0.0,
            emotion_score=0.0,
            penalty_score=0.0,
            scoreboard_like=False,
            score_final=1.0,
            action="save_ready",
            reason="sem filtro de conteudo",
        )
        if content_filter == "football":
            football_content = classify_football_content(
                block_path,
                strict=strict_football_filter,
            )
            content_type_counts[football_content.content_type] += 1
            action_counts[football_content.action] += 1
            _log_football_filter(start, football_content)
            # No gate por bloco os scores de energia (audio/moção do candidato)
            # ainda nao existem (= 0), entao "unknown" aqui significa apenas
            # "sem evidencia negativa" e o bloco segue para a detecção; a
            # decisao strict final acontece no nivel do candidato.
            if football_content.action == "reject" and football_content.category != "unknown":
                non_game_blocks += 1
                print(f"[scan-vod] bloco rejeitado pelo filtro football: {football_content.reason}")
                continue
            game_blocks += 1

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
            score_base = round(
                float(candidate.audio_score + candidate.motion_score + candidate.brightness_score),
                4,
            )
            football_content = classify_football_content(
                block_path,
                strict=strict_football_filter,
                score_base=candidate.score,
                audio_score=candidate.audio_score,
                candidate_motion_score=candidate.motion_score,
                visual_change_score=candidate.brightness_score,
            )
            candidate_action_counts[football_content.action] += 1
            _log_football_filter(global_timestamp, football_content)
            if football_content.action == "reject":
                non_game_blocks += 1
                print(
                    "[scan-vod] candidato rejeitado pelo filtro football: "
                    f"timestamp={global_timestamp}s reason={football_content.reason}"
                )
                continue
            # Raw (sem clamp em 1.0): senao todos os momentos aprovados empatam
            # em 1.0 e o ranking/dedupe do pos-live vira loteria.
            adjusted_score = football_content.score_final_raw
            reason = (
                f"{candidate.reason}; score_base={score_base}; "
                f"football={football_content.reason}"
            )
        scanned = ScannedMoment(
            timestamp_seconds=global_timestamp,
            score=adjusted_score,
            reason=reason,
            block_index=block_index,
            block_file=str(block_path),
            candidate=candidate,
            football_score=football_content.football_confidence,
            football_label=football_content.content_type,
            football_reason=football_content.reason,
            football_action=football_content.action,
            football_emotion_score=football_content.emotion_score,
            football_penalty_score=football_content.penalty_score,
            football_interview_penalty=football_content.interview_penalty,
            football_studio_penalty=football_content.studio_penalty,
            football_static_penalty=football_content.static_penalty,
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
        for content_type, count in sorted(content_type_counts.items()):
            print(f"[scan-vod] football content_type {content_type}: {count}")
        for action, count in sorted(action_counts.items()):
            print(f"[scan-vod] football action {action}: {count}")
        for action, count in sorted(candidate_action_counts.items()):
            print(f"[scan-vod] football candidate_action {action}: {count}")
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
                "strict_football_filter": strict_football_filter,
                "football_score": moment.football_score,
                "football_label": moment.football_label,
                "football_reason": moment.football_reason,
                "football_action": moment.football_action,
                "football_emotion_score": moment.football_emotion_score,
                "football_penalty_score": moment.football_penalty_score,
                "football_interview_penalty": moment.football_interview_penalty,
                "football_studio_penalty": moment.football_studio_penalty,
                "football_static_penalty": moment.football_static_penalty,
            },
        )
        print(f"[scan-vod] salvo {record.id}: {moment.timestamp_seconds}s score={moment.score}")

    return selected
