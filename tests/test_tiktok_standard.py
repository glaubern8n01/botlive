from __future__ import annotations

import os
from pathlib import Path

import pytest

from publisher_adapters import legacy_registry
from publisher_contract import PlatformAccount, PublishJob, PublishStatus
from tiktok_native_variant import TikTokNativeVariantBuilder
from tiktok_oauth import EncryptedTokenStore, OAuthStateStore, TikTokOAuthClient
from tiktok_platform import TikTokPlatform
from tiktok_standard_publisher import TikTokStandardPublisher, upload_geometry


def job(tmp_path: Path, *, mode: str = "prepare_only") -> PublishJob:
    asset = tmp_path / "gta-clean.mp4"
    asset.write_bytes(b"\0" * 1024)
    account = PlatformAccount(
        "standard-account", TikTokPlatform.STANDARD.value, "gta6brasilcortes",
        "tiktok-encrypted:gta6brasilcortes", mode=mode,
        options={"rights_status": "owned"},
    )
    return PublishJob(
        "job-standard", "gta6_cortes", TikTokPlatform.STANDARD.value,
        account, asset, "pub-standard", event_id="event-1", variant_id="variant-1",
    )


def test_standard_and_shop_are_isolated() -> None:
    assert TikTokPlatform.STANDARD != TikTokPlatform.SHOP
    assert TikTokPlatform.STANDARD.value != TikTokPlatform.SHOP.value
    assert "tiktok_shop" not in legacy_registry().platforms()
    assert "tiktok_standard" in legacy_registry().platforms()


def test_prepare_only_never_calls_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = TikTokStandardPublisher()
    monkeypatch.setattr(publisher, "_api", lambda *args, **kwargs: pytest.fail("network called"))
    result = publisher.publish(job(tmp_path), {})
    assert result.status is PublishStatus.PENDING
    assert result.metadata["network_called"] is False


def test_api_modes_remain_gated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_STANDARD_API_ENABLED", "0")
    with pytest.raises(Exception, match="API is disabled"):
        TikTokStandardPublisher().publish(job(tmp_path, mode="upload_draft"), {"access_token": "secret"})


def test_upload_geometry_respects_official_chunk_rules() -> None:
    assert upload_geometry(4 * 1024 * 1024) == (4 * 1024 * 1024, 1)
    chunk, count = upload_geometry(70 * 1024 * 1024)
    assert 5 * 1024 * 1024 <= chunk <= 64 * 1024 * 1024
    assert count > 1


def test_oauth_state_is_short_lived_and_single_use(tmp_path: Path) -> None:
    store = OAuthStateStore(tmp_path, ttl_seconds=60)
    state = store.issue()
    assert store.consume(state.value)
    assert not store.consume(state.value)
    assert not store.consume("wrong-state")


def test_tokens_are_encrypted_and_ui_status_has_no_tokens(tmp_path: Path) -> None:
    store = EncryptedTokenStore(tmp_path, "test-only-key")
    store.save("gta6brasilcortes", {
        "access_token": "access-super-secret",
        "refresh_token": "refresh-super-secret",
        "open_id": "open-id", "scope": "user.info.basic,video.upload", "expires_at": 4102444800,
    })
    raw = (tmp_path / "gta6brasilcortes.token").read_bytes()
    assert b"access-super-secret" not in raw
    status = store.status("gta6brasilcortes")
    assert "access_token" not in status and "refresh_token" not in status
    assert status["token_valid"]


def test_authorization_url_uses_official_endpoint_and_state() -> None:
    url = TikTokOAuthClient("client", "secret", "https://example.test/callback").authorization_url(
        "state-value"
    )
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
    assert "state=state-value" in url
    assert "client_secret" not in url and "secret" not in url


def test_native_variant_has_destination_specific_signature(tmp_path: Path) -> None:
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master")
    builder = TikTokNativeVariantBuilder()
    first = builder.build(
        source_event_id="event", master_asset_id="master", master_path=master,
        output_path=tmp_path / "tiktok.mp4", duration_seconds=25, headline="GTA 6 em detalhes",
        caption="O que você percebeu?", hashtags=("#gta6",), render=False,
    )
    second = builder.build(
        source_event_id="event", master_asset_id="master", master_path=master,
        output_path=tmp_path / "tiktok-2.mp4", duration_seconds=23, headline="O detalhe de GTA 6",
        caption="O que você percebeu?", hashtags=("#gta6",), render=False,
    )
    assert first.variant_signature != second.variant_signature
    assert first.master_asset_id == second.master_asset_id == "master"


def test_migration_contains_no_shop_operational_records() -> None:
    sql = Path("supabase/migrations/20260730_tiktok_standard_gta.sql").read_text(encoding="utf-8")
    before_comment = sql.split("-- Não há conta", 1)[0]
    assert "insert into public.platform_accounts" in sql
    assert "'tiktok_shop'" not in before_comment
    assert "access_token text" not in sql and "refresh_token text" not in sql
