from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from PIL import Image
from moviepy.editor import VideoFileClip

from editorial_strategies import CutPolicy, CutStrategy
from media_domain import ContentEvent, EditorialVariant, MediaAsset, MediaAssetValidator
from profile_config import DestinationConfig, EditorialPolicy, ProfileConfig, RenderPolicy
from runtime_paths import get_output_root
from source_downloader import resolver_fonte_video

PROFILE_ID = "kwai_cut_futebol"
ALLOWED_USAGE = {"authorized", "licensed", "campaign_allowed", "owned"}
REAL_CLASSES = {"real_match", "real_highlights", "real_news", "real_interview", "real_reaction", "real_training"}
SOURCE_TYPES = {"youtube_channel", "youtube_playlist", "youtube_search", "youtube_live", "direct_video", "local_file", "watched_folder", "authorized_feed"}
DEFAULT_NEGATIVE_TERMS = ("EA FC", "FC 26", "FIFA gameplay", "eFootball", "PES", "Football Manager", "Ultimate Team", "modo carreira", "gameplay", "simulação", "mobile game", "videogame")
EVENT_PRIORITY = {"goal": 100, "penalty": 95, "red_card": 90, "fight": 89, "extraordinary_save": 86, "decisive_moment": 84, "urgent_news": 80, "strong_interview": 78, "crowd_reaction": 75, "dribble": 72, "funny_moment": 68, "full_time": 65}


def kwai_cut_profile() -> ProfileConfig:
    """Conservative editable preset. Unconfirmed rules remain profile data."""
    return ProfileConfig(
        profile_id=PROFILE_ID, name="Kwai CUT Futebol",
        description="Perfil aditivo para preparar cortes de futebol real para o Kwai.",
        niche="football", enabled=False,
        editorial=EditorialPolicy(strategy="cut", settings={
            "daily_minimum": 30, "daily_target": 30, "daily_maximum": 100,
            "duration_rule_confirmed": False, "event_priorities": EVENT_PRIORITY,
            "negative_terms": DEFAULT_NEGATIVE_TERMS,
        }),
        render=RenderPolicy(aspect_ratio="9:16", layout="vertical-fit",
                            min_duration_seconds=15, max_duration_seconds=60,
                            target_height=1920,
                            settings={"width": 1080, "video_codec": "h264", "audio_codec": "aac"}),
        destinations=(DestinationConfig(
            platform="kwai", enabled=True, publication_mode="approval",
            max_posts_per_day=100, minimum_interval_seconds=600,
            timezone="America/Sao_Paulo", max_pending_jobs=100, max_attempts=3,
            settings={"mode": "prepare_only"},
        ),),
        settings={"prepare_only": True, "activity_required": True},
    )


@dataclass(frozen=True)
class FootballSource:
    source_id: str
    name: str
    source_type: str
    source_ref: str
    usage_status: str = "review_required"
    enabled: bool = True
    priority: int = 50
    profile_id: str = PROFILE_ID
    check_frequency_minutes: int = 30
    allowed_live: bool = False
    allowed_vod: bool = True
    allowed_highlights: bool = True
    allowed_news: bool = False
    max_cuts: int = 10
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported football source type: {self.source_type}")
        if not self.source_id.strip() or not self.name.strip() or not self.source_ref.strip():
            raise ValueError("source id, name and reference are required")
        if not 0 <= self.priority <= 100:
            raise ValueError("source priority must be between 0 and 100")

    @property
    def auto_process_allowed(self) -> bool:
        return self.enabled and self.usage_status in ALLOWED_USAGE


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: float
    reasons: tuple[str, ...] = ()

    @property
    def is_real(self) -> bool:
        return self.label in REAL_CLASSES


class RealFootballClassifier:
    """Metadata gate ahead of the existing visual football filter."""

    def __init__(self, negative_terms: Iterable[str] = DEFAULT_NEGATIVE_TERMS) -> None:
        self.negative_terms = tuple(term.casefold() for term in negative_terms if term.strip())

    def classify(self, metadata: Mapping[str, Any]) -> Classification:
        text = " ".join(str(metadata.get(key) or "") for key in ("title", "description", "category", "tags")).casefold()
        matches = tuple(term for term in self.negative_terms if term in text)
        if matches:
            return Classification("video_game", 0.99, matches)
        kind = str(metadata.get("content_type") or "").strip().lower()
        explicit = {"match": "real_match", "highlights": "real_highlights", "news": "real_news", "interview": "real_interview", "reaction": "real_reaction", "training": "real_training"}.get(kind)
        markers = ("futebol", "football", "gol", "partida", "campeonato", "jogador", "treinador", "torcida", "pênalti")
        count = sum(marker in text for marker in markers)
        if explicit and count:
            return Classification(explicit, min(0.98, 0.72 + count * 0.05), ("content_type", "football markers"))
        if count >= 2:
            return Classification("real_news", min(0.9, 0.62 + count * 0.06), ("football markers",))
        return Classification("uncertain", 0.4, ("insufficient evidence",))

    def allows_automatic(self, metadata: Mapping[str, Any], threshold: float = 0.75) -> bool:
        result = self.classify(metadata)
        return result.is_real and result.confidence >= threshold


