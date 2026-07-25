from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol


class PublishStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PublishError(RuntimeError):
    pass


class RetryablePublishError(PublishError):
    pass


class PermanentPublishError(PublishError):
    pass


class AuthenticationError(PermanentPublishError):
    pass


class RateLimitError(RetryablePublishError):
    def __init__(self, message: str, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AssetValidationError(PermanentPublishError):
    pass


@dataclass(frozen=True)
class PublisherCapabilities:
    accepts_video: bool = True
    accepts_cover: bool = False
    accepts_title: bool = True
    accepts_caption: bool = True
    min_duration_seconds: Optional[float] = None
    max_duration_seconds: Optional[float] = None
    aspect_ratios: tuple[str, ...] = ()
    max_file_size_bytes: Optional[int] = None
    asynchronous_processing: bool = False
    supports_polling: bool = False
    supports_draft: bool = False
    privacy_options: tuple[str, ...] = ()
    supports_scheduling: bool = False


@dataclass(frozen=True)
class PlatformAccount:
    account_id: str
    platform: str
    account_key: str
    secret_ref: Optional[str] = None
    mode: str = "api"
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishJob:
    job_id: str
    profile_id: str
    platform: str
    account: PlatformAccount
    asset_path: Path
    publication_key: str
    event_id: Optional[str] = None
    variant_id: Optional[str] = None
    asset_id: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    cover_path: Optional[Path] = None
    privacy: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishResult:
    status: PublishStatus
    external_id: Optional[str] = None
    remote_url: Optional[str] = None
    remote_status: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    published_at: Optional[datetime] = None

    @classmethod
    def published(
        cls, external_id: str, remote_url: Optional[str] = None, **metadata: Any
    ) -> "PublishResult":
        return cls(
            status=PublishStatus.PUBLISHED,
            external_id=external_id,
            remote_url=remote_url,
            metadata=metadata,
            published_at=datetime.now(timezone.utc),
        )


class Publisher(Protocol):
    platform: str
    capabilities: PublisherCapabilities

    def validate(self, job: PublishJob) -> ValidationResult: ...

    def publish(self, job: PublishJob, secrets: Mapping[str, str]) -> PublishResult: ...

    def get_status(
        self, external_id: str, account: PlatformAccount, secrets: Mapping[str, str]
    ) -> PublishResult: ...


class PublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[str, Publisher] = {}

    def register(self, publisher: Publisher) -> None:
        if publisher.platform in self._publishers:
            raise ValueError(f"publisher already registered: {publisher.platform}")
        self._publishers[publisher.platform] = publisher

    def get(self, platform: str) -> Publisher:
        try:
            return self._publishers[platform]
        except KeyError as exc:
            raise PermanentPublishError(f"publisher not configured: {platform}") from exc

    def platforms(self) -> tuple[str, ...]:
        return tuple(sorted(self._publishers))
