from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import _get_client

PROFILE = "kwai_cut_futebol"
LOGGER = logging.getLogger("botlive.kwai_cut_producer")
ALLOWED = ("owned", "authorized", "licensed", "campaign_allowed")
MEMORY_LIMIT_RATIO = float(os.getenv("KWAI_MEMORY_LIMIT_RATIO", "0.80"))


def memory_usage_ratio() -> float:
    cgroup = Path("/sys/fs/cgroup")
    try:
        current = int((cgroup / "memory.current").read_text().strip())
        maximum_text = (cgroup / "memory.max").read_text().strip()
        if maximum_text != "max" and int(maximum_text) > 0:
            return current / int(maximum_text)
    except (OSError, ValueError):
        pass
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0])
        return 1 - (values["MemAvailable"] / values["MemTotal"])
    except (OSError, KeyError, ValueError, IndexError):
        return 0.0


def heavy_ffmpeg_running() -> bool:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if "ffmpeg" in command:
                return True
        except OSError:
            continue
    return False


def resource_block_reason() -> str | None:
    ratio = memory_usage_ratio()
    if ratio >= MEMORY_LIMIT_RATIO:
        return f"memory_pressure:{ratio:.3f}"
    if heavy_ffmpeg_running():
        return "ffmpeg_already_running"
    return None


class KwaiCutProducer:
    """Single-instance, rights-aware daily production monitor (never publishes)."""

    def __init__(self, client, worker_id: str | None = None) -> None:
        self.client = client
        self.worker_id = worker_id or f"{socket.gethostname()}-kwai-cut"
        self.stop_requested = False

    def stop(self, *_args) -> None:
        self.stop_requested = True

    def run_once(self) -> dict[str, int | str]:
        if os.getenv("KWAI_API_ENABLED", "0") != "0":
            raise RuntimeError("KWAI_API_ENABLED must remain 0")
        metrics = self.client.table("kwai_cut_daily_metrics").select("*").eq("profile_id", PROFILE).single().execute().data
        sources = (self.client.table("football_sources").select("source_ref,usage_status")
                   .eq("profile_id", PROFILE).eq("enabled", True).in_("usage_status", ALLOWED).execute().data or [])
        # A fonte é elegível pela licença registrada, não pelo domínio. Deduplicação
        # de trecho/roteiro/variante continua sendo responsabilidade do planner.
        current_sources = sources
        target = min(100, max(1, int(metrics.get("daily_target") or 30)))
        approved = int(metrics.get("approved") or 0)
        deficit = max(0, target - approved)
        resource_block = resource_block_reason() if deficit else None
        status = "healthy" if deficit == 0 else ("paused_resource_guard" if resource_block else "deficit")
        now = datetime.now(timezone.utc)
        self.client.table("kwai_cut_producer_state").upsert({
            "profile_id": PROFILE, "worker_id": self.worker_id,
            "lease_expires_at": (now + timedelta(minutes=20)).isoformat(),
            "last_started_at": now.isoformat(), "last_finished_at": now.isoformat(),
            "next_run_at": (now + timedelta(minutes=15)).isoformat(),
            "target": target, "approved_today": approved, "deficit": deficit,
            "eligible_sources": len(current_sources), "status": status,
            "last_error": None if current_sources or not deficit else "Nenhuma fonte com direitos comprovados; produção pausada sem duplicar.",
            "updated_at": now.isoformat(),
        }, on_conflict="profile_id").execute()
        result = {"target": target, "approved": approved, "deficit": deficit,
                  "eligible_sources": len(current_sources), "status": status}
        LOGGER.info("Kwai CUT daily state: %s", result)
        return result

    def loop(self, interval_seconds: int = 900) -> None:
        while not self.stop_requested:
            try:
                self.run_once()
            except Exception as exc:
                LOGGER.exception("Kwai CUT producer cycle failed: %s", type(exc).__name__)
            for _ in range(max(1, interval_seconds)):
                if self.stop_requested:
                    return
                time.sleep(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = _get_client()
    if client is None:
        raise SystemExit("Supabase not configured")
    worker = KwaiCutProducer(client)
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    worker.loop(int(os.getenv("KWAI_CUT_PRODUCER_INTERVAL_SECONDS", "900")))


if __name__ == "__main__":
    main()
