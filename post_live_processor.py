from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from clipper import criar_corte_vertical_de_arquivo
from database import marcar_concluido, marcar_erro, marcar_processando, registrar_corte
from highlight_detector import HighlightCandidate, detectar_melhores_momentos
from moment_logger import MomentRecord, listar_melhores_momentos
from overlay_editor import OverlayConfig
from source_downloader import resolver_fonte_video


@dataclass(frozen=True)
class CorteResultado:
    corte_id: str
    output_path: Optional[Path]
    status: str
    timestamp_seconds: int


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
    video_path: Path,
    candidate: HighlightCandidate,
    overlay_config: Optional[OverlayConfig] = None,
) -> CorteResultado:
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
            "source_file": str(video_path),
        },
    )

    corte_id = str(corte["id"])
    print(
        f"[fila] Corte {corte_id} registrado | "
        f"timestamp={candidate.timestamp_seconds}s | score={candidate.score} | {candidate.reason}"
    )

    try:
        marcar_processando(corte_id)
        output_path = criar_corte_vertical_de_arquivo(
            input_video_path=video_path,
            peak_timestamp=candidate.timestamp_seconds,
            clip_id=corte_id,
            overlay_config=overlay_config,
        )
        marcar_concluido(corte_id, str(output_path))
        print(f"[ok] Corte {corte_id} concluido: {output_path}")
        return CorteResultado(corte_id=corte_id, output_path=output_path, status="concluido", timestamp_seconds=candidate.timestamp_seconds)
    except Exception as exc:
        marcar_erro(corte_id, str(exc))
        print(f"[erro] Corte {corte_id} falhou: {exc}")
        return CorteResultado(corte_id=corte_id, output_path=None, status="erro", timestamp_seconds=candidate.timestamp_seconds)


def processar_pos_live(
    source: str,
    max_cortes: int = 8,
    usar_momentos_salvos: bool = False,
    session_id: Optional[str] = None,
    vod_offset_seconds: int = 0,
    sample_every_seconds: int = 3,
    analysis_window_seconds: int = 6,
    min_gap_seconds: int = 45,
    overlay_config: Optional[OverlayConfig] = None,
) -> list[CorteResultado]:
    print("[pos-live] Preparando replay/VOD ou arquivo local...")
    video_path = resolver_fonte_video(source)
    print(f"[pos-live] Arquivo para cortes: {video_path}")

    candidates: list[HighlightCandidate] = []
    if usar_momentos_salvos:
        moments = listar_melhores_momentos(
            source_url=None if session_id else source,
            session_id=session_id,
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

    if not candidates:
        print("[pos-live] Analisando video completo por audio + movimento + mudanca visual...")
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
        )
        for candidate in candidates[:max_cortes]
    ]
