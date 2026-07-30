from __future__ import annotations

import subprocess
from pathlib import Path

from kwai_media_validation import analyze_audio, required_text_gates


def _media(path: Path, volume: str) -> Path:
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x568:d=2",
        "-f", "lavfi", "-i", f"sine=frequency=800:duration=2,volume={volume}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True)
    return path


def test_silent_aac_is_rejected(tmp_path: Path) -> None:
    media = tmp_path / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x568:d=2",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2",
        "-c:v", "libx264", "-c:a", "aac", str(media),
    ], check=True, capture_output=True)
    assert analyze_audio(media).status == "rejected_silent_audio"


def test_audio_at_minus_91_db_is_rejected(tmp_path: Path) -> None:
    assert analyze_audio(_media(tmp_path / "low.mp4", "-91dB")).status in {
        "rejected_silent_audio", "rejected_low_audio"
    }


def test_audible_audio_passes(tmp_path: Path) -> None:
    assert analyze_audio(_media(tmp_path / "audible.mp4", "-8dB")).status == "valid"


def test_required_text_gates(tmp_path: Path) -> None:
    subtitle = tmp_path / "captions.ass"
    frames = [tmp_path / f"frame-{index}.jpg" for index in range(5)]
    assert "rejected_missing_headline" in required_text_gates("", subtitle, frames)
    assert "rejected_missing_captions" in required_text_gates("Headline", subtitle, frames)
    subtitle.write_text("[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Texto" * 2)
    for frame in frames:
        frame.write_bytes(b"x" * 1200)
    assert required_text_gates("Headline", subtitle, frames) == []


def test_missing_audio_is_rejected(tmp_path: Path) -> None:
    media = tmp_path / "video-only.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x568:d=1",
        "-c:v", "libx264", "-an", str(media),
    ], check=True, capture_output=True)
    assert analyze_audio(media).status == "rejected_missing_audio"


def test_missing_or_broken_validation_frames_are_rejected(tmp_path: Path) -> None:
    subtitle = tmp_path / "captions.ass"
    subtitle.write_text("[Events]\n" + "Dialogue: texto\n" * 10)
    frames = [tmp_path / f"frame-{index}.jpg" for index in range(5)]
    for frame in frames[:-1]:
        frame.write_bytes(b"x" * 1200)
    assert "rejected_visual_validation" in required_text_gates("Headline", subtitle, frames)
