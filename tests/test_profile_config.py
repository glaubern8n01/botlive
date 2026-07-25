from __future__ import annotations

from pathlib import Path

import pytest

from profile_config import (
    DestinationConfig,
    EditorialPolicy,
    ProfileConfig,
    RenderPolicy,
    SourceConfig,
    default_profile_from_legacy,
)


def test_default_profile_preserves_legacy_vigia_configuration() -> None:
    profile = default_profile_from_legacy(
        {
            "id": 1,
            "enabled": True,
            "manual_channels_enabled": True,
            "content_filter": "gta",
            "discovery_language": "pt",
            "clip_duration_seconds": 45,
            "target_height": 720,
            "post_youtube_enabled": True,
            "post_instagram_enabled": False,
            "post_visibilidade": "unlisted",
            "max_posts_per_day": 4,
            "credito_canal": "@canal",
        }
    )

    assert profile.profile_id == "default"
    assert profile.enabled is True
    assert profile.niche == "gta"
    assert profile.render.aspect_ratio == "9:16"
    assert profile.render.max_duration_seconds == 45
    assert profile.sources[0].source_ref == "vigia_channels"
    assert profile.destinations[0] == DestinationConfig(
        platform="youtube",
        enabled=True,
        publication_mode="automatic",
        max_posts_per_day=4,
        settings={"visibility": "unlisted"},
    )
    assert profile.destinations[1].publication_mode == "disabled"


def test_profile_supports_multiple_sources_and_destinations() -> None:
    profile = ProfileConfig(
        profile_id="sports_br",
        name="Sports BR",
        editorial=EditorialPolicy(strategy="highlights"),
        render=RenderPolicy(min_duration_seconds=15, max_duration_seconds=50),
        sources=(
            SourceConfig(source_type="twitch", source_ref="channel-one"),
            SourceConfig(source_type="youtube", source_ref="channel-two"),
        ),
        destinations=(
            DestinationConfig(platform="youtube", account_key="sports"),
            DestinationConfig(platform="instagram", account_key="sports"),
        ),
    )

    assert len(profile.sources) == 2
    assert {destination.platform for destination in profile.destinations} == {
        "youtube",
        "instagram",
    }


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [(20, 10), (-1, 10), (0, 0)],
)
def test_render_policy_rejects_invalid_duration_ranges(minimum: int, maximum: int) -> None:
    with pytest.raises(ValueError):
        RenderPolicy(min_duration_seconds=minimum, max_duration_seconds=maximum)


def test_multi_profile_migration_is_additive_and_seeds_default() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "supabase"
        / "migrations"
        / "20260725_multi_profile.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists public.profiles" in migration
    assert "create table if not exists public.profile_sources" in migration
    assert "create table if not exists public.profile_destinations" in migration
    assert "'default'" in migration
    assert "from public.vigia_config" in migration
    assert "drop table" not in migration
