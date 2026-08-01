from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from football_source_discovery import ACTION_TERMS, FOOTBALL_TERMS, normalized_url

DEFAULT_QUERIES = (
    "futebol gol melhores momentos hoje", "football goals highlights today",
    "brasileirao gols melhores momentos", "libertadores goals highlights",
    "champions league goals highlights", "futebol defesa penalti dribles",
)

@dataclass(frozen=True)
class Prospect:
    url: str
    title: str
    external_id: str
    query: str
    source_type: str = "youtube_video"
    metadata: Mapping[str, Any] | None = None

    @property
    def prospect_key(self) -> str:
        return hashlib.sha256(normalized_url(self.url).encode()).hexdigest()

def configured_queries() -> tuple[str, ...]:
    values = tuple(v.strip() for v in os.getenv("KWAI_DISCOVERY_QUERIES", "").split("|") if v.strip())
    return values or DEFAULT_QUERIES

def ytdlp_search(query: str, limit: int = 8) -> Iterable[Mapping[str, Any]]:
    import yt_dlp
    options = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": max(1, min(limit, 20))}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    return [row for row in (info.get("entries") or []) if isinstance(row, dict)]

def discover_prospects(searcher=ytdlp_search) -> tuple[Prospect, ...]:
    found: dict[str, Prospect] = {}
    for query in configured_queries():
        for row in searcher(query):
            title = str(row.get("title") or "").strip()
            url = str(row.get("webpage_url") or row.get("url") or "").strip()
            text = f"{title} {row.get('description') or ''}".casefold()
            if not title or not url or not any(term in text for term in ACTION_TERMS):
                continue
            if not any(term in text for term in FOOTBALL_TERMS) and "youtube" not in url:
                continue
            item = Prospect(url, title, str(row.get("id") or ""), query, metadata={**row, "content_mode": "vod_or_highlight"})
            found[item.prospect_key] = item
    return tuple(found.values())
