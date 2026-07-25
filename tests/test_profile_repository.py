from __future__ import annotations

from profile_repository import account_from_row, profile_from_row


def test_profile_row_loads_multiple_destinations_and_policies() -> None:
    profile = profile_from_row(
        {
            "profile_id": "sports",
            "name": "Sports",
            "enabled": True,
            "editorial_strategy": "cut",
            "language": "pt-BR",
            "profile_sources": [
                {"source_type": "twitch", "source_ref": "channel", "enabled": True}
            ],
            "profile_render_settings": {
                "aspect_ratio": "9:16",
                "layout": "vertical-fit",
                "min_duration_seconds": 15,
                "max_duration_seconds": 45,
            },
            "profile_destinations": [
                {
                    "id": "dest-1",
                    "platform": "youtube",
                    "enabled": True,
                    "publication_mode": "automatic",
                    "minimum_interval_seconds": 600,
                    "allowed_hours": [12, 18],
                    "timezone": "America/Sao_Paulo",
                    "max_attempts": 4,
                    "platform_accounts": {"account_key": "channel-a"},
                },
                {
                    "id": "dest-2",
                    "platform": "kwai",
                    "enabled": True,
                    "publication_mode": "approval",
                    "platform_accounts": {"account_key": "channel-b"},
                },
            ],
        }
    )
    assert profile.editorial.strategy == "cut"
    assert len(profile.destinations) == 2
    assert profile.destinations[0].minimum_interval_seconds == 600
    assert profile.destinations[0].allowed_hours == (12, 18)
    assert profile.destinations[1].account_key == "channel-b"


def test_account_row_keeps_only_secret_reference() -> None:
    account = account_from_row(
        {
            "id": "account",
            "platform": "kwai",
            "account_key": "principal",
            "secret_ref": "env:KWAI_ACCOUNT",
            "metadata": {"mode": "prepare_only", "official_api_authorized": False},
        }
    )
    assert account.secret_ref == "env:KWAI_ACCOUNT"
    assert account.mode == "prepare_only"
    assert "access_token" not in account.options
