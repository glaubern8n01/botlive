from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Protocol
from uuid import uuid4

from publisher_contract import PublishJob


ELIGIBLE_STATUSES = {
    "pending",
    "validating",
    "ready",
    "uploading",
    "processing",
    "retry_wait",
}
TERMINAL_STATUSES = {"published", "rejected", "cancelled", "failed"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retry_delay_seconds(attempt: int, base: int = 30, maximum: int = 3600) -> int:
    return min(maximum, int(base * math.pow(2, max(0, attempt - 1))))


@dataclass(frozen=True)
class QueuedPublication:
    job: PublishJob
    status: str = "pending"
    attempts: int = 0
    max_attempts: int = 3
    scheduled_at: Optional[datetime] = None
    next_attempt_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    locked_at: Optional[datetime] = None
    lock_expires_at: Optional[datetime] = None
    external_id: Optional[str] = None
    remote_status: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


class PublicationQueue(Protocol):
    def enqueue(self, item: QueuedPublication) -> tuple[QueuedPublication, bool]: ...
    def claim(self, worker_id: str, lock_seconds: int = 300) -> Optional[QueuedPublication]: ...
    def mark(self, job_id: str, status: str, **fields: Any) -> QueuedPublication: ...
    def get(self, job_id: str) -> Optional[QueuedPublication]: ...
    def record_attempt(self, job_id: str, **fields: Any) -> None: ...


class InMemoryPublicationQueue:
    """Deterministic queue for tests and local dry-runs."""

    def __init__(self, clock=utc_now) -> None:
        self._clock = clock
        self._items: dict[str, QueuedPublication] = {}
        self._keys: dict[str, str] = {}
        self.attempt_history: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def enqueue(self, item: QueuedPublication) -> tuple[QueuedPublication, bool]:
        with self._lock:
            existing_id = self._keys.get(item.job.publication_key)
            if existing_id:
                return self._items[existing_id], False
            self._items[item.job.job_id] = item
            self._keys[item.job.publication_key] = item.job.job_id
            return item, True

    def claim(self, worker_id: str, lock_seconds: int = 300) -> Optional[QueuedPublication]:
        now = self._clock()
        with self._lock:
            eligible = [
                item
                for item in self._items.values()
                if item.status in ELIGIBLE_STATUSES
                and item.attempts < item.max_attempts
                and (item.scheduled_at is None or item.scheduled_at <= now)
                and (item.next_attempt_at is None or item.next_attempt_at <= now)
                and (item.lock_expires_at is None or item.lock_expires_at <= now)
            ]
            if not eligible:
                return None
            item = min(eligible, key=lambda candidate: (candidate.scheduled_at or candidate.created_at, candidate.created_at))
            claimed = replace(
                item,
                status="processing" if item.status == "processing" else "validating",
                attempts=item.attempts + 1,
                worker_id=worker_id,
                locked_at=now,
                lock_expires_at=now + timedelta(seconds=max(30, lock_seconds)),
                updated_at=now,
            )
            self._items[item.job.job_id] = claimed
            return claimed

    def mark(self, job_id: str, status: str, **fields: Any) -> QueuedPublication:
        with self._lock:
            item = self._items[job_id]
            updated = replace(
                item,
                status=status,
                worker_id=None if status in TERMINAL_STATUSES | {"retry_wait"} else item.worker_id,
                locked_at=None if status in TERMINAL_STATUSES | {"retry_wait"} else item.locked_at,
                lock_expires_at=None if status in TERMINAL_STATUSES | {"retry_wait"} else item.lock_expires_at,
                updated_at=self._clock(),
                **fields,
            )
            self._items[job_id] = updated
            return updated

    def get(self, job_id: str) -> Optional[QueuedPublication]:
        return self._items.get(job_id)

    def record_attempt(self, job_id: str, **fields: Any) -> None:
        self.attempt_history.append({"job_id": job_id, **fields})


class SupabasePublicationQueue:
    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _row(item: QueuedPublication) -> dict[str, Any]:
        job = item.job
        return {
            "job_id": job.job_id,
            "profile_id": job.profile_id,
            "event_id": job.event_id,
            "variant_id": job.variant_id,
            "asset_id": job.asset_id,
            "destination_id": job.metadata.get("destination_id"),
            "platform": job.platform,
            "account_id": job.account.account_id,
            "status": item.status,
            "publication_key": job.publication_key,
            "title": job.title,
            "caption": job.caption,
            "cover_path": str(job.cover_path) if job.cover_path else None,
            "scheduled_at": (item.scheduled_at or job.scheduled_at).isoformat()
            if (item.scheduled_at or job.scheduled_at)
            else None,
            "max_attempts": item.max_attempts,
            "metadata": dict(job.metadata),
        }

    def enqueue(self, item: QueuedPublication) -> tuple[QueuedPublication, bool]:
        existing = (
            self.client.table("publication_jobs")
            .select("*")
            .eq("publication_key", item.job.publication_key)
            .execute()
        )
        if existing.data:
            return self._from_row(existing.data[0]), False
        response = self.client.table("publication_jobs").insert(self._row(item)).execute()
        return self._from_row(response.data[0]), True

    def claim(self, worker_id: str, lock_seconds: int = 300) -> Optional[QueuedPublication]:
        response = self.client.rpc(
            "claim_publication_job",
            {"p_worker_id": worker_id, "p_lock_seconds": lock_seconds},
        ).execute()
        return self._from_row(response.data[0]) if response.data else None

    def mark(self, job_id: str, status: str, **fields: Any) -> QueuedPublication:
        patch = {"status": status, **fields}
        if status in TERMINAL_STATUSES | {"retry_wait"}:
            patch.update({"worker_id": None, "locked_at": None, "lock_expires_at": None})
        response = (
            self.client.table("publication_jobs")
            .update(patch)
            .eq("job_id", job_id)
            .execute()
        )
        return self._from_row(response.data[0])

    def get(self, job_id: str) -> Optional[QueuedPublication]:
        response = (
            self.client.table("publication_jobs").select("*").eq("job_id", job_id).execute()
        )
        return self._from_row(response.data[0]) if response.data else None

    def record_attempt(self, job_id: str, **fields: Any) -> None:
        self.client.table("publication_attempts").insert(
            {"job_id": job_id, **fields}
        ).execute()

    @staticmethod
    def _parse(value: Optional[str]) -> Optional[datetime]:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    def _from_row(self, row: Mapping[str, Any]) -> QueuedPublication:
        from pathlib import Path
        from publisher_contract import PlatformAccount

        metadata = row.get("metadata") or {}
        account = PlatformAccount(
            account_id=str(row.get("account_id") or ""),
            platform=str(row["platform"]),
            account_key=str(metadata.get("account_key") or "principal"),
            secret_ref=metadata.get("secret_ref"),
            mode=str(metadata.get("publish_mode") or "api"),
            options=metadata.get("publisher_options") or {},
        )
        job = PublishJob(
            job_id=str(row["job_id"]),
            profile_id=str(row["profile_id"]),
            platform=str(row["platform"]),
            account=account,
            asset_path=Path(str(metadata.get("asset_path") or "")),
            publication_key=str(row["publication_key"]),
            event_id=str(row["event_id"]) if row.get("event_id") else None,
            variant_id=str(row["variant_id"]) if row.get("variant_id") else None,
            asset_id=str(row["asset_id"]) if row.get("asset_id") else None,
            title=row.get("title"),
            caption=row.get("caption"),
            cover_path=Path(row["cover_path"]) if row.get("cover_path") else None,
            privacy=metadata.get("privacy"),
            scheduled_at=self._parse(row.get("scheduled_at")),
            metadata=metadata,
        )
        return QueuedPublication(
            job=job,
            status=str(row["status"]),
            attempts=int(row.get("attempts") or 0),
            max_attempts=int(row.get("max_attempts") or 3),
            scheduled_at=self._parse(row.get("scheduled_at")),
            next_attempt_at=self._parse(row.get("next_attempt_at")),
            worker_id=row.get("worker_id"),
            locked_at=self._parse(row.get("locked_at")),
            lock_expires_at=self._parse(row.get("lock_expires_at")),
            external_id=row.get("external_id"),
            remote_status=row.get("remote_status"),
            last_error=row.get("last_error"),
            created_at=self._parse(row.get("created_at")) or utc_now(),
            updated_at=self._parse(row.get("updated_at")) or utc_now(),
        )
