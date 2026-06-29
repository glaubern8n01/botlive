from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from highlight_detector import detectar_melhores_momentos
from live_buffer import capturar_bloco
from moment_logger import salvar_momento, source_id_from_url


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
