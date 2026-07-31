from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ACTION_TERMS = (
    "gol", "goal", "penalti", "penalty", "defesa", "save", "drible",
    "falta", "expuls", "red card", "comemor", "virada", "highlights",
    "melhores momentos", "best moments", "chance", "decisiv", "replay",
)
FOOTBALL_TERMS = (
    "futebol", "football", "soccer", "brasileirao", "libertadores",
    "champions", "copa", "campeonato", "partida", "match", "fc ",
)


def normalized_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = urlencode(sorted(
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in {"feature", "si", "utm_source", "utm_medium", "utm_campaign"}
    ))
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), query, ""))


@dataclass(frozen=True)
class DiscoveredVideo:
    source_id: str
    source_name: str
    external_id: str
    url: str
    title: str
    duration: float | None = None
    published_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def discovery_key(self) -> str:
        identity = self.external_id.strip() or normalized_url(self.url)
        return hashlib.sha256(f"{self.source_id}:{identity}".encode()).hexdigest()

    @property
    def has_action_signal(self) -> bool:
        text = f"{self.title} {self.metadata.get('description', '')}".casefold()
        return any(term in text for term in ACTION_TERMS)

    @property
    def has_football_signal(self) -> bool:
        text = f"{self.title} {self.metadata.get('description', '')}".casefold()
        return self.has_action_signal or any(term in text for term in FOOTBALL_TERMS)

    @property
    def content_mode(self) -> str:
        live_status = str(self.metadata.get("live_status") or "").casefold()
        if self.metadata.get("is_live") is True or live_status == "is_live":
            return "live"
        if live_status in {"was_live", "post_live"}:
            return "vod"
        if self.has_action_signal:
            return "highlights"
        return "vod"

    def allowed_for(self, source: Any) -> bool:
        if self.content_mode == "live":
            return bool(source.allowed_live) and self.has_football_signal
        if self.content_mode == "highlights":
            return bool(source.allowed_highlights) and self.has_action_signal
        return bool(source.allowed_vod) and self.has_action_signal


@dataclass(frozen=True)
class SourceCheck:
    source_id: str
    source_name: str
    status: str
    found: int
    new: int
    duplicates: int
    discarded: int
    live: int = 0
    error: str | None = None
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class DiscoveryReport:
    checks: tuple[SourceCheck, ...]
    candidates: tuple[DiscoveredVideo, ...]

    @property
    def channels_consulted(self) -> int:
        return len(self.checks)


Discoverer = Callable[[Any], Iterable[Mapping[str, Any]]]


class MultiChannelFootballDiscovery:
    """Scans every eligible source and never hides a source-level failure."""

    def __init__(self, discoverer: Discoverer) -> None:
        self.discoverer = discoverer

    def scan_all(self, sources: Iterable[Any], existing_keys: Iterable[str] = ()) -> DiscoveryReport:
        seen = set(existing_keys)
        checks: list[SourceCheck] = []
        candidates: list[DiscoveredVideo] = []
        for source in sources:
            if not source.auto_process_allowed:
                continue
            found = new = duplicates = discarded = live = 0
            try:
                rows = list(self.discoverer(source))
                found = len(rows)
                for row in rows:
                    item = DiscoveredVideo(
                        source_id=source.source_id, source_name=source.name,
                        external_id=str(row.get("id") or row.get("external_id") or ""),
                        url=str(row.get("webpage_url") or row.get("url") or ""),
                        title=str(row.get("title") or ""), duration=row.get("duration"),
                        published_at=row.get("upload_date") or row.get("published_at"),
                        metadata=row,
                    )
                    if item.content_mode == "live":
                        live += 1
                    if not item.url or not item.title or not item.allowed_for(source):
                        discarded += 1
                        continue
                    if item.discovery_key in seen:
                        duplicates += 1
                        continue
                    seen.add(item.discovery_key)
                    candidates.append(item)
                    new += 1
                checks.append(SourceCheck(source.source_id, source.name, "ok", found, new, duplicates, discarded, live))
            except Exception as exc:
                checks.append(SourceCheck(source.source_id, source.name, "error", found, new, duplicates, discarded,
                                          live, f"{type(exc).__name__}: {exc}"))
        return DiscoveryReport(tuple(checks), tuple(candidates))


def ytdlp_discover(source: Any) -> Iterable[Mapping[str, Any]]:
    import yt_dlp

    limit = max(1, min(int(source.settings.get("discovery_limit", 12)), 50))
    options = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist", "playlistend": limit}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source.source_ref, download=False)
    entries = info.get("entries") if isinstance(info, dict) else None
    return [entry for entry in (entries or [info]) if isinstance(entry, dict)]