class FootballSourceDiscovery:
    """Rights-aware adapter that hands discovered references to the legacy downloader."""

    def __init__(self, downloader=resolver_fonte_video) -> None:
        self.downloader = downloader

    def forward(self, source: FootballSource) -> Path:
        if not source.auto_process_allowed:
            raise PermissionError("football source is not authorized for automatic processing")
        return Path(self.downloader(source.source_ref))

    def eligible(self, sources: Iterable[FootballSource]) -> tuple[FootballSource, ...]:
        return tuple(sorted(
            (source for source in sources if source.auto_process_allowed),
            key=lambda source: source.priority,
            reverse=True,
        ))


def score_event(event: ContentEvent) -> float:
    base = EVENT_PRIORITY.get(event.event_type, 50)
    confidence = float(event.metadata.get("confidence", 0.5))
    context = float(event.metadata.get("context_score", 0.5))
    quality = float(event.metadata.get("quality_score", 0.5))
    novelty = 0.0 if event.metadata.get("duplicate_status") == "duplicate" else 1.0
    return round(base * 0.55 + confidence * 20 + context * 8 + quality * 10 + novelty * 7, 3)


VARIANT_STYLES = {
    "direct_action": (8, 15, "event_first"),
    "full_play": (18, 16, "chronological"),
    "reaction": (8, 25, "event_then_reaction"),
    "context": (24, 16, "context_first"),
    "analysis": (15, 25, "analysis_hook"),
}


def create_cut_variants(event: ContentEvent, styles: Iterable[str] = VARIANT_STYLES) -> tuple[EditorialVariant, ...]:
    variants, seen = [], set()
    for style in styles:
        if style not in VARIANT_STYLES:
            raise ValueError(f"unsupported CUT style: {style}")
        before, after, hook = VARIANT_STYLES[style]
        variant = CutStrategy().create_variant(event, CutPolicy(
            min_duration_seconds=15, max_duration_seconds=60,
            pre_event_seconds=before, post_event_seconds=after, hook_policy=hook))
        variant = EditorialVariant.create(
            event,
            variant.strategy,
            {
                **variant.editorial_metadata,
                "context": {
                    "source_event_key": event.source_event_key,
                    "style": style,
                },
            },
        )
        if variant.variant_signature not in seen:
            variants.append(variant)
            seen.add(variant.variant_signature)
    return tuple(variants)


@dataclass(frozen=True)
class DailyPlan:
    target: int
    selected: tuple[EditorialVariant, ...]
    deficit: int
    available_events: int
    available_variants: int


class DailyContentPlanner:
    def plan(self, events: Iterable[ContentEvent], existing_signatures: Iterable[str] = (),
             target: int = 30, maximum: int = 100) -> DailyPlan:
        target = max(0, min(int(target), int(maximum), 100))
        existing = set(existing_signatures)
        ranked = sorted(events, key=lambda event: (score_event(event), event.created_at), reverse=True)
        selected, available = [], 0
        for event in ranked:
            if event.metadata.get("duplicate_status") == "duplicate":
                continue
            for variant in create_cut_variants(event):
                available += 1
                if variant.variant_signature in existing:
                    continue
                existing.add(variant.variant_signature)
                if len(selected) < target:
                    selected.append(variant)
        return DailyPlan(target, tuple(selected), max(0, target - len(selected)), len(ranked), available)


def validation_status(result) -> tuple[str, str]:
    if result.valid:
        return "approved", ""
    reason = "; ".join(result.errors)
    lowered = reason.lower()
    if "duration" in lowered:
        return "rejected_duration", reason
    if "blank" in lowered or "preto" in lowered:
        return "rejected_black_video", reason
    if "audio" in lowered:
        return "rejected_audio", reason
    return "rejected_quality", reason


def prepare_package(asset: MediaAsset, variant: EditorialVariant, title: str,
                    caption: str, hashtags: Iterable[str], activity: Mapping[str, Any],
                    output_root: Optional[Path] = None, today: Optional[date] = None) -> Path:
    """Create the prepare-only package without any external upload."""
    if not activity or not activity.get("name"):
        raise ValueError("active campaign/activity is required")
    result = MediaAssetValidator().validate(asset, kwai_cut_profile().render)
    status, reason = validation_status(result)
    if status != "approved":
        raise ValueError(reason)
    folder = (output_root or get_output_root()) / PROFILE_ID / str(today or date.today()) / variant.variant_id
    folder.mkdir(parents=True, exist_ok=True)
    video_path = folder / "video.mp4"
    if asset.path.resolve() != video_path.resolve():
        shutil.copy2(asset.path, video_path)
    cover_path = folder / "cover.jpg"
    clip = VideoFileClip(str(video_path), audio=False)
    try:
        timestamp = min(max(float(clip.duration or 0) * .35, 0), max(0, float(clip.duration or 0) - .05))
        Image.fromarray(clip.get_frame(timestamp)).convert("RGB").save(cover_path, "JPEG", quality=90)
    finally:
        clip.close()
    tags = [tag if tag.startswith("#") else f"#{tag}" for tag in hashtags if tag.strip()]
    metadata = {
        "profile_id": PROFILE_ID, "mode": "prepare_only", "status": "ready",
        "asset_id": asset.asset_id, "event_id": variant.event_id,
        "variant_id": variant.variant_id, "variant_signature": variant.variant_signature,
        "title": title, "caption": caption, "hashtags": tags, "activity": dict(activity),
        "video": video_path.name, "cover": cover_path.name,
        "duration": asset.duration, "resolution": f"{asset.width}x{asset.height}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder
