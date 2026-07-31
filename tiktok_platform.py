from __future__ import annotations

from enum import Enum


class TikTokPlatform(str, Enum):
    """Explicitly separate the consumer platform from the future Shop project."""

    STANDARD = "tiktok_standard"
    SHOP = "tiktok_shop"


TIKTOK_STANDARD_ACCOUNT_KEY = "gta6brasilcortes"
TIKTOK_STANDARD_DESTINATION_KEY = "tiktok_standard_gta6"


def is_tiktok_standard(platform: str) -> bool:
    return platform == TikTokPlatform.STANDARD.value


def is_tiktok_shop(platform: str) -> bool:
    return platform == TikTokPlatform.SHOP.value
