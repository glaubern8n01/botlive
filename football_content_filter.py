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


FootballContentType = Literal[
    "match_action",
    "penalty_kick",
    "big_chance",
    "goalkeeper_save",
    "goal_or_chance",
    "celebration",
    "pregame",
    "postgame",
    "studio_or_commentary",
    "var_or_graphics",
    "crowd_or_stadium_only",
    "replay_of_play",
    "crowd_reaction",
    "interview",
    "studio",
    "static_screen",
    "menu",
    "unknown",
]
FootballCategory = Literal[
    "active_play",
    "pregame",
    "postgame",
    "studio_or_commentary",
    "var_or_graphics",
    "crowd_or_stadium_only",
    "static_screen",
    "unknown",
]
FootballAction = Literal["save_ready", "save_needs_review", "reject"]

# Categorias que nunca podem virar save_ready, mesmo com campo/placar/torcida
# visiveis: sozinhos esses sinais nao provam que ha jogada real acontecendo.
NON_PLAY_CATEGORIES: frozenset[str] = frozenset(
    {"pregame", "postgame", "studio_or_commentary", "var_or_graphics", "crowd_or_stadium_only", "static_screen"}
)


@dataclass(frozen=True)
class FootballContentResult:
    content_type: FootballContentType
    football_confidence: float
    interview_penalty: float
    studio_penalty: float
    static_penalty: float
    green_field_ratio: float
    motion_score: float
    visual_change_score: float
    emotion_score: float
    penalty_score: float
    scoreboard_like: bool
    score_final: float
    action: FootballAction
    reason: str
    category: FootballCategory = "unknown"
    active_play_score: float = 0.0
    pregame_score: float = 0.0
    postgame_score: float = 0.0
    studio_score: float = 0.0
    var_graphics_score: float = 0.0
    crowd_only_score: float = 0.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


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


def _skin_ratio(frame: np.ndarray) -> float:
    arr = frame.astype(np.float32)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    skin_mask = (
        (red > 75)
        & (green > 35)
        & (blue > 20)
        & (red > green * 1.10)
        & (green > blue * 1.05)
        & ((np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])) > 18)
    )
    return float(np.mean(skin_mask))


def _white_line_ratio(frame: np.ndarray) -> float:
    arr = frame.astype(np.float32)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    white_mask = (red > 170) & (green > 170) & (blue > 170) & (np.std(arr, axis=2) < 35)
    return float(np.mean(white_mask))


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


