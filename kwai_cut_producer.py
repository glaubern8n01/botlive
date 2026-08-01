from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import _get_client
from football_source_discovery import MultiChannelFootballDiscovery, ytdlp_discover
from football_source_prospecting import discover_prospects
from kwai_cut_football import FootballSource
from kwai_real_pipeline import KwaiRealPipeline

PROFILE = "kwai_cut_futebol"
LOGGER = logging.getLogger("botlive.kwai_cut_producer")
ALLOWED = ("owned", "approved", "authorized", "licensed", "campaign_allowed")


def authorization_active(row: dict) -> bool:
    """Fonte só é elegível enquanto a autorização não vencer."""
    expires = row.get("authorization_expires_at")
    if not expires:
        return True
    try:
        deadline = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except ValueError:
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline > datetime.now(timezone.utc)
MEMORY_LIMIT_RATIO = float(os.getenv("KWAI_MEMORY_LIMIT_RATIO", "0.80"))
DAILY_TARGET = min(100, max(1, int(os.getenv("KWAI_DAILY_TARGET", "30"))))
DAILY_MAXIMUM = min(100, max(DAILY_TARGET, int(os.getenv("KWAI_DAILY_MAXIMUM", "100"))))
RENDER_CONCURRENCY = 1


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
        sources = (self.client.table("football_sources").select("source_ref,usage_status,authorization_expires_at")
                   .eq("profile_id", PROFILE).eq("enabled", True).in_("usage_status", ALLOWED).execute().data or [])
        # A fonte é elegível pela licença registrada, não pelo domínio. Deduplicação
        # de trecho/roteiro/variante continua sendo responsabilidade do planner.
        current_sources = [row for row in sources if authorization_active(row)]
        target = min(DAILY_MAXIMUM, max(1, int(metrics.get("daily_target") or DAILY_TARGET)))
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

    def discover_all_sources(self) -> dict[str, int]:
        rows = (self.client.table("football_sources").select("*")
                .eq("profile_id", PROFILE).eq("enabled", True)
                .in_("usage_status", ALLOWED).execute().data or [])
        rows = [row for row in rows if authorization_active(row)]
        sources = tuple(FootballSource(
            source_id=str(row["source_id"]), name=str(row["name"]),
            source_type=str(row["source_type"]), source_ref=str(row["source_ref"]),
            usage_status=str(row["usage_status"]), enabled=bool(row.get("enabled", True)),
            priority=int(row.get("priority") or 50),
            check_frequency_minutes=int(row.get("check_frequency_minutes") or 30),
            allowed_live=bool(row.get("allowed_live", False)),
            allowed_vod=bool(row.get("allowed_vod", True)),
            allowed_highlights=bool(row.get("allowed_highlights", True)),
            allowed_news=bool(row.get("allowed_news", False)),
            max_cuts=int(row.get("max_cuts") or 10), settings=row.get("settings") or {},
        ) for row in rows)
        existing_rows = (self.client.table("football_discovered_videos")
                         .select("discovery_key").eq("profile_id", PROFILE).execute().data or [])
        report = MultiChannelFootballDiscovery(ytdlp_discover).scan_all(
            sources, (row["discovery_key"] for row in existing_rows))
        for check in report.checks:
            self.client.table("football_source_checks").insert({
                "profile_id": PROFILE, "source_id": check.source_id, "status": check.status,
                "checked_at": check.checked_at, "found_count": check.found, "new_count": check.new,
                "duplicate_count": check.duplicates, "discarded_count": check.discarded,
                "live_count": check.live, "error": check.error,
                "discard_reasons": dict(check.discard_reasons),
            }).execute()
            self.client.table("football_sources").update({
                "last_checked_at": check.checked_at, "status": check.status,
                "last_error": check.error,
            }).eq("source_id", check.source_id).execute()
        for item in report.candidates:
            self.client.table("football_discovered_videos").upsert({
                "profile_id": PROFILE, "source_id": item.source_id,
                "discovery_key": item.discovery_key, "external_id": item.external_id or None,
                "source_url": item.url, "source_name": item.source_name, "title": item.title,
                "duration": item.duration, "source_published_at": item.published_at,
                "status": "found", "metadata": {**dict(item.metadata), "content_mode": item.content_mode},
            }, on_conflict="profile_id,discovery_key").execute()
        return {"channels_consulted": report.channels_consulted,
                "candidates": len(report.candidates),
                "live_found": sum(check.live for check in report.checks),
                "channel_errors": sum(check.status == "error" for check in report.checks)}

    def produce_next(self) -> bool:
        """Renderiza no máximo um item; o ciclo seguinte retoma automaticamente."""
        state = self.run_once()
        if not state["deficit"] or state["status"] == "paused_resource_guard":
            return False
        discovery = self.discover_all_sources()
        LOGGER.info("Kwai CUT multichannel discovery: %s", discovery)
        try:
            prospects = discover_prospects()
            for item in prospects:
                self.client.table("football_source_prospects").upsert({
                    "profile_id": PROFILE, "prospect_key": item.prospect_key,
                    "source_url": item.url, "title": item.title,
                    "source_type": item.source_type, "discovered_by": "automatic_search",
                    "search_query": item.query, "review_status": "review_required",
                    "metadata": dict(item.metadata or {}),
                }, on_conflict="profile_id,prospect_key").execute()
            LOGGER.info("Kwai CUT source prospecting: %s candidates", len(prospects))
        except Exception as exc:
            LOGGER.warning("Kwai CUT source prospecting failed without stopping production: %s", exc)
        # O antigo --auto usa um catálogo histórico fixo e não recebe o candidato
        # descoberto. Nunca o acione aqui: os vídeos reais ficam em `found` até o
        # detector de lances consumi-los, em vez de aparentar produção com outro arquivo.
        result = KwaiRealPipeline(self.client).process_next()
        if result is None:
            LOGGER.info("Kwai CUT: nenhum candidato real aguardando processamento")
            return False
        LOGGER.info("Kwai CUT real pipeline: %s", result)
        return result.status == "ready_review"

    def loop(self, interval_seconds: int = 900) -> None:
        while not self.stop_requested:
            try:
                self.produce_next()
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
    worker.loop(int(os.getenv("KWAI_CUT_PRODUCER_INTERVAL_SECONDS", "300")))


if __name__ == "__main__":
    main()
