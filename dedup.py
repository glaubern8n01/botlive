from __future__ import annotations

"""V6 — dedup live x VOD (PLANO-VIGIA.md secao 3).

Indice de cortes ja feitos (tabela vigia_clip_index) para o reprocesso de VOD
NAO repetir os momentos que o modo live ja capturou — so complementar com o que
o live perdeu.

Coordenada unica de todo o indice: TEMPO DO VOD (segundos desde o started_at da
transmissao, que e a origem da linha do tempo do archive da Twitch).

- Corte de VOD ja nasce em tempo de VOD (timestamp absoluto do scan).
- Corte de live nasce em tempo de CAPTURA; converte-se com
  ts_vod ~= ts_live + (capture_start_utc - started_at).
  A tolerancia do dedup (default 60s) cobre o erro de alinhamento (borda do HLS
  na Etapa C, +-15s) + picos ligeiramente diferentes nas duas analises.

Leitura e escrita passam pelo MESMO cliente Supabase do robo
(database._get_client). Sem Supabase configurado, tudo vira no-op seguro: o
dedup nao filtra nada e o VOD processa como sempre (nunca quebra o pipeline).
"""

from datetime import datetime
from typing import Any, Iterable, Optional

CLIP_INDEX_TABLE = "vigia_clip_index"


def _client():
    # Import tardio: quem nao usa dedup nao paga o import do supabase.
    from database import _get_client

    return _get_client()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def offset_live_para_vod(capture_start_utc: Any, started_at: Any) -> Optional[int]:
    """Segundos a somar num timestamp de CAPTURA para chegar no tempo do VOD.

    ts_vod = ts_live + offset, com offset = capture_start_utc - started_at.
    None quando falta alguma das duas ancoras (sem conversao possivel).
    """
    cap = _parse_dt(capture_start_utc)
    started = _parse_dt(started_at)
    if cap is None or started is None:
        return None
    return int(round((cap - started).total_seconds()))


def carregar_clips_indexados(stream_id: str) -> list[dict[str, Any]]:
    """Cortes ja feitos (qualquer modo) deste stream_id, em tempo de VOD.

    Falha de leitura => lista vazia (o VOD processa tudo; pior caso e um
    corte duplicado, nunca um corte perdido)."""
    client = _client()
    if client is None:
        return []
    try:
        resp = (
            client.table(CLIP_INDEX_TABLE)
            .select("mode, ts_vod_estimated, clip_start_vod, clip_end_vod")
            .eq("stream_id", str(stream_id))
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        print(f"[dedup] falha ao ler vigia_clip_index de {stream_id} ({exc}); sem dedup neste job.")
        return []


def timestamps_colidentes(
    candidate_peaks: Iterable[Any],
    clips_indexados: list[dict[str, Any]],
    clip_duration_seconds: int,
    window_seconds: int,
) -> set[int]:
    """Picos (em tempo de VOD) que colidem com algum corte ja indexado.

    Um candidato de pico `p` ocupa a janela [p - clip/2, p + clip/2]. Ele
    COLIDE se essa janela sobrepoe [clip_start - W, clip_end + W] de qualquer
    corte ja feito (W = window_seconds). Retorna o conjunto de picos colidentes
    (os que NAO devem renderizar de novo).
    """
    half = float(clip_duration_seconds) / 2.0
    intervalos: list[tuple[float, float]] = []
    for c in clips_indexados:
        try:
            lo = float(c["clip_start_vod"]) - window_seconds
            hi = float(c["clip_end_vod"]) + window_seconds
        except (KeyError, TypeError, ValueError):
            continue
        if hi >= lo:
            intervalos.append((lo, hi))

    colidem: set[int] = set()
    for peak in candidate_peaks:
        try:
            p = float(peak)
        except (TypeError, ValueError):
            continue
        cand_lo, cand_hi = p - half, p + half
        for lo, hi in intervalos:
            if cand_lo <= hi and cand_hi >= lo:  # sobreposicao de intervalos
                colidem.add(int(peak))
                break
    return colidem


def registrar_clip(
    stream_id: str,
    mode: str,
    ts_vod_estimated: int,
    clip_start_vod: int,
    clip_end_vod: int,
    session_id: str,
    corte_ref: Optional[str] = None,
) -> bool:
    """Grava um corte concluido no indice, em tempo de VOD. True se persistiu.

    Falha de escrita nao derruba nada: apenas loga (o dedup futuro pode repetir
    esse momento, que e exatamente o comportamento de hoje)."""
    client = _client()
    if client is None:
        return False
    row = {
        "stream_id": str(stream_id),
        "mode": mode,
        "ts_vod_estimated": int(ts_vod_estimated),
        "clip_start_vod": int(clip_start_vod),
        "clip_end_vod": int(clip_end_vod),
        "session_id": str(session_id),
        "corte_ref": corte_ref,
    }
    try:
        client.table(CLIP_INDEX_TABLE).insert(row).execute()
        return True
    except Exception as exc:
        print(f"[dedup] falha ao gravar clip no indice ({exc}); dedup futuro pode repetir este momento.")
        return False
