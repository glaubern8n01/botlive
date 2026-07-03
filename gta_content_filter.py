from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from PIL import Image

try:
    from moviepy.editor import VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import VideoFileClip


GtaContentType = Literal["action", "talk", "dead", "unknown"]
GtaAction = Literal["save_ready", "save_needs_review", "reject"]

# --- Mascara da facecam -------------------------------------------------
# No layout de referencia (VOD "PAULINHO O LOKO AO VIVO - GTA RP", 720p) a
# facecam ocupa o canto inferior esquerdo: x < 32% e y > 50% do quadro.
# Ela se mexe o tempo todo (streamer falando) e poluia toda a analise de
# movimento; por isso essa regiao e excluida. Streams com facecam em outra
# posicao podem precisar de ajuste destes dois valores.
FACECAM_X_MAX = 0.32
FACECAM_Y_MIN = 0.50

# --- Limiares calibrados nos valores MEDIDOS no VOD de referencia -------
# (janela de +-10s ao redor do pico do candidato, frames 160x90 a cada 0.5s)
#
# m_med (mediana do movimento na regiao do jogo, amostragem densa):
#   perseguicao 112-183km/h: 0.140 | tiroteio no telhado: 0.105
#   ligacao dirigindo: 0.076 | menu+fone: 0.057 | fone parado/conversa: 0.021
ACTION_SUSTAINED_MOTION_MIN = 0.09
# audio impulsivo (p98/mediana do RMS em janelas de 0.5s):
#   desmaio/porrada com gritos: 5.65 | ligacoes/conversa: 1.8-2.9
ACTION_AUDIO_TRANSIENT_MIN = 4.0
ACTION_AUDIO_MEAN_MIN = 0.03
ACTION_MOTION_FLOOR = 0.035  # desmaio: 0.041 | fone parado: 0.021
# fracao de pixels do jogo parados no tempo (UI de ligacao/menu sobre jogo):
#   ligacao dirigindo: 0.23 | jogo livre: <= 0.06
UI_OVERLAY_MAX_FOR_ACTION = 0.15
# fala animada (conteudo viral de RP) vs ligacao morna:
#   ligacao do advogado (pico do heatmap): a_mean 0.168 | fracas: 0.089-0.118
TALK_AUDIO_MEAN_MIN = 0.12
TALK_AUDIO_CV_MIN = 0.75  # fala expressiva com volume variando (exige mean >= 0.05)
TALK_AUDIO_MEAN_FLOOR = 0.05

ANALYSIS_WINDOW_SECONDS = 10  # para cada lado do pico
FRAME_STEP_SECONDS = 0.5
STATIC_PIXEL_STD = 0.015


@dataclass(frozen=True)
class GtaContentResult:
    content_type: GtaContentType
    category: GtaContentType
    action: GtaAction
    game_motion_median: float
    game_motion_p95: float
    static_ui_ratio: float
    audio_rms_mean: float
    audio_rms_cv: float
    audio_transient_ratio: float
    score_final: float
    reason: str


def _reject(reason: str) -> GtaContentResult:
    return GtaContentResult(
        content_type="unknown",
        category="unknown",
        action="reject",
        game_motion_median=0.0,
        game_motion_p95=0.0,
        static_ui_ratio=0.0,
        audio_rms_mean=0.0,
        audio_rms_cv=0.0,
        audio_transient_ratio=0.0,
        score_final=-1.0,
        reason=reason,
    )


def _sample_game_frames(clip: VideoFileClip, start: float, end: float) -> np.ndarray:
    timestamps = np.arange(start, end, FRAME_STEP_SECONDS)
    frames = []
    for timestamp in timestamps:
        frame = clip.get_frame(float(timestamp))
        gray = np.asarray(Image.fromarray(frame).resize((160, 90)).convert("L"), dtype=np.float32) / 255.0
        gray[int(90 * FACECAM_Y_MIN):, : int(160 * FACECAM_X_MAX)] = np.nan
        frames.append(gray)
    return np.stack(frames) if frames else np.zeros((0, 90, 160))


def _audio_rms_series(clip: VideoFileClip, start: float, end: float) -> np.ndarray:
    if clip.audio is None:
        return np.zeros(1)
    values = []
    t = start
    while t < end:
        segment = clip.audio.subclip(t, min(end, t + FRAME_STEP_SECONDS))
        chunks = list(segment.iter_chunks(fps=8000, chunksize=4000))
        samples = np.vstack(chunks) if chunks else np.zeros((1, 2))
        values.append(float(np.sqrt(np.mean(np.square(samples)))))
        t += FRAME_STEP_SECONDS
    return np.asarray(values) if values else np.zeros(1)


