from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

import imageio_ffmpeg
from clipper import (
    OutputLayout,
    criar_corte_vertical,
    criar_corte_vertical_de_arquivo,
    validar_video_final,
)
from database import marcar_concluido, marcar_erro, marcar_processando, registrar_corte
from highlight_detector import HighlightCandidate, detectar_melhores_momentos
from moment_logger import MomentRecord, carregar_momentos, listar_melhores_momentos
from overlay_editor import OverlayConfig
from runtime_paths import cortes_dir, tagged_cortes_subdir, temp_dir
from smart_window import calculate_smart_event_window, smart_window_metadata
from source_downloader import resolver_fonte_video


RenderSource = Literal["auto", "vod", "cache"]


@dataclass(frozen=True)
class CorteResultado:
    corte_id: str
    output_path: Optional[Path]
    status: str
    timestamp_seconds: int
    duration_seconds: Optional[int] = None
    validation_reason: Optional[str] = None
    render_source: str = "unknown"
    fallback_used: bool = False


def _is_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "rtmp://", "m3u8://"))


def _candidate_from_moment(moment: MomentRecord, vod_offset_seconds: int = 0) -> HighlightCandidate:
    return HighlightCandidate(
        timestamp_seconds=max(0, int(moment.timestamp_seconds) + int(vod_offset_seconds)),
        score=moment.score,
        audio_score=float((moment.metadata or {}).get("audio_score", 0.0)),
        motion_score=float((moment.metadata or {}).get("motion_score", 0.0)),
        brightness_score=float((moment.metadata or {}).get("brightness_score", 0.0)),
        reason=moment.reason or "timestamp salvo",
    )


