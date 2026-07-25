from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from feature_flags import FeatureFlags
from media_domain import EditorialVariant, MediaAsset, content_fingerprint, publication_key
from profile_config import DestinationConfig, ProfileConfig
from publication_queue import PublicationQueue, QueuedPublication
from publisher_contract import PlatformAccount, PublishJob


@dataclass(frozen=True)
class DestinationUsage:
    published_today: int = 0
    pending_jobs: int = 0
    last_published_at: Optional[datetime] = None


@dataclass(frozen=True)
class PlanResult:
    jobs: tuple[QueuedPublication, ...]
    skipped: Mapping[str, str]
    duplicates: int = 0


def destination_allowed(
    destination: DestinationConfig,
    usage: DestinationUsage,
    now: Optional[datetime] = None,
) -> tuple[bool, Optional[str], Optional[datetime]]:
    now = now or datetime.now(timezone.utc)
    if not destination.enabled or destination.publication_mode == "disabled":
        return False, "destination disabled", None
    if (
        destination.max_posts_per_day is not None
        and usage.published_today >= destination.max_posts_per_day
    ):
        return False, "daily limit reached", None
    if (
        destination.max_pending_jobs is not None
        and usage.pending_jobs >= destination.max_pending_jobs
    ):
        return False, "maximum pending jobs reached", None
    scheduled = now
    if usage.last_published_at and destination.minimum_interval_seconds:
        earliest = usage.last_published_at + timedelta(
            seconds=destination.minimum_interval_seconds
        )
        if earliest > scheduled:
            scheduled = earliest
    if destination.allowed_hours:
        try:
            zone = ZoneInfo(destination.timezone)
        except ZoneInfoNotFoundError:
            return False, "invalid destination timezone", None
        local = scheduled.astimezone(zone)
        allowed = sorted(set(destination.allowed_hours))
        if local.hour not in allowed:
            candidate = None
            for offset in range(1, 49):
                probe = local + timedelta(hours=offset)
                if probe.hour in allowed:
                    candidate = probe.replace(minute=0, second=0, microsecond=0)
                    break
            if candidate is None:
                return False, "no allowed publication hour", None
            scheduled = candidate.astimezone(timezone.utc)
    return True, None, scheduled


class PublicationPlanner:
    def __init__(
        self,
        queue: PublicationQueue,
        flags: Optional[FeatureFlags] = None,
    ) -> None:
        self.queue = queue
        self.flags = flags or FeatureFlags.from_env()

    def plan(
        self,
        profile: ProfileConfig,
        variant: EditorialVariant,
        asset: MediaAsset,
        accounts: Mapping[tuple[str, str], PlatformAccount],
        usage: Optional[Mapping[tuple[str, str], DestinationUsage]] = None,
        now: Optional[datetime] = None,
        title: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> PlanResult:
        if not self.flags.multi_profile or not self.flags.publication_queue:
            return PlanResult((), {"features": "multi-profile publication is disabled"})
        fingerprint = content_fingerprint(asset)
        created: list[QueuedPublication] = []
        skipped: dict[str, str] = {}
        duplicates = 0
        usage = usage or {}
        for destination in profile.destinations:
            key = (destination.platform, destination.account_key)
            label = f"{destination.platform}:{destination.account_key}"
            account = accounts.get(key)
            if account is None:
                skipped[label] = "platform account not configured"
                continue
            allowed, reason, scheduled_at = destination_allowed(
                destination, usage.get(key, DestinationUsage()), now
            )
            if not allowed:
                skipped[label] = reason or "destination policy rejected"
                continue
            pub_key = publication_key(
                destination.platform,
                account.account_id,
                profile.profile_id,
                variant.variant_id,
                fingerprint,
            )
            mode = (
                "api"
                if destination.publication_mode == "automatic"
                else "prepare_only"
            )
            effective_account = PlatformAccount(
                account.account_id,
                account.platform,
                account.account_key,
                account.secret_ref,
                mode=mode,
                options={**account.options, **destination.settings},
            )
            job = PublishJob(
                job_id=str(uuid4()),
                profile_id=profile.profile_id,
                platform=destination.platform,
                account=effective_account,
                asset_path=asset.path,
                publication_key=pub_key,
                event_id=variant.event_id,
                variant_id=variant.variant_id,
                asset_id=asset.asset_id,
                title=title,
                caption=caption,
                scheduled_at=scheduled_at,
                metadata={
                    "asset_path": str(asset.path),
                    "account_key": account.account_key,
                    "secret_ref": account.secret_ref,
                    "publish_mode": mode,
                    "publisher_options": dict(effective_account.options),
                    "destination_id": destination.destination_id,
                },
            )
            queued, was_created = self.queue.enqueue(
                QueuedPublication(
                    job,
                    scheduled_at=scheduled_at,
                    max_attempts=destination.max_attempts,
                )
            )
            if was_created:
                created.append(queued)
            else:
                duplicates += 1
        return PlanResult(tuple(created), skipped, duplicates)