def classify_gta_content(
    video_path: str | Path,
    *,
    candidate_block_seconds: Optional[float] = None,
    score_base: float = 0.0,
) -> GtaContentResult:
    """Classifica um trecho de GTA em 3 vias: action / talk / dead.

    - action (save_ready): movimento sustentado na regiao do jogo (tiroteio,
      perseguicao, briga) ou pico impulsivo de audio com jogo se mexendo.
    - talk (save_needs_review): jogo parado mas fala animada (ligacao/conversa
      expressiva) — conteudo potencialmente viral de RP, vai para revisao.
    - dead (reject): menu/loading/tela parada ou fala morna/silencio.

    A analise foca uma janela de +-10s ao redor do pico do candidato
    (candidate_block_seconds, relativo ao inicio do arquivo); sem esse valor,
    analisa o arquivo inteiro.
    """
    video_path = Path(video_path)
    try:
        clip = VideoFileClip(str(video_path))
    except Exception as exc:
        return _reject(f"falha ao abrir trecho: {exc}")

    try:
        duration = float(clip.duration or 0.0)
        if duration <= 2.0:
            return _reject("duracao muito curta")
        if candidate_block_seconds is None:
            window_start, window_end = 0.3, duration - 0.3
        else:
            peak = float(candidate_block_seconds)
            window_start = max(0.3, peak - ANALYSIS_WINDOW_SECONDS)
            window_end = min(duration - 0.3, peak + ANALYSIS_WINDOW_SECONDS)
            if window_end - window_start < 4.0:
                window_start, window_end = 0.3, duration - 0.3

        stack = _sample_game_frames(clip, window_start, window_end)
        if len(stack) < 4:
            return _reject("frames insuficientes para analise")
        diffs = np.abs(np.diff(stack, axis=0))
        motion_series = np.nanmean(diffs.reshape(len(diffs), -1), axis=1)
        motion_median = float(np.median(motion_series))
        motion_p95 = float(np.percentile(motion_series, 95))
        pixel_std = np.nanstd(stack, axis=0)
        static_ui_ratio = float(np.nanmean((pixel_std < STATIC_PIXEL_STD).astype(float)))

        rms = _audio_rms_series(clip, window_start, window_end)
        audio_mean = float(np.mean(rms))
        audio_cv = float(np.std(rms) / max(audio_mean, 1e-6))
        audio_transient = float(np.percentile(rms, 98) / max(float(np.median(rms)), 1e-4))
    except Exception as exc:
        return _reject(f"falha ao analisar trecho: {exc}")
    finally:
        clip.close()

    sustained_action = motion_median >= ACTION_SUSTAINED_MOTION_MIN
    impulsive_action = (
        audio_transient >= ACTION_AUDIO_TRANSIENT_MIN
        and audio_mean >= ACTION_AUDIO_MEAN_MIN
        and motion_median >= ACTION_MOTION_FLOOR
    )
    ui_blocks_action = static_ui_ratio >= UI_OVERLAY_MAX_FOR_ACTION
    animated_talk = audio_mean >= TALK_AUDIO_MEAN_MIN or (
        audio_cv >= TALK_AUDIO_CV_MIN and audio_mean >= TALK_AUDIO_MEAN_FLOOR
    )

    reasons: list[str] = []
    if not ui_blocks_action and (sustained_action or impulsive_action):
        content_type: GtaContentType = "action"
        action: GtaAction = "save_ready"
        if sustained_action:
            reasons.append(f"movimento sustentado no jogo ({motion_median:.3f})")
        if impulsive_action:
            reasons.append(f"pico impulsivo de audio ({audio_transient:.1f}x)")
    elif animated_talk:
        content_type = "talk"
        action = "save_needs_review"
        reasons.append(f"fala animada (rms={audio_mean:.3f} cv={audio_cv:.2f}), jogo sem acao")
        if ui_blocks_action:
            reasons.append("tela de ligacao/UI sobre o jogo")
    else:
        content_type = "dead"
        action = "reject"
        if ui_blocks_action:
            reasons.append("tela de ligacao/menu estatica sobre o jogo")
        if motion_median < ACTION_MOTION_FLOOR:
            reasons.append(f"jogo parado ({motion_median:.3f})")
        reasons.append(f"audio morno/silencio (rms={audio_mean:.3f} cv={audio_cv:.2f})")

    score_final = round(float(score_base) + 3.0 * motion_median + audio_mean, 4)

    return GtaContentResult(
        content_type=content_type,
        category=content_type,
        action=action,
        game_motion_median=round(motion_median, 4),
        game_motion_p95=round(motion_p95, 4),
        static_ui_ratio=round(static_ui_ratio, 4),
        audio_rms_mean=round(audio_mean, 4),
        audio_rms_cv=round(audio_cv, 4),
        audio_transient_ratio=round(audio_transient, 2),
        score_final=score_final,
        reason=", ".join(reasons),
    )
