from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import instagram_publisher
import yt_publisher
from publisher_contract import (
    PermanentPublishError,
    PlatformAccount,
    PublishJob,
    PublishResult,
    PublisherCapabilities,
    PublishStatus,
    ValidationResult,
)


def _legacy_record(job: PublishJob) -> dict:
    record = dict(job.metadata)
    record.setdefault("horizontal", str(job.asset_path))
    record.setdefault("vertical", str(job.asset_path))
    record.setdefault("legenda", job.caption or "")
    record.setdefault("hashtags", [])
    if job.title:
        record.setdefault("titulo", job.title)
    return record


class YouTubePublisher:
    platform = "youtube"
    capabilities = PublisherCapabilities(
        accepts_cover=False,
        aspect_ratios=("original", "9:16"),
        asynchronous_processing=False,
        supports_polling=False,
        supports_draft=True,
        privacy_options=("private", "unlisted", "public"),
    )

    def validate(self, job: PublishJob) -> ValidationResult:
        errors = () if Path(job.asset_path).is_file() else ("asset not found",)
        return ValidationResult(valid=not errors, errors=errors)

    def publish(self, job: PublishJob, secrets: Mapping[str, str]) -> PublishResult:
        del secrets  # legacy module resolves its existing authorized account token
        config = SimpleNamespace(
            conta=job.account.account_key,
            visibilidade=job.privacy or "unlisted",
            dry_run=job.account.mode == "dry_run",
        )
        result = yt_publisher.postar_corte_registro(_legacy_record(job), config)
        if result.get("erro"):
            raise PermanentPublishError(str(result["erro"]))
        uploads = [
            item for key, item in result.items() if key in {"horizontal", "vertical"} and isinstance(item, dict)
        ]
        completed = next((item for item in uploads if item.get("video_id")), None)
        if completed:
            return PublishResult.published(
                str(completed["video_id"]), completed.get("url"), legacy_result=result
            )
        return PublishResult(
            status=PublishStatus.PENDING if config.dry_run else PublishStatus.FAILED,
            metadata={"legacy_result": result},
        )

    def get_status(
        self, external_id: str, account: PlatformAccount, secrets: Mapping[str, str]
    ) -> PublishResult:
        del account, secrets
        return PublishResult(status=PublishStatus.UNKNOWN, external_id=external_id)


class InstagramPublisher:
    platform = "instagram"
    capabilities = PublisherCapabilities(
        accepts_cover=False,
        aspect_ratios=("9:16",),
        asynchronous_processing=True,
        supports_polling=False,
        supports_draft=False,
        privacy_options=("public",),
    )

    def validate(self, job: PublishJob) -> ValidationResult:
        errors = () if Path(job.asset_path).is_file() else ("asset not found",)
        return ValidationResult(valid=not errors, errors=errors)

    def publish(self, job: PublishJob, secrets: Mapping[str, str]) -> PublishResult:
        del secrets
        config = SimpleNamespace(
            conta=job.account.account_key,
            visibilidade="public",
            dry_run=job.account.mode == "dry_run",
        )
        result = instagram_publisher.postar_corte_registro(_legacy_record(job), config)
        if result.get("erro"):
            raise PermanentPublishError(str(result["erro"]))
        reel = result.get("reel") or {}
        if reel.get("media_id"):
            return PublishResult.published(
                str(reel["media_id"]), reel.get("permalink"), legacy_result=result
            )
        return PublishResult(
            status=PublishStatus.PENDING if config.dry_run else PublishStatus.FAILED,
            metadata={"legacy_result": result},
        )

    def get_status(
        self, external_id: str, account: PlatformAccount, secrets: Mapping[str, str]
    ) -> PublishResult:
        del account, secrets
        return PublishResult(status=PublishStatus.UNKNOWN, external_id=external_id)


def legacy_registry():
    from publisher_contract import PublisherRegistry
    from tiktok_standard_publisher import TikTokStandardPublisher

    registry = PublisherRegistry()
    registry.register(YouTubePublisher())
    registry.register(InstagramPublisher())
    registry.register(TikTokStandardPublisher())
    return registry
