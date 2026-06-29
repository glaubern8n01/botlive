from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

try:
    from moviepy.editor import VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import VideoFileClip


@dataclass(frozen=True)
class HighlightCandidate:
    timestamp_seconds: int
    score: float
    audio_score: float
    motion_score: float
    brightness_score: float
    reason: str


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    array = np.asarray(values, dtype=float)
    low = float(np.percentile(array, 10))
    high = float(np.percentile(array, 95))
    if high <= low:
        return [0.0 for _ in values]
    normalized = np.clip((array - low) / (high - low), 0.0, 1.0)
    return normalized.tolist()


def _frame_features(clip: VideoFileClip, timestamp: float, previous_gray: Optional[np.ndarray]) -> tuple[float, float, np.ndarray]:
    frame = clip.get_frame(timestamp)
    image = Image.fromarray(frame).resize((160, 90))
    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
    brightness = float(np.mean(gray))

    if previous_gray is None:
        motion = 0.0
    else:
        motion = float(np.mean(np.abs(gray - previous_gray)))

    return motion, brightness, gray


def _audio_rms(clip: VideoFileClip, start: float, end: float) -> float:
    if clip.audio is None:
        return 0.0

    safe_start = max(0.0, start)
    safe_end = min(float(clip.duration), end)
    if safe_end <= safe_start:
        return 0.0

    audio = clip.audio.subclip(safe_start, safe_end)
    chunks = list(audio.iter_chunks(fps=11025, chunksize=50000))
    if not chunks:
        return 0.0
    samples = np.vstack(chunks)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def detectar_melhores_momentos(
    video_path: str | Path,
    max_cortes: int = 8,
    sample_every_seconds: int = 3,
    analysis_window_seconds: int = 6,
    min_gap_seconds: int = 45,
    ignore_first_seconds: int = 20,
    min_score: float = 0.0,
) -> list[HighlightCandidate]:
    """Analisa audio + movimento + mudanca visual e retorna timestamps fortes."""
    video_path = Path(video_path)
    clip = VideoFileClip(str(video_path))

    try:
        duration = int(clip.duration or 0)
        if duration <= ignore_first_seconds + analysis_window_seconds:
            return []

        timestamps = list(range(ignore_first_seconds, duration, sample_every_seconds))
        raw_audio: list[float] = []
        raw_motion: list[float] = []
        raw_brightness_delta: list[float] = []
        previous_gray: Optional[np.ndarray] = None
        previous_brightness: Optional[float] = None

        for timestamp in timestamps:
            motion, brightness, gray = _frame_features(clip, timestamp, previous_gray)
            audio = _audio_rms(
                clip,
                start=timestamp - analysis_window_seconds / 2,
                end=timestamp + analysis_window_seconds / 2,
            )
            brightness_delta = 0.0 if previous_brightness is None else abs(brightness - previous_brightness)

            raw_audio.append(audio)
            raw_motion.append(motion)
            raw_brightness_delta.append(brightness_delta)
            previous_gray = gray
            previous_brightness = brightness

        audio_scores = _normalize(raw_audio)
        motion_scores = _normalize(raw_motion)
        brightness_scores = _normalize(raw_brightness_delta)

        candidates: list[HighlightCandidate] = []
        for timestamp, audio_score, motion_score, brightness_score in zip(
            timestamps,
            audio_scores,
            motion_scores,
            brightness_scores,
        ):
            score = (audio_score * 0.55) + (motion_score * 0.35) + (brightness_score * 0.10)
            reasons = []
            if audio_score >= 0.65:
                reasons.append("audio alto")
            if motion_score >= 0.65:
                reasons.append("muito movimento")
            if brightness_score >= 0.65:
                reasons.append("mudanca visual")
            if not reasons:
                reasons.append("score combinado")

            candidates.append(
                HighlightCandidate(
                    timestamp_seconds=int(timestamp),
                    score=round(float(score), 4),
                    audio_score=round(float(audio_score), 4),
                    motion_score=round(float(motion_score), 4),
                    brightness_score=round(float(brightness_score), 4),
                    reason=", ".join(reasons),
                )
            )

        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        selected: list[HighlightCandidate] = []
        for candidate in ranked:
            if candidate.score <= 0 or candidate.score < min_score:
                continue
            too_close = any(
                abs(candidate.timestamp_seconds - chosen.timestamp_seconds) < min_gap_seconds
                for chosen in selected
            )
            if too_close:
                continue
            selected.append(candidate)
            if len(selected) >= max_cortes:
                break

        return sorted(selected, key=lambda item: item.timestamp_seconds)
    finally:
        clip.close()
