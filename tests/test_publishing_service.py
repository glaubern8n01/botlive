from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from feature_flags import FeatureFlags
from media_domain import ContentEvent, EditorialVariant, MediaAsset
from profile_config import (
    DestinationConfig,
    EditorialPolicy,
    ProfileConfig,
    RenderPolicy,
)
from publication_queue import InMemoryPublicationQueue
from publisher_contract import PlatformAccount
from publishing_service import (
    DestinationUsage,
    PublicationPlanner,
    destination_allowed,
)


NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def _variant():
    event = ContentEvent("event", "profile", "source:1", "source", 10)
    return EditorialVariant.create(
        event, "cut", {"start_seconds": 0, "end_seconds": 20}
    )


def _asset(tmp_path: Path):
    path = tmp_path / "asset.mp4"
    path.write_bytes(b"video")
    return MediaAsset(
        "asset", "profile", path, "sha", 20, 1080, 1920, "9:16",
        "h264", "aac", 5, "valid", perceptual_hash="perceptual"
    )


def _profile():
    return ProfileConfig(
        "profile",
        "Profile",
        editorial=EditorialPolicy(),
        render=RenderPolicy(),
        destinations=(
            DestinationConfig(
                "youtube", "a", True, "automatic", max_posts_per_day=5
            ),
            DestinationConfig(
                "instagram", "b", True, "approval", max_posts_per_day=3
            ),
        ),
    )


def test_planner_creates_independent_job_per_destination(tmp_path: Path) -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    planner = PublicationPlanner(
        queue, FeatureFlags(multi_profile=True, publication_queue=True)
    )
    accounts = {
        ("youtube", "a"): PlatformAccount("yt-a", "youtube", "a", "env:YT_A"),
        ("instagram", "b"): PlatformAccount("ig-b", "instagram", "b", "env:IG_B"),
    }
    result = planner.plan(_profile(), _variant(), _asset(tmp_path), accounts, now=NOW)
    assert len(result.jobs) == 2
    assert {item.job.account.account_id for item in result.jobs} == {"yt-a", "ig-b"}
    assert {item.job.account.mode for item in result.jobs} == {"api", "prepare_only"}


def test_planner_deduplicates_same_publication_key(tmp_path: Path) -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    planner = PublicationPlanner(
        queue, FeatureFlags(multi_profile=True, publication_queue=True)
    )
    accounts = {
        ("youtube", "a"): PlatformAccount("yt-a", "youtube", "a"),
        ("instagram", "b"): PlatformAccount("ig-b", "instagram", "b"),
    }
    variant = _variant()
    planner.plan(_profile(), variant, _asset(tmp_path), accounts, now=NOW)
    repeated = planner.plan(_profile(), variant, _asset(tmp_path), accounts, now=NOW)
    assert repeated.jobs == ()
    assert repeated.duplicates == 2


def test_destination_policy_respects_limits_and_interval() -> None:
    destination = DestinationConfig(
        "youtube",
        enabled=True,
        publication_mode="automatic",
        max_posts_per_day=2,
        minimum_interval_seconds=600,
    )
    blocked, reason, _ = destination_allowed(
        destination, DestinationUsage(published_today=2), NOW
    )
    assert blocked is False
    assert reason == "daily limit reached"
    allowed, _, scheduled = destination_allowed(
        destination,
        DestinationUsage(last_published_at=NOW - timedelta(seconds=60)),
        NOW,
    )
    assert allowed is True
    assert scheduled == NOW + timedelta(seconds=540)


def test_planner_is_inert_when_features_are_disabled(tmp_path: Path) -> None:
    result = PublicationPlanner(
        InMemoryPublicationQueue(), FeatureFlags()
    ).plan(_profile(), _variant(), _asset(tmp_path), {})
    assert result.jobs == ()
    assert "features" in result.skipped
