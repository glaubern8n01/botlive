from __future__ import annotations

from pathlib import Path

import pytest

from media_domain import (
    ContentEvent,
    EditorialVariant,
    MediaAsset,
    MediaAssetValidator,
    content_fingerprint,
    create_variant_signature,
    publication_key,
    sha256_file,
)
from profile_config import RenderPolicy


def _asset(tmp_path: Path, **overrides) -> MediaAsset:
    path = tmp_path / "asset.mp4"
    path.write_bytes(b"video")
    values = dict(
        asset_id="asset-1",
        profile_id="profile",
        path=path,
        sha256=sha256_file(path),
        duration=30,
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        codec="h264",
        audio_codec="aac",
        filesize=path.stat().st_size,
        validation_status="pending",
        perceptual_hash="abc",
    )
    values.update(overrides)
    return MediaAsset(**values)


def test_variant_signature_ignores_cosmetic_only_fields() -> None:
    with pytest.raises(ValueError):
        create_variant_signature("cut", {"font": "Anton", "color": "red", "title": "A"})


def test_materially_different_variants_have_different_signatures() -> None:
    event = ContentEvent("event-1", "profile", "source:100", "source", 100)
    short = EditorialVariant.create(
        event, "cut", {"start_seconds": 90, "end_seconds": 110}
    )
    complete = EditorialVariant.create(
        event, "cut", {"start_seconds": 75, "end_seconds": 120}
    )
    assert short.variant_signature != complete.variant_signature


def test_publication_key_is_stable_and_destination_specific(tmp_path: Path) -> None:
    fingerprint = content_fingerprint(_asset(tmp_path))
    first = publication_key("youtube", "a", "profile", "variant", fingerprint)
    assert first == publication_key("youtube", "a", "profile", "variant", fingerprint)
    assert first != publication_key("youtube", "b", "profile", "variant", fingerprint)


def test_asset_validator_enforces_profile_duration_and_ratio(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "media_domain.validar_video_final",
        lambda *_args, **_kwargs: type("Result", (), {"valid": True, "reason": "ok"})(),
    )
    validator = MediaAssetValidator()
    policy = RenderPolicy(min_duration_seconds=10, max_duration_seconds=40)
    assert validator.validate(_asset(tmp_path), policy).valid
    too_short = _asset(tmp_path, duration=5)
    assert validator.validate(too_short, policy).valid is False
    horizontal = _asset(tmp_path, aspect_ratio="other", width=1920, height=1080)
    assert validator.validate(horizontal, policy).valid is False
