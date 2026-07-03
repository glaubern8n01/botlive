from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Pre-roll/post-roll ideais por tipo de evento de futebol (regras do usuario).
# Medido em VOD real: o pico do detector erra a explosao de audio em ate ~12s
# (amostragem de 3s + blocos alinhados em keyframe). O pre-roll precisa cobrir
# esse erro E a jogada antes do grito (passe/corrida/chute), estilo replay.
DEFAULT_PRE_ROLL_BY_EVENT_TYPE: dict[str, int] = {
    "penalty_kick": 20,
    "goal_or_chance": 25,
    "goalkeeper_save": 20,
    "big_chance": 22,
}
DEFAULT_POST_ROLL_BY_EVENT_TYPE: dict[str, int] = {
    "penalty_kick": 18,
    "goal_or_chance": 20,
    "goalkeeper_save": 18,
    "big_chance": 18,
}

MIN_PRE_ROLL_SECONDS = 10
MIN_POST_ROLL_SECONDS = 8
DEFAULT_MAX_CLIP_DURATION = 50
DEFAULT_MIN_EVENT_SEPARATION = 8
# validar_video_final rejeita cortes com duracao <= 5s; a janela nunca pode
# ficar menor que isso, mesmo com eventos vizinhos muito proximos.
MIN_WINDOW_SECONDS = 6


@dataclass(frozen=True)
class SmartEventWindow:
    start_seconds: int
    end_seconds: int
    duration_seconds: int
    pre_roll_used: int
    post_roll_used: int
    previous_event_seconds: Optional[int]
    next_event_seconds: Optional[int]
    prevented_multi_event: bool
    window_reason: str


def calculate_smart_event_window(
    event_peak_seconds: int,
    event_type: Optional[str],
    previous_event_seconds: Optional[int] = None,
    next_event_seconds: Optional[int] = None,
    pre_roll_seconds: Optional[int] = None,
    post_roll_seconds: Optional[int] = None,
    clip_duration: Optional[int] = None,
    max_clip_duration: int = DEFAULT_MAX_CLIP_DURATION,
    min_event_separation: int = DEFAULT_MIN_EVENT_SEPARATION,
) -> SmartEventWindow:
    """Calcula start/end de um corte de 1 lance so, sem juntar eventos vizinhos.

    Regras (pedidas pelo usuario):
    - cada corte tem 1 lance principal, pre-roll/post-roll adaptado ao event_type;
    - se o proximo evento cair dentro da janela, o fim e antecipado (nunca junta
      dois lances fortes no mesmo mp4);
    - se o evento anterior estiver perto, o inicio e adiado pelo mesmo motivo;
    - a duracao nunca passa de max_clip_duration (corta o post-roll primeiro,
      protegendo o inicio da jogada).
    """
    peak = int(event_peak_seconds)
    fallback_pre = int(pre_roll_seconds) if pre_roll_seconds is not None else 15
    fallback_post = int(post_roll_seconds) if post_roll_seconds is not None else 15
    pre_roll = max(MIN_PRE_ROLL_SECONDS, int(DEFAULT_PRE_ROLL_BY_EVENT_TYPE.get(event_type or "", fallback_pre)))
    post_roll = max(MIN_POST_ROLL_SECONDS, int(DEFAULT_POST_ROLL_BY_EVENT_TYPE.get(event_type or "", fallback_post)))

    reasons = [f"pre-roll={pre_roll}s post-roll={post_roll}s (event_type={event_type or 'generico'})"]
    start = max(0, peak - pre_roll)
    end = peak + post_roll
    prevented_multi_event = False

    if previous_event_seconds is not None and previous_event_seconds < peak:
        min_allowed_start = int(previous_event_seconds) + min_event_separation
        if start < min_allowed_start:
            start = min(min_allowed_start, peak)
            prevented_multi_event = True
            reasons.append(
                f"inicio adiado para {start}s (evento anterior no pico {previous_event_seconds}s "
                f"+ {min_event_separation}s de folga)"
            )

    if next_event_seconds is not None and next_event_seconds > peak:
        max_allowed_end = int(next_event_seconds) - min_event_separation
        if end > max_allowed_end:
            end = max_allowed_end if max_allowed_end > peak else peak + MIN_POST_ROLL_SECONDS
            end = min(end, int(next_event_seconds) - 1)
            prevented_multi_event = True
            reasons.append(
                f"fim antecipado para {end}s (proximo evento no pico {next_event_seconds}s "
                f"- {min_event_separation}s de folga)"
            )

    duration = end - start
    if duration > max_clip_duration:
        excess = duration - max_clip_duration
        trim_post = min(excess, max(0, end - (peak + MIN_POST_ROLL_SECONDS)))
        end -= trim_post
        excess -= trim_post
        if excess > 0:
            floor_start = peak - MIN_PRE_ROLL_SECONDS
            trim_pre = min(excess, max(0, start - max(0, floor_start)))
            start += trim_pre
        reasons.append(f"duracao limitada a {max_clip_duration}s (maximo padrao)")

    if end - start < MIN_WINDOW_SECONDS:
        end = start + MIN_WINDOW_SECONDS
        reasons.append(
            f"janela minima de {MIN_WINDOW_SECONDS}s aplicada (eventos muito proximos)"
        )

    duration = end - start
    return SmartEventWindow(
        start_seconds=int(start),
        end_seconds=int(end),
        duration_seconds=int(duration),
        pre_roll_used=int(peak - start),
        post_roll_used=int(end - peak),
        previous_event_seconds=int(previous_event_seconds) if previous_event_seconds is not None else None,
        next_event_seconds=int(next_event_seconds) if next_event_seconds is not None else None,
        prevented_multi_event=prevented_multi_event,
        window_reason=" | ".join(reasons),
    )


def smart_window_metadata(window: SmartEventWindow) -> dict:
    return {
        "smart_start_seconds": window.start_seconds,
        "smart_end_seconds": window.end_seconds,
        "smart_duration_seconds": window.duration_seconds,
        "smart_pre_roll_seconds": window.pre_roll_used,
        "smart_post_roll_seconds": window.post_roll_used,
        "previous_event_seconds": window.previous_event_seconds,
        "next_event_seconds": window.next_event_seconds,
        "prevented_multi_event": window.prevented_multi_event,
        "window_reason": window.window_reason,
    }
