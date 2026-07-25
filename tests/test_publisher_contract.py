from __future__ import annotations

import json
from pathlib import Path

import pytest

from feature_flags import FeatureFlags
from publisher_adapters import InstagramPublisher, YouTubePublisher
from publisher_contract import (
    PlatformAccount,
    PublishJob,
    PublisherRegistry,
)
from secret_provider import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    LocalTokenSecretProvider,
)


def _job(tmp_path: Path, platform: str = "youtube") -> PublishJob:
    asset = tmp_path / "asset.mp4"
    asset.write_bytes(b"video")
    return PublishJob(
        job_id="job-1",
        profile_id="default",
        platform=platform,
        account=PlatformAccount("account-1", platform, "principal", mode="dry_run"),
        asset_path=asset,
        publication_key="key-1",
    )


def test_registry_resolves_typed_publishers() -> None:
    registry = PublisherRegistry()
    registry.register(YouTubePublisher())
    registry.register(InstagramPublisher())
    assert registry.platforms() == ("instagram", "youtube")
    assert registry.get("youtube").capabilities.supports_draft is True


def test_adapters_validate_asset_without_external_calls(tmp_path: Path) -> None:
    assert YouTubePublisher().validate(_job(tmp_path)).valid is True
    missing = _job(tmp_path, "instagram")
    missing.asset_path.unlink()
    assert InstagramPublisher().validate(missing).valid is False


def test_environment_secret_provider_supports_string_and_json(monkeypatch) -> None:
    provider = EnvironmentSecretProvider()
    monkeypatch.setenv("BOTLIVE_TEST_SECRET", "abc")
    assert provider.resolve("env:BOTLIVE_TEST_SECRET") == {"token": "abc"}
    monkeypatch.setenv("BOTLIVE_TEST_SECRET", '{"client_id":"id","token":"value"}')
    assert provider.resolve("env:BOTLIVE_TEST_SECRET")["client_id"] == "id"


def test_local_token_provider_is_restricted_to_token_root(tmp_path: Path) -> None:
    provider = LocalTokenSecretProvider(tmp_path)
    token = tmp_path / "youtube" / "principal.json"
    token.parent.mkdir()
    token.write_text(json.dumps({"token": "secret"}), encoding="utf-8")
    assert provider.resolve("local-token:youtube/principal.json")["token"] == "secret"
    with pytest.raises(Exception):
        provider.resolve("local-token:../outside.json")


def test_composite_provider_routes_by_reference(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOTLIVE_TEST_SECRET", "abc")
    provider = CompositeSecretProvider(
        EnvironmentSecretProvider(), LocalTokenSecretProvider(tmp_path)
    )
    assert provider.resolve("env:BOTLIVE_TEST_SECRET") == {"token": "abc"}


def test_all_new_feature_flags_are_safe_by_default(monkeypatch) -> None:
    for name in (
        "MULTI_PROFILE_ENABLED",
        "PUBLICATION_QUEUE_ENABLED",
        "NEW_PUBLISHER_CONTRACT_ENABLED",
        "KWAI_ENABLED",
        "KWAI_API_ENABLED",
        "CUT_ENABLED",
        "NARRASTARS_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    assert FeatureFlags.from_env() == FeatureFlags()
