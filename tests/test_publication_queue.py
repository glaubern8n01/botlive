from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from publication_queue import InMemoryPublicationQueue, QueuedPublication
from publication_worker import PublicationWorker
from publisher_contract import (
    PlatformAccount,
    PublishJob,
    PublishResult,
    PublisherCapabilities,
    PublisherRegistry,
    RetryablePublishError,
    ValidationResult,
)


NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _item(key: str = "key", max_attempts: int = 3) -> QueuedPublication:
    return QueuedPublication(
        PublishJob(
            job_id=f"job-{key}",
            profile_id="default",
            platform="fake",
            account=PlatformAccount("account", "fake", "principal"),
            asset_path=Path("asset.mp4"),
            publication_key=key,
        ),
        max_attempts=max_attempts,
        created_at=NOW,
        updated_at=NOW,
    )


def test_queue_enforces_publication_key_idempotency() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    first, created = queue.enqueue(_item())
    second, duplicated = queue.enqueue(_item())
    assert created is True
    assert duplicated is False
    assert first.job.job_id == second.job.job_id


def test_claim_is_atomic_and_respects_lock() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item())
    assert queue.claim("worker-a") is not None
    assert queue.claim("worker-b") is None


def test_expired_lock_is_recovered() -> None:
    clock = [NOW]
    queue = InMemoryPublicationQueue(clock=lambda: clock[0])
    queue.enqueue(_item())
    queue.claim("worker-a", lock_seconds=30)
    clock[0] += timedelta(seconds=31)
    recovered = queue.claim("worker-b")
    assert recovered is not None
    assert recovered.worker_id == "worker-b"
    assert recovered.attempts == 2


class _FakePublisher:
    platform = "fake"
    capabilities = PublisherCapabilities()

    def __init__(self, error=None) -> None:
        self.error = error

    def validate(self, _job):
        return ValidationResult(True)

    def publish(self, _job, _secrets):
        if self.error:
            raise self.error
        return PublishResult.published("external-1")

    def get_status(self, *_args):
        return PublishResult.published("external-1")


class _Secrets:
    def resolve(self, _ref):
        return {}


def _worker(queue, publisher):
    registry = PublisherRegistry()
    registry.register(publisher)
    return PublicationWorker(queue, registry, _Secrets(), worker_id="worker")


def test_worker_publishes_and_records_attempt() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item())
    assert _worker(queue, _FakePublisher()).run_once()
    assert queue.get("job-key").status == "published"
    assert queue.get("job-key").external_id == "external-1"
    assert queue.attempt_history[0]["status"] == "published"


def test_worker_retries_retryable_error() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item())
    _worker(queue, _FakePublisher(RetryablePublishError("temporary"))).run_once()
    job = queue.get("job-key")
    assert job.status == "retry_wait"
    assert job.next_attempt_at is not None


def test_worker_stops_retrying_at_max_attempts() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item(max_attempts=1))
    _worker(queue, _FakePublisher(RetryablePublishError("temporary"))).run_once()
    assert queue.get("job-key").status == "failed"


def test_cancelled_job_is_not_claimed() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item())
    queue.mark("job-key", "cancelled")
    assert queue.claim("worker") is None


def test_worker_checks_remote_status_instead_of_reuploading_after_restart() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item())
    claimed = queue.claim("old-worker")
    queue.mark(
        claimed.job.job_id,
        "processing",
        external_id="external-1",
        lock_expires_at=NOW - timedelta(seconds=1),
    )
    publisher = _FakePublisher()
    publisher.publish = lambda *_args: (_ for _ in ()).throw(
        AssertionError("must not publish again")
    )
    _worker(queue, publisher).run_once()
    assert queue.get("job-key").status == "published"


def test_worker_never_reuploads_uncertain_remote_state() -> None:
    queue = InMemoryPublicationQueue(clock=lambda: NOW)
    queue.enqueue(_item())
    claimed = queue.claim("old-worker")
    queue.mark(
        claimed.job.job_id,
        "processing",
        lock_expires_at=NOW - timedelta(seconds=1),
    )
    _worker(queue, _FakePublisher()).run_once()
    job = queue.get("job-key")
    assert job.status == "failed"
    assert "manual reconciliation" in job.last_error
