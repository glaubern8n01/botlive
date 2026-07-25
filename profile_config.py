from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


SUPPORTED_ASPECT_RATIOS = {"original", "9:16"}
SUPPORTED_LAYOUTS = {"original", "vertical-fit", "vertical-crop"}
SUPPORTED_PUBLICATION_MODES = {"disabled", "manual", "approval", "automatic"}


@dataclass(frozen=True)
class EditorialPolicy:
    """Editorial choices owned by one profile.

    ``settings`` is intentionally extensible so niche-specific options can be
    introduced without changing the stable core contract.
    """

    strategy: str = "default"
    language: str = "pt-BR"
    captions_enabled: bool = True
    headline_enabled: bool = True
    brand: Optional[str] = None
    cta: Optional[str] = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy.strip():
            raise ValueError("editorial strategy must not be empty")
        if not self.language.strip():
            raise ValueError("editorial language must not be empty")


@dataclass(frozen=True)
class RenderPolicy:
    aspect_ratio: str = "9:16"
    layout: str = "vertical-fit"
    min_duration_seconds: int = 5
    max_duration_seconds: int = 60
    target_height: Optional[int] = 720
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            raise ValueError(f"unsupported aspect ratio: {self.aspect_ratio}")
        if self.layout not in SUPPORTED_LAYOUTS:
            raise ValueError(f"unsupported render layout: {self.layout}")
        if self.min_duration_seconds < 0:
            raise ValueError("minimum duration must be non-negative")
        if self.max_duration_seconds <= 0:
            raise ValueError("maximum duration must be positive")
        if self.min_duration_seconds > self.max_duration_seconds:
            raise ValueError("minimum duration cannot exceed maximum duration")


@dataclass(frozen=True)
class SourceConfig:
    source_type: str
    source_ref: str
    enabled: bool = True
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_type.strip() or not self.source_ref.strip():
            raise ValueError("source type and reference must not be empty")


@dataclass(frozen=True)
class DestinationConfig:
    platform: str
    account_key: str = "principal"
    enabled: bool = False
    publication_mode: str = "disabled"
    max_posts_per_day: Optional[int] = None
    schedule: Mapping[str, Any] = field(default_factory=dict)
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.platform.strip() or not self.account_key.strip():
            raise ValueError("destination platform and account must not be empty")
        if self.publication_mode not in SUPPORTED_PUBLICATION_MODES:
            raise ValueError(f"unsupported publication mode: {self.publication_mode}")
        if self.max_posts_per_day is not None and self.max_posts_per_day < 0:
            raise ValueError("maximum posts per day must be non-negative")


@dataclass(frozen=True)
class ProfileConfig:
    profile_id: str
    name: str
    description: Optional[str] = None
    niche: Optional[str] = None
    enabled: bool = False
    editorial: EditorialPolicy = field(default_factory=EditorialPolicy)
    render: RenderPolicy = field(default_factory=RenderPolicy)
    sources: tuple[SourceConfig, ...] = ()
    destinations: tuple[DestinationConfig, ...] = ()
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.name.strip():
            raise ValueError("profile id and name must not be empty")


def default_profile_from_legacy(row: Mapping[str, Any]) -> ProfileConfig:
    """Adapt the existing singleton ``vigia_config`` without changing it.

    The Vigia keeps consuming its legacy dataclass in phase 2. This adapter is
    the compatibility boundary for new multi-profile consumers.
    """

    niche = str(row.get("content_filter") or "none")
    clip_duration = int(row.get("clip_duration_seconds") or 45)
    youtube_enabled = bool(row.get("post_youtube_enabled", False))
    instagram_enabled = bool(row.get("post_instagram_enabled", False))
    destinations = (
        DestinationConfig(
            platform="youtube",
            enabled=youtube_enabled,
            publication_mode="automatic" if youtube_enabled else "disabled",
            max_posts_per_day=int(row.get("max_posts_per_day") or 0),
            settings={"visibility": row.get("post_visibilidade") or "unlisted"},
        ),
        DestinationConfig(
            platform="instagram",
            enabled=instagram_enabled,
            publication_mode="approval" if instagram_enabled else "disabled",
        ),
    )
    return ProfileConfig(
        profile_id="default",
        name="Default",
        description="Perfil de compatibilidade com vigia_config",
        niche=None if niche == "none" else niche,
        enabled=bool(row.get("enabled", False)),
        editorial=EditorialPolicy(
            strategy="default",
            language=str(row.get("discovery_language") or "pt"),
            brand=row.get("credito_canal"),
        ),
        render=RenderPolicy(
            aspect_ratio="9:16",
            layout="vertical-fit",
            min_duration_seconds=5,
            max_duration_seconds=max(5, clip_duration),
            target_height=int(row["target_height"]) if row.get("target_height") else None,
        ),
        sources=(
            SourceConfig(
                source_type="legacy_vigia_channels",
                source_ref="vigia_channels",
                enabled=bool(row.get("manual_channels_enabled", True)),
            ),
        ),
        destinations=destinations,
        settings={"legacy_config_id": int(row.get("id") or 1)},
    )
