from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

import imageio_ffmpeg
import numpy as np
from PIL import Image
from moviepy.editor import VideoFileClip

from clipper import validar_video_final
from profile_config import RenderPolicy
from publisher_contract import ValidationResult


@dataclass(frozen=True)
class ContentEvent:
    event_id: str
    profile_id: str
    source_event_key: str
    source_ref: str
    timestamp_seconds: float
    event_type: str = "highlight"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


MATERIAL_VARIANT_FIELDS = (
    "start_seconds",
    "end_seconds",
    "hook_policy",
    "scene_sequence",
    "crop",
    "narration",
    "context",
    "audio_policy",
    "burned_text",
)


def create_variant_signature(strategy: str, metadata: Mapping[str, Any]) -> str:
    material = {
        key: metadata[key] for key in MATERIAL_VARIANT_FIELDS if key in metadata
    }
    if not material:
        raise ValueError("variant must include at least one material editorial change")
    payload = json.dumps(
        {"strategy": strategy, "material": material},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EditorialVariant:
    variant_id: str
    event_id: str
    profile_id: str
    strategy: str
    variant_signature: str
    editorial_metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        event: ContentEvent,
        strategy: str,
        editorial_metadata: Mapping[str, Any],
        variant_id: Optional[str] = None,
    ) -> "EditorialVariant":
        return cls(
            variant_id=variant_id or str(uuid4()),
            event_id=event.event_id,
            profile_id=event.profile_id,
            strategy=strategy,
            variant_signature=create_variant_signature(strategy, editorial_metadata),
            editorial_metadata=dict(editorial_metadata),
        )


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    profile_id: str
    path: Path
    sha256: str
    duration: float
    width: int
    height: int
    aspect_ratio: str
    codec: Optional[str]
    audio_codec: Optional[str]
    filesize: int
    validation_status: str
    event_id: Optional[str] = None
    variant_id: Optional[str] = None
    perceptual_hash: Optional[str] = None
    audio_fingerprint: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def perceptual_video_hash(path: Path, samples: int = 5) -> Optional[str]:
    try:
        clip = VideoFileClip(str(path), audio=False)
    except Exception:
        return None
    try:
        duration = float(clip.duration or 0)
        if duration <= 0:
            return None
        hashes: list[str] = []
        for timestamp in np.linspace(0.1, max(0.1, duration - 0.1), samples):
            frame = Image.fromarray(clip.get_frame(float(timestamp))).convert("L").resize((9, 8))
            pixels = np.asarray(frame)
            bits = pixels[:, 1:] > pixels[:, :-1]
            hashes.append(f"{int(''.join('1' if bit else '0' for bit in bits.flat), 2):016x}")
        return hashlib.sha256("|".join(hashes).encode()).hexdigest()[:32]
    finally:
        clip.close()


def _probe(path: Path) -> dict[str, Any]:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-i",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    output = result.stderr
    video_match = re.search(
        r"Stream .* Video: ([^,\s]+).*?(\d{2,5})x(\d{2,5})", output
    )
    audio_match = re.search(r"Stream .* Audio: ([^,\s]+)", output)
    duration_match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", output)
    if not video_match or not duration_match:
        raise ValueError("media probe failed")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return {
        "format": {"duration": duration},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": video_match.group(1),
                "width": int(video_match.group(2)),
                "height": int(video_match.group(3)),
            },
            *(
                [{"codec_type": "audio", "codec_name": audio_match.group(1)}]
                if audio_match
                else []
            ),
        ],
    }


def inspect_media_asset(
    path: str | Path,
    profile_id: str,
    event_id: Optional[str] = None,
    variant_id: Optional[str] = None,
    asset_id: Optional[str] = None,
) -> MediaAsset:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    probe = _probe(path)
    video = next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"),
        {},
    )
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    aspect_ratio = "9:16" if width and height and abs(width / height - 9 / 16) < 0.02 else "other"
    return MediaAsset(
        asset_id=asset_id or str(uuid4()),
        profile_id=profile_id,
        event_id=event_id,
        variant_id=variant_id,
        path=path,
        sha256=sha256_file(path),
        perceptual_hash=perceptual_video_hash(path),
        duration=float((probe.get("format") or {}).get("duration") or 0),
        width=width,
        height=height,
        aspect_ratio=aspect_ratio,
        codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
        filesize=path.stat().st_size,
        validation_status="pending",
    )


class MediaAssetValidator:
    def validate(self, asset: MediaAsset, policy: RenderPolicy) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        if not asset.path.is_file() or asset.filesize <= 0:
            errors.append("asset file is missing or empty")
        if asset.duration < policy.min_duration_seconds:
            errors.append("asset duration is below profile minimum")
        if asset.duration > policy.max_duration_seconds:
            errors.append("asset duration exceeds profile maximum")
        if asset.width <= 0 or asset.height <= 0 or not asset.codec:
            errors.append("asset video stream is invalid")
        if policy.aspect_ratio == "9:16" and asset.aspect_ratio != "9:16":
            errors.append("asset is not 9:16")
        if not asset.audio_codec:
            warnings.append("asset has no audio stream")
        if not errors and asset.path.is_file():
            legacy = validar_video_final(
                asset.path,
                require_audio=False,
                min_duration_seconds=max(0, policy.min_duration_seconds - 0.01),
                min_size_bytes=1,
            )
            if not legacy.valid:
                errors.append(legacy.reason)
        return ValidationResult(not errors, tuple(errors), tuple(warnings))


def content_fingerprint(asset: MediaAsset) -> str:
    payload = "|".join(
        filter(None, (asset.sha256, asset.perceptual_hash, asset.audio_fingerprint))
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def publication_key(
    platform: str,
    account_id: str,
    profile_id: str,
    variant_id: str,
    fingerprint: str,
) -> str:
    normalized = "|".join(
        part.strip().lower()
        for part in (platform, account_id, profile_id, variant_id, fingerprint)
    )
    return hashlib.sha256(normalized.encode()).hexdigest()
