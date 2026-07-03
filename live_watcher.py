from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import imageio_ffmpeg
from clipper import OutputLayout, criar_preview_de_arquivo, validar_video_final
from football_content_filter import FootballContentResult, classify_football_content
from highlight_detector import detectar_melhores_momentos
from live_buffer import LiveBlock, capturar_bloco
from moment_logger import salvar_momento, salvar_preview_evento, source_id_from_url
from runtime_paths import temp_dir
from smart_window import calculate_smart_event_window, smart_window_metadata


@dataclass
class PendingPreview:
    moment_id: str
    timestamp_seconds: int
    event_start_seconds: int
    event_end_seconds: int
    block_timestamp_seconds: int
    score: float
    reason: str
    event_type: str
    metadata: dict
    previous_event_seconds: Optional[int] = None


@dataclass(frozen=True)
class NearLiveResult:
    saved_ids: list[str]
    preview_paths: list[Path]


def _new_session_id(source_url: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{source_id_from_url(source_url)}_{stamp}"


def monitorar_live(
    source_url: str,
    block_seconds: int = 45,
    max_cortes: int = 8,
    session_id: Optional[str] = None,
    score_threshold: float = 0.62,
    sample_every_seconds: int = 3,
    analysis_window_seconds: int = 6,
    max_failures: int = 3,
    max_blocks: Optional[int] = None,
) -> list[str]:
    if block_seconds < 30 or block_seconds > 60:
        raise ValueError("--block-seconds deve ficar entre 30 e 60 segundos.")

    session_id = session_id or _new_session_id(source_url)
    print(f"[live] Sessao: {session_id}")
    print(f"[live] Capturando blocos de {block_seconds}s sem usar chat.")

    saved_ids: list[str] = []
    failures = 0
    block_index = 0
    start_offset = 0

    while len(saved_ids) < max_cortes:
        if max_blocks is not None and block_index >= max_blocks:
            print("[live] Limite de blocos atingido.")
            break

        print(f"[live] Capturando bloco #{block_index} offset={start_offset}s...")
        block = capturar_bloco(
            source_url=source_url,
            session_id=session_id,
            block_index=block_index,
            start_offset_seconds=start_offset,
            block_seconds=block_seconds,
        )

        if block is None:
            failures += 1
            if failures >= max_failures:
                print("[live] Muitas falhas seguidas. Encerrando monitoramento.")
                break
            block_index += 1
            start_offset += block_seconds
            continue

        failures = 0
        candidates = detectar_melhores_momentos(
            video_path=block.path,
            max_cortes=1,
            sample_every_seconds=sample_every_seconds,
            analysis_window_seconds=analysis_window_seconds,
            min_gap_seconds=max(10, block_seconds // 2),
            ignore_first_seconds=0,
            min_score=score_threshold,
        )

        if not candidates:
            print(f"[live] Bloco #{block_index}: nenhum momento acima do threshold {score_threshold}.")
        else:
            for candidate in candidates:
                global_timestamp = block.start_offset_seconds + candidate.timestamp_seconds
                print(
                    f"[detector] score={candidate.score} "
                    f"timestamp_bloco={candidate.timestamp_seconds}s "
                    f"timestamp_live={global_timestamp}s"
                )
                record = salvar_momento(
                    source_url=source_url,
                    timestamp_seconds=global_timestamp,
                    score=candidate.score,
                    reason=candidate.reason,
                    session_id=session_id,
                    block_index=block.block_index,
                    block_file=str(block.path),
                    metadata={
                        "mode": "live",
                        "block_timestamp_seconds": candidate.timestamp_seconds,
                        "audio_score": candidate.audio_score,
                        "motion_score": candidate.motion_score,
                        "brightness_score": candidate.brightness_score,
                    },
                )
                saved_ids.append(record.id)
                print(
                    f"[momento] salvo {record.id}: "
                    f"{global_timestamp}s score={candidate.score} motivo={candidate.reason}"
                )
                print(f"[status] {len(saved_ids)}/{max_cortes} momentos detectados")
                if len(saved_ids) >= max_cortes:
                    break

        block_index += 1
        start_offset += block_seconds

    print(f"[live] Finalizado. Momentos salvos: {len(saved_ids)}")
    return saved_ids


def _football_metadata(
    block_path: Path,
    candidate,
    content_filter: str,
    strict_football_filter: bool,
) -> tuple[bool, str, dict]:
    if content_filter != "football":
        return True, "highlight", {
            "content_filter": content_filter,
            "event_type": "highlight",
            "football_action": "save_ready",
        }

    result: FootballContentResult = classify_football_content(
        block_path,
        strict=strict_football_filter,
        score_base=candidate.score,
        audio_score=candidate.audio_score,
        candidate_motion_score=candidate.motion_score,
        visual_change_score=candidate.brightness_score,
    )
    metadata = {
        "content_filter": "football",
        "event_type": result.content_type,
        "football_label": result.content_type,
        "football_action": result.action,
        "football_score": result.football_confidence,
        "football_reason": result.reason,
        "football_emotion_score": result.emotion_score,
        "football_penalty_score": result.penalty_score,
        "football_interview_penalty": result.interview_penalty,
        "football_studio_penalty": result.studio_penalty,
        "football_static_penalty": result.static_penalty,
    }
    print(
        "[near-live][football] "
        f"type={result.content_type} action={result.action} "
        f"score={result.score_final} reason={result.reason}"
    )
    return result.action != "reject", result.content_type, metadata


def _window_blocks(blocks: list[LiveBlock], start_seconds: int, end_seconds: int) -> list[LiveBlock]:
    selected = [
        block
        for block in blocks
        if block.start_offset_seconds < end_seconds
        and (block.start_offset_seconds + block.duration_seconds) > start_seconds
    ]
    return sorted(selected, key=lambda item: item.start_offset_seconds)


def _can_render_preview(
    blocks: list[LiveBlock],
    pending: PendingPreview,
    allow_partial: bool = False,
    lookahead_seconds: int = 0,
) -> bool:
    if not blocks:
        return False
    available_start = min(block.start_offset_seconds for block in blocks)
    available_end = max(block.start_offset_seconds + block.duration_seconds for block in blocks)
    if pending.event_start_seconds < available_start:
        return False
    if allow_partial:
        return True
    # Espera capturar um pouco alem do post-roll antes de renderizar, para dar
    # chance de detectar um evento vizinho e encurtar a janela (anti multi-lance).
    required_end = pending.event_end_seconds + max(0, lookahead_seconds)
    return available_end >= required_end


def _concat_blocks(blocks: list[LiveBlock]) -> Optional[Path]:
    if not blocks:
        return None
    temp_dir().mkdir(parents=True, exist_ok=True)
    concat_id = uuid4().hex
    list_path = temp_dir() / f"near_live_blocks_{concat_id}.txt"
    concat_path = temp_dir() / f"near_live_range_{concat_id}.mp4"
    # Caminho absoluto: o demuxer concat resolve caminhos relativos a partir
    # da pasta da PROPRIA lista, quebrando com --output-root relativo.
    list_path.write_text(
        "\n".join(f"file '{block.path.resolve().as_posix()}'" for block in blocks) + "\n",
        encoding="utf-8",
    )
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(concat_path),
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    finally:
        list_path.unlink(missing_ok=True)
    if result.returncode != 0:
        print(f"[near-live][falha] concat blocos: {(result.stderr or '').strip()[-500:]}")
        return None
    return concat_path


def _renderizar_preview(
    source_url: str,
    session_id: str,
    blocks: list[LiveBlock],
    pending: PendingPreview,
    output_layout: OutputLayout,
) -> Optional[Path]:
    selected = _window_blocks(blocks, pending.event_start_seconds, pending.event_end_seconds)
    concat_path = _concat_blocks(selected)
    if concat_path is None:
        salvar_preview_evento(
            moment_id=pending.moment_id,
            session_id=session_id,
            source_url=source_url,
            timestamp_seconds=pending.timestamp_seconds,
            preview_path=None,
            status="preview_error",
            metadata={**pending.metadata, "error": "concat_failed"},
        )
        return None

    try:
        concat_start = selected[0].start_offset_seconds
        adjusted_peak = max(0, int(pending.timestamp_seconds) - concat_start)
        # Usa a janela real do pending (pode ter sido encurtada pelo smart-window),
        # nunca os valores fixos de pre/post-roll da sessao inteira.
        seconds_before = max(0, int(pending.timestamp_seconds) - int(pending.event_start_seconds))
        seconds_after = max(1, int(pending.event_end_seconds) - int(pending.timestamp_seconds))
        preview_id = f"{session_id}_{pending.timestamp_seconds}_{uuid4().hex[:8]}"
        preview_path = criar_preview_de_arquivo(
            input_video_path=concat_path,
            peak_timestamp=adjusted_peak,
            preview_id=preview_id,
            seconds_before=seconds_before,
            seconds_after=seconds_after,
            output_layout=output_layout,
        )
        validation = validar_video_final(preview_path, require_audio=False)
        status = "preview_ready" if validation.valid else "preview_invalid"
        salvar_preview_evento(
            moment_id=pending.moment_id,
            session_id=session_id,
            source_url=source_url,
            timestamp_seconds=pending.timestamp_seconds,
            preview_path=str(preview_path),
            status=status,
            metadata={
                **pending.metadata,
                "event_start_seconds": pending.event_start_seconds,
                "event_peak_seconds": pending.timestamp_seconds,
                "event_end_seconds": pending.event_end_seconds,
                "validation_reason": validation.reason,
                "duration_seconds": validation.duration_seconds,
                "width": validation.width,
                "height": validation.height,
                "has_audio": validation.has_audio,
            },
        )
        if validation.valid:
            print(
                f"[near-live][ok] preview {preview_path} | "
                f"{validation.width}x{validation.height} | {validation.duration_seconds:.1f}s"
            )
            return preview_path
        print(f"[near-live][falha] preview invalido: {validation.reason}")
        preview_path.unlink(missing_ok=True)
        return None
    except Exception as exc:
        salvar_preview_evento(
            moment_id=pending.moment_id,
            session_id=session_id,
            source_url=source_url,
            timestamp_seconds=pending.timestamp_seconds,
            preview_path=None,
            status="preview_error",
            metadata={**pending.metadata, "error": str(exc)},
        )
        print(f"[near-live][falha] render preview timestamp={pending.timestamp_seconds}s motivo={exc}")
        return None
    finally:
        concat_path.unlink(missing_ok=True)


def _tentar_renderizar_pendentes(
    source_url: str,
    session_id: str,
    blocks: list[LiveBlock],
    pending: list[PendingPreview],
    output_layout: OutputLayout,
    max_previews: int,
    preview_paths: list[Path],
    allow_partial: bool = False,
    lookahead_seconds: int = 0,
) -> list[PendingPreview]:
    remaining: list[PendingPreview] = []
    for item in pending:
        if len(preview_paths) >= max_previews:
            remaining.append(item)
            continue
        if not _can_render_preview(blocks, item, allow_partial=allow_partial, lookahead_seconds=lookahead_seconds):
            remaining.append(item)
            continue
        preview_path = _renderizar_preview(
            source_url=source_url,
            session_id=session_id,
            blocks=blocks,
            pending=item,
            output_layout=output_layout,
        )
        if preview_path is not None:
            preview_paths.append(preview_path)
    return remaining


def monitorar_near_live(
    source_url: str,
    block_seconds: int = 45,
    max_cortes: int = 8,
    session_id: Optional[str] = None,
    score_threshold: float = 0.62,
    sample_every_seconds: int = 3,
    analysis_window_seconds: int = 6,
    max_failures: int = 3,
    max_blocks: Optional[int] = None,
    pre_roll_seconds: Optional[int] = None,
    post_roll_seconds: Optional[int] = None,
    output_layout: OutputLayout = "original",
    content_filter: str = "none",
    strict_football_filter: bool = False,
    smart_event_window: bool = False,
    no_multi_event_clips: bool = False,
    max_clip_duration: int = 50,
    min_event_separation: int = 8,
) -> NearLiveResult:
    if block_seconds < 30 or block_seconds > 60:
        raise ValueError("--block-seconds deve ficar entre 30 e 60 segundos.")

    pre_roll = 12 if pre_roll_seconds is None else max(0, int(pre_roll_seconds))
    post_roll = 33 if post_roll_seconds is None else max(1, int(post_roll_seconds))
    use_smart_window = smart_event_window or no_multi_event_clips
    lookahead_seconds = min_event_separation if use_smart_window else 0
    session_id = session_id or _new_session_id(source_url)
    print(f"[near-live] Sessao: {session_id}")
    print(f"[near-live] Capturando blocos de {block_seconds}s e gerando previews.")
    if use_smart_window:
        print(
            f"[near-live] Janela inteligente ativa (smart_event_window={smart_event_window}, "
            f"no_multi_event_clips={no_multi_event_clips}, max_clip_duration={max_clip_duration}s, "
            f"min_event_separation={min_event_separation}s)."
        )

    saved_ids: list[str] = []
    preview_paths: list[Path] = []
    pending: list[PendingPreview] = []
    blocks: list[LiveBlock] = []
    failures = 0
    analysis_failures = 0
    block_index = 0
    start_offset = 0
    last_event_timestamp: Optional[int] = None

    while len(preview_paths) < max_cortes:
        if max_blocks is not None and block_index >= max_blocks:
            print("[near-live] Limite de blocos atingido.")
            break

        print(f"[near-live] Capturando bloco #{block_index} offset={start_offset}s...")
        block = capturar_bloco(
            source_url=source_url,
            session_id=session_id,
            block_index=block_index,
            start_offset_seconds=start_offset,
            block_seconds=block_seconds,
        )

        if block is None:
            failures += 1
            if failures >= max_failures:
                print("[near-live] Muitas falhas seguidas. Encerrando monitoramento.")
                break
            block_index += 1
            start_offset += block_seconds
            continue

        failures = 0
        blocks.append(block)

        if len(saved_ids) < max_cortes:
            try:
                candidates = detectar_melhores_momentos(
                    video_path=block.path,
                    max_cortes=1,
                    sample_every_seconds=sample_every_seconds,
                    analysis_window_seconds=analysis_window_seconds,
                    min_gap_seconds=max(10, block_seconds // 2),
                    ignore_first_seconds=0,
                    min_score=score_threshold,
                )
            except Exception as exc:
                analysis_failures += 1
                print(f"[near-live][falha] bloco invalido para analise: {block.path} | motivo={exc}")
                if analysis_failures >= max_failures:
                    print("[near-live] Muitas falhas seguidas na analise. Encerrando monitoramento.")
                    break
                block_index += 1
                start_offset += block_seconds
                continue
            analysis_failures = 0

            if not candidates:
                print(f"[near-live] Bloco #{block_index}: nenhum momento acima do threshold {score_threshold}.")
            for candidate in candidates:
                global_timestamp = block.start_offset_seconds + candidate.timestamp_seconds
                keep, event_type, filter_metadata = _football_metadata(
                    block.path,
                    candidate,
                    content_filter=content_filter,
                    strict_football_filter=strict_football_filter,
                )
                if not keep:
                    print(f"[near-live] timestamp rejeitado pelo filtro: {global_timestamp}s")
                    continue

                smart_metadata: dict = {}
                if use_smart_window:
                    window = calculate_smart_event_window(
                        event_peak_seconds=global_timestamp,
                        event_type=event_type if smart_event_window else None,
                        previous_event_seconds=last_event_timestamp,
                        next_event_seconds=None,
                        pre_roll_seconds=pre_roll,
                        post_roll_seconds=post_roll,
                        max_clip_duration=max_clip_duration,
                        min_event_separation=min_event_separation,
                    )
                    event_start = window.start_seconds
                    event_end = window.end_seconds
                    smart_metadata = smart_window_metadata(window)
                    # Evento novo pode invadir a janela de um pendente anterior:
                    # encurta o anterior em vez de deixar dois lances no mesmo mp4.
                    for earlier in pending:
                        if earlier.timestamp_seconds >= global_timestamp:
                            continue
                        if earlier.event_end_seconds <= global_timestamp - min_event_separation:
                            continue
                        shrunk = calculate_smart_event_window(
                            event_peak_seconds=earlier.timestamp_seconds,
                            event_type=earlier.event_type if smart_event_window else None,
                            previous_event_seconds=earlier.previous_event_seconds,
                            next_event_seconds=global_timestamp,
                            pre_roll_seconds=pre_roll,
                            post_roll_seconds=post_roll,
                            max_clip_duration=max_clip_duration,
                            min_event_separation=min_event_separation,
                        )
                        earlier.event_start_seconds = shrunk.start_seconds
                        earlier.event_end_seconds = shrunk.end_seconds
                        earlier.metadata.update(smart_window_metadata(shrunk))
                        earlier.metadata["event_start_seconds"] = shrunk.start_seconds
                        earlier.metadata["event_end_seconds"] = shrunk.end_seconds
                        print(
                            f"[near-live][smart-window] evento {earlier.timestamp_seconds}s encurtado "
                            f"para {shrunk.start_seconds}-{shrunk.end_seconds}s (novo evento em {global_timestamp}s)"
                        )
                else:
                    event_start = max(0, int(global_timestamp) - pre_roll)
                    event_end = int(global_timestamp) + post_roll

                metadata = {
                    "mode": "near_live",
                    "block_timestamp_seconds": candidate.timestamp_seconds,
                    "audio_score": candidate.audio_score,
                    "motion_score": candidate.motion_score,
                    "brightness_score": candidate.brightness_score,
                    "event_type": event_type,
                    "event_start_seconds": event_start,
                    "event_peak_seconds": int(global_timestamp),
                    "event_end_seconds": event_end,
                    "preview_status": "pending",
                    "render_source": "live_preview",
                    "block_seconds": block_seconds,
                    **filter_metadata,
                    **smart_metadata,
                }
                record = salvar_momento(
                    source_url=source_url,
                    timestamp_seconds=global_timestamp,
                    score=candidate.score,
                    reason=candidate.reason,
                    session_id=session_id,
                    block_index=block.block_index,
                    block_file=str(block.path),
                    metadata=metadata,
                )
                saved_ids.append(record.id)
                pending.append(
                    PendingPreview(
                        moment_id=record.id,
                        timestamp_seconds=int(global_timestamp),
                        event_start_seconds=event_start,
                        event_end_seconds=event_end,
                        block_timestamp_seconds=candidate.timestamp_seconds,
                        score=candidate.score,
                        reason=candidate.reason,
                        event_type=event_type,
                        metadata=metadata,
                        previous_event_seconds=last_event_timestamp,
                    )
                )
                last_event_timestamp = int(global_timestamp)
                print(
                    f"[near-live][momento] salvo {record.id}: "
                    f"{global_timestamp}s event_type={event_type} score={candidate.score}"
                )
                if len(saved_ids) >= max_cortes:
                    break

        pending = _tentar_renderizar_pendentes(
            source_url=source_url,
            session_id=session_id,
            blocks=blocks,
            pending=pending,
            output_layout=output_layout,
            max_previews=max_cortes,
            preview_paths=preview_paths,
            lookahead_seconds=lookahead_seconds,
        )

        retention_margin = pre_roll + post_roll + block_seconds
        if use_smart_window:
            retention_margin = max(retention_margin, max_clip_duration + lookahead_seconds + block_seconds)
        keep_after = max(0, start_offset - retention_margin)
        blocks = [item for item in blocks if (item.start_offset_seconds + item.duration_seconds) >= keep_after]
        block_index += 1
        start_offset += block_seconds

    if pending and len(preview_paths) < max_cortes:
        pending = _tentar_renderizar_pendentes(
            source_url=source_url,
            session_id=session_id,
            blocks=blocks,
            pending=pending,
            output_layout=output_layout,
            max_previews=max_cortes,
            preview_paths=preview_paths,
            allow_partial=True,
        )

    print(
        f"[near-live] Finalizado. Momentos salvos: {len(saved_ids)} | "
        f"previews validos: {len(preview_paths)} | pendentes: {len(pending)}"
    )
    return NearLiveResult(saved_ids=saved_ids, preview_paths=preview_paths)