def _scoreboard_like(frames: list[np.ndarray]) -> bool:
    if not frames:
        return False
    hits = 0
    for frame in frames:
        top = frame[: max(8, frame.shape[0] // 5), :, :].astype(np.float32)
        brightness = np.mean(top, axis=2)
        contrast = float(np.std(brightness))
        dark_ratio = float(np.mean(brightness < 70))
        light_ratio = float(np.mean(brightness > 180))
        if contrast > 35 and (dark_ratio > 0.10 or light_ratio > 0.08):
            hits += 1
    return hits >= max(1, len(frames) // 3)


def _sample_frames(video_path: Path) -> tuple[list[np.ndarray], float]:
    clip = VideoFileClip(str(video_path))
    try:
        duration = float(clip.duration or 0.0)
        if duration <= 1.0:
            return [], duration
        sample_count = min(10, max(5, int(duration // 5) + 1))
        timestamps = np.linspace(0.5, max(0.5, duration - 0.5), sample_count)
        frames: list[np.ndarray] = []
        for timestamp in timestamps:
            frame = clip.get_frame(float(timestamp))
            image = Image.fromarray(frame).resize((160, 90))
            frames.append(np.asarray(image.convert("RGB"), dtype=np.uint8))
        return frames, duration
    finally:
        clip.close()


def _play_motion_shape(distributed_motion: float) -> float:
    """Jogada real ativa uma fatia moderada da grade de movimento (jogadores +
    bola), nao o quadro quase inteiro de uma vez (pan de camera/corte de
    estadio) nem quase nada (plano parado/estudio)."""
    if distributed_motion <= 0.05:
        return 0.0
    if distributed_motion <= 0.16:
        return _clamp((distributed_motion - 0.05) / 0.11)
    if distributed_motion <= 0.55:
        return 1.0
    if distributed_motion <= 0.80:
        return _clamp(1.0 - (distributed_motion - 0.55) / 0.25)
    return 0.15


def classify_football_content(
    video_path: str | Path,
    *,
    strict: bool = False,
    score_base: float = 0.0,
    audio_score: float = 0.0,
    candidate_motion_score: float = 0.0,
    visual_change_score: float = 0.0,
) -> FootballContentResult:
    video_path = Path(video_path)
    try:
        frames, duration = _sample_frames(video_path)
    except Exception as exc:
        return FootballContentResult(
            content_type="unknown",
            football_confidence=0.0,
            interview_penalty=0.0,
            studio_penalty=0.0,
            static_penalty=1.0,
            green_field_ratio=0.0,
            motion_score=0.0,
            visual_change_score=0.0,
            emotion_score=0.0,
            penalty_score=0.0,
            scoreboard_like=False,
            score_final=-1.0,
            action="reject",
            reason=f"falha ao analisar bloco: {exc}",
        )

    if not frames or duration <= 1.0:
        return FootballContentResult(
            content_type="static_screen",
            football_confidence=0.0,
            interview_penalty=0.0,
            studio_penalty=0.0,
            static_penalty=1.0,
            green_field_ratio=0.0,
            motion_score=0.0,
            visual_change_score=0.0,
            emotion_score=0.0,
            penalty_score=0.0,
            scoreboard_like=False,
            score_final=-1.0,
            action="reject",
            reason="duracao muito curta ou sem frames",
        )

    green_values: list[float] = []
    skin_values: list[float] = []
    white_values: list[float] = []
    brightness_values: list[float] = []
    contrast_values: list[float] = []
    motion_values: list[float] = []
    previous_gray: Optional[np.ndarray] = None

    for frame in frames:
        gray = np.asarray(Image.fromarray(frame).convert("L"), dtype=np.float32) / 255.0
        green_values.append(_green_ratio(frame))
        skin_values.append(_skin_ratio(frame))
        white_values.append(_white_line_ratio(frame))
        brightness_values.append(float(np.mean(gray)))
        contrast_values.append(float(np.std(gray)))
        if previous_gray is not None:
            motion_values.append(_motion_grid_ratio(previous_gray, gray))
        previous_gray = gray

    green_ratio = float(np.mean(green_values))
    skin_ratio = float(np.mean(skin_values))
    white_ratio = float(np.mean(white_values))
    brightness = float(np.mean(brightness_values))
    contrast = float(np.mean(contrast_values))
    distributed_motion = float(np.mean(motion_values)) if motion_values else 0.0
    scoreboard = _scoreboard_like(frames)

    return classify_football_metrics(
        green_ratio=green_ratio,
        skin_ratio=skin_ratio,
        white_ratio=white_ratio,
        brightness=brightness,
        contrast=contrast,
        distributed_motion=distributed_motion,
        scoreboard=scoreboard,
        strict=strict,
        score_base=score_base,
        audio_score=audio_score,
        candidate_motion_score=candidate_motion_score,
        visual_change_score=visual_change_score,
    )


def classify_football_metrics(
    *,
    green_ratio: float,
    skin_ratio: float,
    white_ratio: float,
    brightness: float,
    contrast: float,
    distributed_motion: float,
    scoreboard: bool,
    strict: bool = False,
    score_base: float = 0.0,
    audio_score: float = 0.0,
    candidate_motion_score: float = 0.0,
    visual_change_score: float = 0.0,
) -> FootballContentResult:
    """Nucleo puro da classificacao: recebe metricas ja calculadas (de frames
    reais ou simuladas em teste) e decide categoria/acao. Sem I/O de video,
    para permitir testar a logica com metadados simulados."""
    visual_change = _clamp(max(visual_change_score, distributed_motion))

    field_score = _clamp((green_ratio / 0.22) * 0.65 + (distributed_motion / 0.45) * 0.25 + (white_ratio / 0.035) * 0.10)
    if scoreboard and green_ratio >= 0.06:
        field_score = _clamp(field_score + 0.08)
    if green_ratio >= 0.16 and distributed_motion >= 0.05:
        field_score = max(field_score, 0.62)
    if green_ratio >= 0.28:
        field_score = max(field_score, 0.78)

    static_penalty = 0.0
    if brightness < 0.06 or contrast < 0.018:
        static_penalty = 1.0
    elif distributed_motion < 0.04 and visual_change_score < 0.20:
        static_penalty = 0.65

    interview_penalty = 0.0
    if green_ratio < 0.08 and skin_ratio > 0.075:
        interview_penalty = 0.75
    if green_ratio < 0.05 and skin_ratio > 0.11:
        interview_penalty = 0.92
    if green_ratio < 0.08 and distributed_motion < 0.18 and skin_ratio > 0.05:
        interview_penalty = max(interview_penalty, 0.65)

    studio_penalty = 0.0
    if green_ratio < 0.06 and skin_ratio <= 0.075 and contrast >= 0.08:
        studio_penalty = 0.58
    if green_ratio < 0.04 and distributed_motion < 0.12 and contrast >= 0.08:
        studio_penalty = max(studio_penalty, 0.72)

    emotion_score = _clamp((audio_score * 0.50) + (candidate_motion_score * 0.30) + (visual_change_score * 0.20))
    emotion_score = round(emotion_score * field_score, 4)
    set_piece_shape = 0.06 <= distributed_motion <= 0.38
    goal_area_signal = white_ratio >= 0.026 or (scoreboard and white_ratio >= 0.018)
    after_kick_signal = audio_score >= 0.58 and visual_change_score >= 0.32
    penalty_score = 0.0
    if field_score >= 0.72 and set_piece_shape and goal_area_signal and after_kick_signal:
        penalty_score = _clamp(
            0.18
            + (audio_score * 0.30)
            + (visual_change_score * 0.22)
            + (white_ratio / 0.08 * 0.16)
            + (0.12 if scoreboard else 0.0)
        )
    if field_score >= 0.82 and goal_area_signal and audio_score >= 0.70 and visual_change_score >= 0.45:
        penalty_score = max(penalty_score, 0.72)

    save_score = 0.0
    if field_score >= 0.62 and candidate_motion_score >= 0.50 and visual_change_score >= 0.30 and audio_score >= 0.42:
        save_score = _clamp((candidate_motion_score * 0.35) + (visual_change_score * 0.25) + (audio_score * 0.25) + (white_ratio / 0.06 * 0.15))

    chance_score = 0.0
    if field_score >= 0.60:
        chance_score = _clamp((emotion_score * 0.55) + (candidate_motion_score * 0.20) + (audio_score * 0.15) + (visual_change_score * 0.10))

    negative_score = interview_penalty + studio_penalty + static_penalty
    score_final = (score_base * field_score) + emotion_score + penalty_score - negative_score
    score_final = round(_clamp(score_final, -1.0, 1.0), 4)

    # --- Camada conservadora: campo/placar/torcida sozinhos NAO provam jogada
    # ativa. pre-jogo, pos-jogo, estudio, VAR/grafico e torcida/estadio puro
    # tambem tem grama, placar, movimento de camera e emocao na torcida.

    motion_shape = _play_motion_shape(distributed_motion)
    green_centered = _clamp(1.0 - abs(green_ratio - 0.22) / 0.22)
    skin_penalty_factor = 1.0 if skin_ratio < 0.055 else _clamp(1.0 - (skin_ratio - 0.055) / 0.10)

    active_play_score = _clamp(
        green_centered * 0.30
        + motion_shape * 0.30
        + audio_score * 0.15
        + candidate_motion_score * 0.15
        + visual_change_score * 0.10
    )
    active_play_score = _clamp(active_play_score * skin_penalty_factor)
    if green_ratio < 0.06:
        active_play_score *= 0.35
    if green_ratio > 0.45:
        active_play_score *= 0.5
    active_play_score = round(active_play_score, 4)

    wide_shot_signal = _clamp((green_ratio - 0.30) / 0.25) if green_ratio > 0.30 else 0.0
    static_wide_signal = 1.0 if (green_ratio > 0.20 and distributed_motion < 0.05) else 0.0
    big_pan_signal = 1.0 if (green_ratio > 0.20 and distributed_motion > 0.72) else 0.0
    low_energy_signal = _clamp(1.0 - audio_score)
    pregame_postgame_score = _clamp(
        wide_shot_signal * 0.40 + static_wide_signal * 0.25 + big_pan_signal * 0.25 + low_energy_signal * 0.10
    )
    if skin_ratio > 0.09:
        pregame_postgame_score *= 0.4
    pregame_score = postgame_score = round(pregame_postgame_score, 4)

    studio_score = round(_clamp(max(interview_penalty, studio_penalty)), 4)

    graphic_shape_signal = (
        1.0 if (green_ratio < 0.10 and skin_ratio < 0.05) else _clamp(1.0 - (green_ratio + skin_ratio) / 0.20)
    )
    contrast_signal = _clamp((contrast - 0.05) / 0.15)
    low_motion_signal = _clamp(1.0 - distributed_motion / 0.15)
    var_graphics_score = round(
        _clamp(graphic_shape_signal * 0.45 + contrast_signal * 0.30 + low_motion_signal * 0.25), 4
    )

    no_field_signal = _clamp(1.0 - green_ratio / 0.10) if green_ratio < 0.10 else 0.0
    no_face_signal = 1.0 if skin_ratio < 0.06 else 0.0
    energy_signal = _clamp((audio_score + distributed_motion) / 2)
    crowd_only_score = round(_clamp(no_field_signal * 0.35 + no_face_signal * 0.15 + energy_signal * 0.50), 4)

    negative_threshold = 0.55 if strict else 0.62
    category_scores: dict[FootballCategory, float] = {
        "var_or_graphics": var_graphics_score,
        "studio_or_commentary": studio_score,
        "pregame": pregame_score,
        "postgame": postgame_score,
        "crowd_or_stadium_only": crowd_only_score,
    }
    best_negative_label, best_negative_value = max(category_scores.items(), key=lambda item: item[1])

    active_play_min = 0.42 if strict else 0.34
    category: FootballCategory
    if static_penalty > 0.60:
        category = "static_screen"
    elif best_negative_value >= negative_threshold and best_negative_value > active_play_score:
        category = best_negative_label
    elif active_play_score >= active_play_min:
        category = "active_play"
    else:
        category = "unknown"

    if category == "static_screen":
        content_type: FootballContentType = "static_screen"
    elif category != "active_play":
        content_type = category  # "pregame" | "postgame" | "studio_or_commentary" | "var_or_graphics" | "crowd_or_stadium_only" | "unknown"
    elif penalty_score >= 0.72 and emotion_score >= 0.42:
        content_type = "penalty_kick"
    elif save_score >= 0.62 and goal_area_signal:
        content_type = "goalkeeper_save"
    elif chance_score >= 0.62 and audio_score >= 0.55:
        content_type = "big_chance"
    elif field_score >= 0.65 and emotion_score >= 0.50:
        content_type = "goal_or_chance"
    elif field_score >= 0.56 and audio_score >= 0.72 and candidate_motion_score >= 0.45:
        content_type = "celebration"
    else:
        content_type = "match_action"

    active_play_ready = 0.62 if strict else 0.50
    active_play_review = 0.42 if strict else 0.32
    ready_score_final = 0.40 if strict else 0.32

    if category in NON_PLAY_CATEGORIES:
        action: FootballAction = "reject"
    elif category == "active_play" and active_play_score >= active_play_ready and score_final >= ready_score_final:
        action = "save_ready"
    elif category == "active_play" and active_play_score >= active_play_review:
        action = "save_needs_review"
    else:
        action = "reject" if strict else "save_needs_review"

    reasons = []
    if category == "active_play":
        reasons.append("campo/gramado visivel")
        if distributed_motion >= 0.20:
            reasons.append("movimento distribuido")
        if scoreboard:
            reasons.append("placar/layout de transmissao")
        if emotion_score >= 0.45:
            reasons.append("emocao junto do campo")
        if goal_area_signal:
            reasons.append("area/gol/goleiro provavel")
        if set_piece_shape:
            reasons.append("camera relativamente controlada")
        if after_kick_signal:
            reasons.append("explosao/movimento apos lance")
        if penalty_score >= 0.72:
            reasons.append("sinais fortes de penalti")
        elif chance_score >= 0.55 or save_score >= 0.55:
            reasons.append("lance perigoso sem certeza de penalti")
        if active_play_score >= active_play_ready:
            reasons.append("sinais fortes de jogada ativa")
        elif active_play_score >= active_play_review:
            reasons.append("jogada ativa incerta, precisa revisao")
    if category == "pregame":
        reasons.append("provavel pre-jogo: panoramica ampla/parada ou pouca jogada")
    if category == "postgame":
        reasons.append("provavel pos-jogo: panoramica ampla/parada ou pouca jogada")
    if category == "studio_or_commentary":
        reasons.append("provavel estudio/comentarista/entrevista, sem campo em jogada")
    if category == "var_or_graphics":
        reasons.append("provavel tela de VAR/grafico/patrocinador, sem campo em jogada")
    if category == "crowd_or_stadium_only":
        reasons.append("provavel torcida/estadio sem jogada visivel")
    if static_penalty > 0.60:
        reasons.append("tela parada/escura")
    if not reasons:
        reasons.append("sinais visuais insuficientes")

    return FootballContentResult(
        content_type=content_type,
        football_confidence=round(field_score, 4),
        interview_penalty=round(interview_penalty, 4),
        studio_penalty=round(studio_penalty, 4),
        static_penalty=round(static_penalty, 4),
        green_field_ratio=round(green_ratio, 4),
        motion_score=round(distributed_motion, 4),
        visual_change_score=round(visual_change, 4),
        emotion_score=round(emotion_score, 4),
        penalty_score=round(penalty_score, 4),
        scoreboard_like=scoreboard,
        score_final=score_final,
        action=action,
        reason=", ".join(reasons),
        category=category,
        active_play_score=active_play_score,
        pregame_score=pregame_score,
        postgame_score=postgame_score,
        studio_score=studio_score,
        var_graphics_score=var_graphics_score,
        crowd_only_score=crowd_only_score,
    )
