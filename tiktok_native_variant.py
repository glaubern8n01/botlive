from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TikTokNativeVariant:
    source_event_id: str
    master_asset_id: str
    platform_variant_id: str
    output_path: Path
    hook_seconds: float
    duration_seconds: float
    headline: str
    caption: str
    hashtags: tuple[str, ...]
    variant_signature: str


class TikTokNativeVariantBuilder:
    """Creates a genuine editorial cut from a clean master; no evasion transforms."""

    def build(
        self,
        *,
        source_event_id: str,
        master_asset_id: str,
        master_path: Path,
        output_path: Path,
        duration_seconds: float,
        headline: str,
        caption: str,
        hashtags: tuple[str, ...],
        start_seconds: float = 0.0,
        hook_seconds: float = 1.5,
        ffmpeg: str = "ffmpeg",
        render: bool = True,
    ) -> TikTokNativeVariant:
        if not master_path.is_file():
            raise FileNotFoundError(master_path)
        if duration_seconds <= hook_seconds or hook_seconds <= 0:
            raise ValueError("TikTok variant needs a real opening hook and complete duration")
        if not headline.strip() or len(headline.strip()) > 80:
            raise ValueError("TikTok headline must be concise and non-empty")
        payload = {
            "source_event_id": source_event_id,
            "master_asset_id": master_asset_id,
            "start_seconds": round(start_seconds, 3),
            "duration_seconds": round(duration_seconds, 3),
            "hook_seconds": round(hook_seconds, 3),
            "headline": headline.strip(),
            "caption": caption.strip(),
            "hashtags": list(hashtags),
            "editorial_strategy": "tiktok-native-v1",
        }
        signature = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        variant_id = f"tiktok-{signature[:16]}"
        if render:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg, "-y", "-ss", str(start_seconds), "-i", str(master_path),
                    "-t", str(duration_seconds),
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
            )
        return TikTokNativeVariant(
            source_event_id=source_event_id,
            master_asset_id=master_asset_id,
            platform_variant_id=variant_id,
            output_path=output_path,
            hook_seconds=hook_seconds,
            duration_seconds=duration_seconds,
            headline=headline.strip(),
            caption=caption.strip(),
            hashtags=hashtags,
            variant_signature=signature,
        )
