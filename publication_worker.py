from __future__ import annotations

import argparse
import logging
import signal
import socket
import time
from datetime import timedelta
from typing import Optional
from uuid import uuid4

from database import _get_client
from feature_flags import FeatureFlags
from publication_queue import (
    PublicationQueue,
    SupabasePublicationQueue,
    retry_delay_seconds,
    utc_now,
)
from publisher_adapters import legacy_registry
from publisher_contract import (
    AssetValidationError,
    AuthenticationError,
    PermanentPublishError,
    PublishStatus,
    RateLimitError,
    RetryablePublishError,
)
from secret_provider import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    LocalTokenSecretProvider,
)
from kwai_publisher import KwaiPublisher


LOGGER = logging.getLogger("botlive.publication_worker")


class PublicationWorker:
    def __init__(
        self,
        queue: PublicationQueue,
        registry,
        secrets,
        worker_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        self.queue = queue
        self.registry = registry
        self.secrets = secrets
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        self.dry_run = dry_run
        self.stop_requested = False

    def request_stop(self, *_args) -> None:
        self.stop_requested = True

    def run_once(self) -> bool:
        item = self.queue.claim(self.worker_id)
        if item is None:
            return False
        job = item.job
        context = {
            "publication_job_id": job.job_id,
            "profile_id": job.profile_id,
            "event_id": job.event_id,
            "variant_id": job.variant_id,
            "asset_id": job.asset_id,
            "platform": job.platform,
            "account_id": job.account.account_id,
            "worker_id": self.worker_id,
        }
        started = time.monotonic()
        try:
            publisher = self.registry.get(job.platform)
            validation = publisher.validate(job)
            if not validation.valid:
                raise AssetValidationError("; ".join(validation.errors))
            if self.dry_run:
                self.queue.mark(job.job_id, "ready", remote_status="worker_dry_run")
                return True
            secret_values = (
                self.secrets.resolve(job.account.secret_ref)
                if job.account.secret_ref
                else {}
            )
            if item.status == "processing":
                if not item.external_id:
                    raise PermanentPublishError(
                        "uncertain remote upload state without external_id; "
                        "manual reconciliation required to avoid duplicate publication"
                    )
                result = publisher.get_status(
                    item.external_id, job.account, secret_values
                )
            else:
                self.queue.mark(job.job_id, "uploading")
                result = publisher.publish(job, secret_values)
            status = (
                "published"
                if result.status == PublishStatus.PUBLISHED
                else "processing"
                if result.status == PublishStatus.PROCESSING
                else "ready"
            )
            self.queue.mark(
                job.job_id,
                status,
                external_id=result.external_id,
                remote_status=result.remote_status or result.status.value,
            )
            self.queue.record_attempt(
                job.job_id,
                attempt_number=item.attempts,
                worker_id=self.worker_id,
                status=status,
                external_id=result.external_id,
                remote_status=result.remote_status,
                finished_at=utc_now().isoformat(),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            LOGGER.info("publication job completed", extra=context)
        except AssetValidationError as exc:
            self._fail(item, "rejected", exc, started, context)
        except (AuthenticationError, PermanentPublishError) as exc:
            self._fail(item, "failed", exc, started, context)
        except (RateLimitError, RetryablePublishError, OSError, TimeoutError) as exc:
            if item.attempts >= item.max_attempts:
                self._fail(item, "failed", exc, started, context)
            else:
                delay = (
                    exc.retry_after_seconds
                    if isinstance(exc, RateLimitError) and exc.retry_after_seconds
                    else retry_delay_seconds(item.attempts)
                )
                self._fail(
                    item,
                    "retry_wait",
                    exc,
                    started,
                    context,
                    next_attempt_at=(utc_now() + timedelta(seconds=delay)).isoformat(),
                )
        except Exception as exc:
            self._fail(item, "failed", exc, started, context)
        return True

    def _fail(self, item, status, exc, started, context, **fields) -> None:
        message = f"{type(exc).__name__}: {exc}"
        self.queue.mark(item.job.job_id, status, last_error=message, **fields)
        self.queue.record_attempt(
            item.job.job_id,
            attempt_number=item.attempts,
            worker_id=self.worker_id,
            status=status,
            error_type=type(exc).__name__,
            error_message=str(exc),
            finished_at=utc_now().isoformat(),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        LOGGER.warning("publication job failed: %s", type(exc).__name__, extra=context)

    def run_loop(self, poll_seconds: float = 5.0) -> None:
        while not self.stop_requested:
            if not self.run_once():
                time.sleep(max(0.1, poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker persistente de publicação do BotLive.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Processa no máximo um job elegível.")
    mode.add_argument("--loop", action="store_true", help="Processa continuamente até receber sinal.")
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--dry-run", action="store_true", help="Faz claim e valida, mas não envia.")
    args = parser.parse_args()

    flags = FeatureFlags.from_env()
    if not flags.publication_queue:
        raise SystemExit("PUBLICATION_QUEUE_ENABLED está desligada; worker não iniciado.")
    client = _get_client()
    if client is None:
        raise SystemExit("Supabase não configurado; worker requer fila persistente.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    registry = legacy_registry()
    if flags.kwai:
        registry.register(KwaiPublisher(flags))
    worker = PublicationWorker(
        SupabasePublicationQueue(client),
        registry,
        CompositeSecretProvider(EnvironmentSecretProvider(), LocalTokenSecretProvider()),
        dry_run=args.dry_run,
    )
    signal.signal(signal.SIGINT, worker.request_stop)
    signal.signal(signal.SIGTERM, worker.request_stop)
    if args.once:
        worker.run_once()
    else:
        worker.run_loop(args.poll_seconds)


if __name__ == "__main__":
    main()
