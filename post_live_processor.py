from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
from source_downloader import resolver_fonte_video


@dataclass(frozen=True)
class CorteResultado:
    corte_id: str
    output_path: Optional[Path]
    status: str
    timestamp_seconds: int
    duration_seconds: Optional[int] = None
    validation_reason: Optional[str] = None


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
    usar_download_trecho: bool = False,
    output_layout: OutputLayout = "original",
    keep_intermediate: bool = False,
) -> CorteResultado:
    seconds_before = max(1, clip_duration // 2)
    seconds_after = max(1, clip_duration - seconds_before)
    corte = registrar_corte(
        live_url=source,
        peak_timestamp=candidate.timestamp_seconds,
        keywords=["video_audio_detector"],
        messages_per_minute=None,
        status="pendente",
        metadata={
            "mode": "post_live",
            "score": candidate.score,
            "audio_score": candidate.audio_score,
            "motion_score": candidate.motion_score,
            "brightness_score": candidate.brightness_score,
            "reason": candidate.reason,
            "source_file": str(video_path) if video_path else None,
            "clip_duration": clip_duration,
            "download_mode": "trecho" if usar_download_trecho else "arquivo_completo",
            "output_layout": output_layout,
        },
    )

    corte_id = str(corte["id"])
    print(
        f"[fila] Corte {corte_id} registrado | "
        f"timestamp={candidate.timestamp_seconds}s | score={candidate.score} | {candidate.reason}"
    )

    try:
        marcar_processando(corte_id)
        require_audio = bool(usar_download_trecho or (video_path and _video_path_tem_audio(video_path)))
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
        )
        marcar_concluido(corte_id, str(output_path))
        print(
            f"[ok] Corte {corte_id} concluido: {output_path} | "
            f"{validation.width}x{validation.height} | {validation.duration_seconds:.1f}s"
        )
        return CorteResultado(
            corte_id=corte_id,
            output_path=output_path,
            status="concluido",
            timestamp_seconds=candidate.timestamp_seconds,
            duration_seconds=clip_duration,
            validation_reason=validation.reason,
        )
    except Exception as exc:
        marcar_erro(corte_id, str(exc))
        print(f"[erro] Corte {corte_id} falhou: {exc}")
        return CorteResultado(
            corte_id=corte_id,
            output_path=None,
            status="erro",
            timestamp_seconds=candidate.timestamp_seconds,
            duration_seconds=clip_duration,
            validation_reason=str(exc),
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
    overlay_config: Optional[OverlayConfig] = None,
    output_layout: OutputLayout = "original",
    keep_intermediate: bool = False,
) -> list[CorteResultado]:
    candidates: list[HighlightCandidate] = []
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
            print("[pos-live] Nenhum timestamp salvo para esse filtro. Tentando usar timestamps salvos recentes.")
            moments = listar_melhores_momentos(limit=max_cortes, min_gap_seconds=min_gap_seconds)
        if not moments:
            print("[pos-live] Nenhum timestamp salvo encontrado. Buscando melhores momentos no video.")
        else:
            print(f"[pos-live] Usando {len(moments)} timestamp(s) salvo(s).")
            candidates = [_candidate_from_moment(moment, vod_offset_seconds) for moment in moments]

    usar_download_trecho = bool(candidates and usar_momentos_salvos and _is_url(source))
    video_path: Optional[Path] = None
    if usar_download_trecho:
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

    return [
        _registrar_e_renderizar(
            source=source,
            video_path=video_path,
            candidate=candidate,
            overlay_config=overlay_config,
            clip_duration=clip_duration,
            usar_download_trecho=usar_download_trecho,
            output_layout=output_layout,
            keep_intermediate=keep_intermediate,
        )
        for candidate in candidates[:max_cortes]
    ]