def _registrar_e_renderizar(
    source: str,
    video_path: Optional[Path],
    candidate: HighlightCandidate,
    overlay_config: Optional[OverlayConfig] = None,
    clip_duration: int = 60,
    pre_roll_seconds: Optional[int] = None,
    post_roll_seconds: Optional[int] = None,
    usar_download_trecho: bool = False,
    output_layout: OutputLayout = "original",
    keep_intermediate: bool = False,
    review_action: Optional[str] = None,
    football_metadata: Optional[dict] = None,
    target_height: Optional[int] = None,
    render_source: RenderSource = "auto",
    smart_seconds_before: Optional[int] = None,
    smart_seconds_after: Optional[int] = None,
    smart_metadata: Optional[dict] = None,
    publish_config: Optional[object] = None,
) -> CorteResultado:
    if smart_seconds_before is not None and smart_seconds_after is not None:
        seconds_before = max(0, int(smart_seconds_before))
        seconds_after = max(1, int(smart_seconds_after))
    else:
        seconds_before = max(0, int(pre_roll_seconds)) if pre_roll_seconds is not None else max(1, clip_duration // 2)
        seconds_after = (
            max(1, int(post_roll_seconds))
            if post_roll_seconds is not None
            else max(1, int(clip_duration) - seconds_before)
        )
    metadata = {
        "mode": "post_live",
        "score": candidate.score,
        "audio_score": candidate.audio_score,
        "motion_score": candidate.motion_score,
        "brightness_score": candidate.brightness_score,
        "reason": candidate.reason,
        "source_file": str(video_path) if video_path else None,
        "clip_duration": clip_duration,
        "pre_roll_seconds": seconds_before,
        "post_roll_seconds": seconds_after,
        "download_mode": "trecho" if usar_download_trecho else "arquivo_completo",
        "output_layout": output_layout,
        "target_height": target_height,
        "render_source_requested": render_source,
    }
    if review_action:
        metadata["review_action"] = review_action
    if football_metadata:
        metadata["football"] = football_metadata
    if smart_metadata:
        metadata["smart_window"] = smart_metadata

    corte = registrar_corte(
        live_url=source,
        peak_timestamp=candidate.timestamp_seconds,
        keywords=["video_audio_detector"],
        messages_per_minute=None,
        status="pendente",
        metadata=metadata,
    )

    corte_id = str(corte["id"])
    print(
        f"[fila] Corte {corte_id} registrado | "
        f"timestamp={candidate.timestamp_seconds}s | score={candidate.score} | {candidate.reason}"
    )

    try:
        marcar_processando(corte_id)
        cache_video_path: Optional[Path] = None
        source_render = bool(
            usar_download_trecho
            and render_source != "cache"
            and (render_source == "vod" or target_height is not None)
        )
        actual_render_source = "vod_original" if source_render else "bloco_local"
        fallback_used = False
        if usar_download_trecho and not source_render:
            cached_video, cached_candidate, cache_video_path = _preparar_video_cache_para_corte(
                candidate=candidate,
                seconds_before=seconds_before,
                seconds_after=seconds_after,
                football_metadata=football_metadata,
            )
            if cached_video is not None:
                video_path = cached_video
                candidate = cached_candidate
                usar_download_trecho = False
        require_audio = bool(usar_download_trecho or (video_path and _video_path_tem_audio(video_path)))
        try:
            output_path, validation = _renderizar_validando(
                source=source,
                video_path=video_path,
                candidate=candidate,
                clip_id=corte_id,
                seconds_before=seconds_before,
                seconds_after=seconds_after,
                overlay_config=overlay_config,
                usar_download_trecho=usar_download_trecho,
                output_layout=output_layout,
                keep_intermediate=keep_intermediate,
                require_audio=require_audio,
                target_height=target_height,
            )
        except Exception as source_exc:
            if not source_render:
                raise
            print(
                "[pos-live][fallback] "
                f"timestamp={candidate.timestamp_seconds}s fonte=vod_original falhou={source_exc} "
                "continuou=tentando_blocos_locais"
            )
            cached_video, cached_candidate, cache_video_path = _preparar_video_cache_para_corte(
                candidate=candidate,
                seconds_before=seconds_before,
                seconds_after=seconds_after,
                football_metadata=football_metadata,
            )
            if cached_video is None:
                raise
            video_path = cached_video
            candidate = cached_candidate
            actual_render_source = "bloco_local"
            fallback_used = True
            require_audio = bool(video_path and _video_path_tem_audio(video_path))
            output_path, validation = _renderizar_validando(
                source=source,
                video_path=video_path,
                candidate=candidate,
                clip_id=corte_id,
                seconds_before=seconds_before,
                seconds_after=seconds_after,
                overlay_config=overlay_config,
                usar_download_trecho=False,
                output_layout=output_layout,
                keep_intermediate=keep_intermediate,
                require_audio=require_audio,
                target_height=None,
            )
        if cache_video_path is not None and not keep_intermediate:
            cache_video_path.unlink(missing_ok=True)
        output_path = _organizar_corte_por_revisao(output_path, review_action, target_height=target_height)
        marcar_concluido(corte_id, str(output_path))
        print(
            f"[ok] Corte {corte_id} concluido: {output_path} | "
            f"{validation.width}x{validation.height} | {validation.duration_seconds:.1f}s | "
            f"fonte={actual_render_source} | fallback={fallback_used}"
        )
        # Publicacao vertical e sempre POS-corte e opt-in (--publish-vertical):
        # o horizontal ja esta salvo acima; falha aqui nunca derruba o pipeline.
        if publish_config is not None and getattr(publish_config, "enabled", False):
            try:
                from publisher import publicar_corte

                publicar_corte(
                    output_path,
                    nicho=getattr(publish_config, "nicho", None),
                    credito_streamer=getattr(publish_config, "credito_streamer", None),
                    credito_canal=getattr(publish_config, "credito_canal", None),
                    social_config=getattr(publish_config, "social", None),
                )
            except Exception as publish_exc:
                print(
                    f"[publisher][falha] corte {corte_id}: {publish_exc}; "
                    "horizontal preservado, pipeline segue."
                )
        return CorteResultado(
            corte_id=corte_id,
            output_path=output_path,
            status="concluido",
            timestamp_seconds=candidate.timestamp_seconds,
            duration_seconds=clip_duration,
            validation_reason=validation.reason,
            render_source=actual_render_source,
            fallback_used=fallback_used,
        )
    except Exception as exc:
        if "cache_video_path" in locals() and cache_video_path is not None and not keep_intermediate:
            cache_video_path.unlink(missing_ok=True)
        marcar_erro(corte_id, str(exc))
        print(
            "[pos-live][falha] "
            f"timestamp={candidate.timestamp_seconds}s etapa=renderizar_corte "
            f"motivo={exc} comando=baixar_trecho/renderizar_layout continuou=sim"
        )
        return CorteResultado(
            corte_id=corte_id,
            output_path=None,
            status="erro",
            timestamp_seconds=candidate.timestamp_seconds,
            duration_seconds=clip_duration,
            validation_reason=str(exc),
            render_source="erro",
            fallback_used=False,
        )


def _video_path_tem_audio(video_path: Path) -> bool:
    try:
        from moviepy.editor import VideoFileClip
    except ImportError:
        from moviepy import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        return clip.audio is not None
    finally:
        clip.close()


def _organizar_corte_por_revisao(
    output_path: Path,
    review_action: Optional[str],
    target_height: Optional[int] = None,
) -> Path:
    if review_action not in {"save_ready", "save_needs_review", "reject"}:
        return output_path

    folder_name = {
        "save_ready": "ready_hd" if target_height else "ready",
        "save_needs_review": "needs_review",
        "reject": "rejected",
    }[review_action]
    target_dir = tagged_cortes_subdir(folder_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / output_path.name
    if target_path.exists():
        target_path.unlink()
    output_path.replace(target_path)
    print(f"[organizador] Corte movido para {folder_name}: {target_path}")
    return target_path


def _block_start_seconds(block_path: Path, block_seconds: int) -> Optional[int]:
    """Descobre o offset (em segundos) de inicio de um arquivo de bloco em cache.

    scan-vod grava "vod_block_{indice}_{inicio_em_segundos}.mp4" (2 numeros: o
    ultimo ja e o offset). live-clips/near-live grava "block_{indice}.mp4" (so o
    indice sequencial), entao o offset precisa ser calculado como indice * duracao.
    """
    stem = block_path.stem
    try:
        if stem.startswith("vod_block_"):
            return int(stem.rsplit("_", 1)[1])
        if stem.startswith("block_"):
            block_index = int(stem.rsplit("_", 1)[1])
            return block_index * block_seconds
    except (IndexError, ValueError):
        return None
    return None


def _preparar_video_cache_para_corte(
    candidate: HighlightCandidate,
    seconds_before: int,
    seconds_after: int,
    football_metadata: Optional[dict],
) -> tuple[Optional[Path], HighlightCandidate, Optional[Path]]:
    if not football_metadata:
        return None, candidate, None
    block_file = football_metadata.get("_block_file")
    if not block_file:
        return None, candidate, None

    original_block = Path(str(block_file))
    session_dir = original_block.parent
    if not session_dir.exists():
        return None, candidate, None

    # 45 e o default real de --block-seconds em todos os modos de captura.
    block_seconds = int(football_metadata.get("block_seconds") or 45)
    window_start = max(0, int(candidate.timestamp_seconds) - seconds_before)
    window_end = int(candidate.timestamp_seconds) + seconds_after
    blocks: list[tuple[int, Path]] = []
    # vod_block_*.mp4 vem do scan-vod; block_*.mp4 vem do live-clips/near-live.
    candidate_paths = list(session_dir.glob("vod_block_*.mp4")) + list(session_dir.glob("block_*.mp4"))
    for block_path in candidate_paths:
        block_start = _block_start_seconds(block_path, block_seconds)
        if block_start is None:
            continue
        if block_start < window_end and (block_start + block_seconds) > window_start:
            blocks.append((block_start, block_path))
    blocks.sort(key=lambda item: item[0])
    if not blocks:
        return None, candidate, None

    temp_dir().mkdir(parents=True, exist_ok=True)
    concat_id = uuid4().hex
    list_path = temp_dir() / f"cached_blocks_{concat_id}.txt"
    concat_path = temp_dir() / f"cached_range_{concat_id}.mp4"
    # Caminho absoluto: o demuxer concat resolve caminhos relativos a partir
    # da pasta da PROPRIA lista, quebrando com --output-root relativo.
    list_path.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for _, path in blocks) + "\n",
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
        print(
            "[pos-live][falha] "
            f"timestamp={candidate.timestamp_seconds}s etapa=concat_cache "
            f"motivo={(result.stderr or '').strip()[-500:]} comando=ffmpeg_concat_cache continuou=sim"
        )
        return None, candidate, None

    concat_start = blocks[0][0]
    adjusted = HighlightCandidate(
        timestamp_seconds=max(0, int(candidate.timestamp_seconds) - concat_start),
        score=candidate.score,
        audio_score=candidate.audio_score,
        motion_score=candidate.motion_score,
        brightness_score=candidate.brightness_score,
        reason=f"{candidate.reason}; fonte=cache_scan_vod",
    )
    print(
        "[pos-live] usando blocos locais do scan: "
        f"timestamp={candidate.timestamp_seconds}s blocos={len(blocks)} inicio_cache={concat_start}s"
    )
    return concat_path, adjusted, concat_path


def _criar_corte(
    source: str,
    video_path: Optional[Path],
    candidate: HighlightCandidate,
    clip_id: str,
    seconds_before: int,
    seconds_after: int,
    overlay_config: Optional[OverlayConfig],
    usar_download_trecho: bool,
    output_layout: OutputLayout,
    keep_intermediate: bool,
    target_height: Optional[int] = None,
) -> Path:
    if usar_download_trecho:
        return criar_corte_vertical(
            video_url=source,
            peak_timestamp=candidate.timestamp_seconds,
            clip_id=clip_id,
            seconds_before=seconds_before,
            seconds_after=seconds_after,
            overlay_config=overlay_config,
            limpar_cache_antes=False,
            limpar_cache_depois=False,
            output_layout=output_layout,
            keep_intermediate=keep_intermediate,
            target_height=target_height,
        )

    if video_path is None:
        raise ValueError("video_path e obrigatorio para cortes de arquivo completo.")
    return criar_corte_vertical_de_arquivo(
        input_video_path=video_path,
        peak_timestamp=candidate.timestamp_seconds,
        clip_id=clip_id,
        seconds_before=seconds_before,
        seconds_after=seconds_after,
        overlay_config=overlay_config,
        output_layout=output_layout,
        keep_intermediate=keep_intermediate,
    )


def _renderizar_validando(
    source: str,
    video_path: Optional[Path],
    candidate: HighlightCandidate,
    clip_id: str,
    seconds_before: int,
    seconds_after: int,
    overlay_config: Optional[OverlayConfig],
    usar_download_trecho: bool,
    output_layout: OutputLayout,
    keep_intermediate: bool,
    require_audio: bool,
    target_height: Optional[int] = None,
):
    attempts = [
        ("com overlay", overlay_config),
        ("sem overlay", None),
    ]
    if not (overlay_config and overlay_config.enabled):
        attempts = [("sem overlay", None)]

    last_reason = "falha desconhecida"
    for label, attempt_overlay in attempts:
        output_path = _criar_corte(
            source=source,
            video_path=video_path,
            candidate=candidate,
            clip_id=clip_id,
            seconds_before=seconds_before,
            seconds_after=seconds_after,
            overlay_config=attempt_overlay,
            usar_download_trecho=usar_download_trecho,
            output_layout=output_layout,
            keep_intermediate=keep_intermediate,
            target_height=target_height,
        )
        validation = validar_video_final(output_path, require_audio=require_audio)
        if validation.valid:
            if label == "sem overlay" and overlay_config and overlay_config.enabled:
                print(f"[validacao] Corte {clip_id} recuperado sem overlay.")
            return output_path, validation

        last_reason = validation.reason
        print(f"[validacao] Corte {clip_id} invalido {label}: {validation.reason}")
        output_path.unlink(missing_ok=True)

    raise RuntimeError(f"arquivo final invalido apos retry: {last_reason}")


def _dedupe_momentos(moments: list[MomentRecord], max_cortes: int, min_gap_seconds: int) -> list[MomentRecord]:
    ranked = sorted(moments, key=lambda item: (item.score, item.created_at), reverse=True)
    selected: list[MomentRecord] = []
    for moment in ranked:
        too_close = any(abs(moment.timestamp_seconds - kept.timestamp_seconds) < min_gap_seconds for kept in selected)
        if too_close:
            print(f"[dedupe] timestamp ignorado por proximidade: {moment.timestamp_seconds}s")
            continue
        selected.append(moment)
        if len(selected) >= max_cortes:
            break
    return sorted(selected, key=lambda item: item.timestamp_seconds)


def _dedupe_candidates(
    candidates: list[HighlightCandidate],
    max_cortes: int,
    min_gap_seconds: int,
) -> list[HighlightCandidate]:
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    selected: list[HighlightCandidate] = []
    for candidate in ranked:
        if any(abs(candidate.timestamp_seconds - kept.timestamp_seconds) < min_gap_seconds for kept in selected):
            print(f"[dedupe] candidato ignorado por proximidade: {candidate.timestamp_seconds}s")
            continue
        selected.append(candidate)
        if len(selected) >= max_cortes:
            break
    return sorted(selected, key=lambda item: item.timestamp_seconds)


def processar_pos_live(
    source: str,
    max_cortes: int = 8,
    usar_momentos_salvos: bool = False,
    session_id: Optional[str] = None,
    vod_offset_seconds: int = 0,
    sample_every_seconds: int = 3,
    analysis_window_seconds: int = 6,
    min_gap_seconds: int = 120,
    clip_duration: int = 60,
    pre_roll_seconds: Optional[int] = None,
    post_roll_seconds: Optional[int] = None,
    overlay_config: Optional[OverlayConfig] = None,
    output_layout: OutputLayout = "original",
    keep_intermediate: bool = False,
    target_height: Optional[int] = None,
    render_source: RenderSource = "auto",
    smart_event_window: bool = False,
    no_multi_event_clips: bool = False,
    max_clip_duration: int = 50,
    min_event_separation: int = 8,
    publish_config: Optional[object] = None,
) -> list[CorteResultado]:
    candidates: list[HighlightCandidate] = []
    moment_metadata_by_timestamp: dict[int, dict] = {}
    if usar_momentos_salvos:
        if session_id:
            moments = _dedupe_momentos(
                carregar_momentos(source_url=source, session_id=session_id),
                max_cortes=max_cortes,
                min_gap_seconds=min_gap_seconds,
            )
        else:
            moments = listar_melhores_momentos(
                source_url=source,
                limit=max_cortes,
                min_gap_seconds=min_gap_seconds,
            )
        if not moments:
            print(
                "[pos-live] Nenhum timestamp salvo para essa combinacao de source + session_id. "
                "Nada sera renderizado: timestamps de outras sessoes nunca sao reaproveitados. "
                f"Confira o --session-id ({session_id!r}) e use a MESMA URL/arquivo do scan/live."
            )
            return []
        else:
            print(f"[pos-live] Usando {len(moments)} timestamp(s) salvo(s).")
            # Chave igual ao timestamp do candidato em _candidate_from_moment
            # (com vod_offset aplicado), senao offset != 0 perde os metadados.
            moment_metadata_by_timestamp = {
                max(0, int(moment.timestamp_seconds) + int(vod_offset_seconds)): {
                    **(moment.metadata or {}),
                    "_block_file": moment.block_file,
                }
                for moment in moments
            }
            candidates = [_candidate_from_moment(moment, vod_offset_seconds) for moment in moments]

    usar_download_trecho = bool(candidates and usar_momentos_salvos and _is_url(source))
    video_path: Optional[Path] = None
    if usar_download_trecho:
        if target_height is not None and render_source != "cache":
            print(
                "[pos-live] URL com timestamps salvos: render final a partir do VOD original "
                f"com target_height={target_height}."
            )
        else:
            print("[pos-live] URL com timestamps salvos: baixando apenas trechos necessarios, sem VOD inteiro.")
    else:
        print("[pos-live] Preparando replay/VOD ou arquivo local...")
        video_path = resolver_fonte_video(source)
        print(f"[pos-live] Arquivo para cortes: {video_path}")

    if not candidates:
        print("[pos-live] Analisando video completo por audio + movimento + mudanca visual...")
        if video_path is None:
            video_path = resolver_fonte_video(source)
        candidates = detectar_melhores_momentos(
            video_path=video_path,
            max_cortes=max_cortes,
            sample_every_seconds=sample_every_seconds,
            analysis_window_seconds=analysis_window_seconds,
            min_gap_seconds=min_gap_seconds,
        )

    if not candidates:
        print("[pos-live] Nenhum momento forte detectado.")
        return []

    candidates = _dedupe_candidates(candidates, max_cortes=max_cortes, min_gap_seconds=min_gap_seconds)

    for index, candidate in enumerate(candidates, start=1):
        print(
            f"[pos-live] #{index}: {candidate.timestamp_seconds}s | "
            f"score={candidate.score} | audio={candidate.audio_score} | "
            f"motion={candidate.motion_score} | motivo={candidate.reason}"
        )

    selected_candidates = candidates[:max_cortes]
    use_smart_window = smart_event_window or no_multi_event_clips

    resultados: list[CorteResultado] = []
    for index, candidate in enumerate(selected_candidates):
        football_metadata = moment_metadata_by_timestamp.get(int(candidate.timestamp_seconds), {})
        review_action = football_metadata.get("football_action")
        if review_action is None and target_height is not None:
            review_action = "save_ready"

        smart_seconds_before = None
        smart_seconds_after = None
        smart_metadata = None
        if use_smart_window:
            event_type = (
                (football_metadata.get("event_type") or football_metadata.get("football_label"))
                if smart_event_window
                else None
            )
            previous_ts = selected_candidates[index - 1].timestamp_seconds if index > 0 else None
            next_ts = (
                selected_candidates[index + 1].timestamp_seconds
                if index + 1 < len(selected_candidates)
                else None
            )
            window = calculate_smart_event_window(
                event_peak_seconds=candidate.timestamp_seconds,
                event_type=event_type,
                previous_event_seconds=previous_ts,
                next_event_seconds=next_ts,
                pre_roll_seconds=pre_roll_seconds,
                post_roll_seconds=post_roll_seconds,
                clip_duration=clip_duration,
                max_clip_duration=max_clip_duration,
                min_event_separation=min_event_separation,
            )
            smart_seconds_before = window.pre_roll_used
            smart_seconds_after = window.post_roll_used
            smart_metadata = smart_window_metadata(window)
            print(
                f"[smart-window] #{index + 1} peak={candidate.timestamp_seconds}s "
                f"janela={window.start_seconds}-{window.end_seconds}s "
                f"multi_evento_evitado={window.prevented_multi_event} | {window.window_reason}"
            )

        resultados.append(
            _registrar_e_renderizar(
                source=source,
                video_path=video_path,
                candidate=candidate,
                overlay_config=overlay_config,
                clip_duration=clip_duration,
                pre_roll_seconds=pre_roll_seconds,
                post_roll_seconds=post_roll_seconds,
                usar_download_trecho=usar_download_trecho,
                output_layout=output_layout,
                keep_intermediate=keep_intermediate,
                review_action=review_action,
                football_metadata=football_metadata
                if football_metadata.get("content_filter") in {"football", "gta"}
                else None,
                target_height=target_height,
                render_source=render_source,
                smart_seconds_before=smart_seconds_before,
                smart_seconds_after=smart_seconds_after,
                smart_metadata=smart_metadata,
                publish_config=publish_config,
            )
        )
    return resultados
