"""Gates pós-renderização para mídia vertical do Kwai CUT."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


SILENCE_DB = float(os.getenv("KWAI_AUDIO_SILENCE_DB", "-80"))
MIN_MEAN_DB = float(os.getenv("KWAI_AUDIO_MIN_MEAN_DB", "-45"))
MIN_PEAK_DB = float(os.getenv("KWAI_AUDIO_MIN_PEAK_DB", "-35"))
MAX_DURATION_DELTA = float(os.getenv("KWAI_AUDIO_MAX_DURATION_DELTA", "0.75"))


@dataclass(frozen=True)
class AudioAnalysis:
    mean_db: float | None
    peak_db: float | None
    audio_duration: float | None
    video_duration: float

    @property
    def status(self) -> str:
        if self.mean_db is None or self.peak_db is None or self.audio_duration is None:
            return "rejected_missing_audio"
        if self.mean_db <= SILENCE_DB or self.peak_db <= SILENCE_DB:
            return "rejected_silent_audio"
        if self.mean_db < MIN_MEAN_DB or self.peak_db < MIN_PEAK_DB:
            return "rejected_low_audio"
        if abs(self.audio_duration - self.video_duration) > MAX_DURATION_DELTA:
            return "rejected_audio_duration"
        return "valid"


def _duration(path: Path, selector: str) -> float | None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", selector, "-show_entries",
         "stream=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def analyze_audio(path: Path) -> AudioAnalysis:
    video_duration = _duration(path, "v:0") or 0.0
    audio_duration = _duration(path, "a:0")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    mean = re.search(r"mean_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", output)
    peak = re.search(r"max_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", output)

    def number(match: re.Match[str] | None) -> float | None:
        if not match or match.group(1) == "-inf":
            return -999.0 if match else None
        return float(match.group(1))

    return AudioAnalysis(number(mean), number(peak), audio_duration, video_duration)


def required_text_gates(headline: str, subtitle_file: Path, frames: list[Path]) -> list[str]:
    errors: list[str] = []
    if not headline.strip():
        errors.append("rejected_missing_headline")
    if not subtitle_file.is_file() or subtitle_file.stat().st_size < 80:
        errors.append("rejected_missing_captions")
    if len(frames) < 5 or any(not frame.is_file() or frame.stat().st_size < 1000 for frame in frames):
        errors.append("rejected_visual_validation")
    return errors
