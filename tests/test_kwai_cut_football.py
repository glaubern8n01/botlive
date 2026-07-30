from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from kwai_cut_football import (
    DailyContentPlanner,
    FootballSource,
    FootballSourceDiscovery,
    PROFILE_ID,
    RealFootballClassifier,
    create_cut_variants,
    kwai_cut_profile,
    score_event,
)
from media_domain import ContentEvent


def event(kind="goal", key="event-1", duplicate=False):
    return ContentEvent(
        str(uuid4()), PROFILE_ID, key, "authorized-fixture", 40.0, kind,
        {"confidence": .95, "context_score": .8, "quality_score": .9,
         "duplicate_status": "duplicate" if duplicate else "new"},
        datetime.now(timezone.utc),
    )


def test_profile_is_conservative_editable_prepare_only_preset():
    profile = kwai_cut_profile()
    assert profile.profile_id == PROFILE_ID
    assert profile.enabled is False
    assert profile.editorial.strategy == "cut"
    assert profile.render.aspect_ratio == "9:16"
    assert profile.render.target_height == 1920
    assert profile.editorial.settings["daily_minimum"] == 30
    assert profile.editorial.settings["daily_maximum"] == 100
    assert profile.editorial.settings["duration_rule_confirmed"] is False
    assert profile.destinations[0].settings["mode"] == "prepare_only"


def test_source_requires_rights_for_automatic_processing():
    pending = FootballSource("one", "Canal", "youtube_channel", "https://example.test")
    owned = FootballSource("two", "Arquivo", "local_file", str(Path("safe.mp4")), usage_status="owned")
    blocked = FootballSource("three", "Bloqueada", "youtube_channel", "https://example.test/blocked", usage_status="blocked")
    assert not pending.auto_process_allowed
    assert owned.auto_process_allowed
    assert not blocked.auto_process_allowed
    with pytest.raises(ValueError):
        FootballSource("bad", "Bad", "torrent", "x")


def test_source_discovery_forwards_only_to_existing_downloader():
    calls = []
    discovery = FootballSourceDiscovery(lambda ref: calls.append(ref) or Path("downloaded.mp4"))
    source = FootballSource("owned", "Arquivo", "local_file", "safe.mp4", usage_status="owned")
    assert discovery.forward(source) == Path("downloaded.mp4")
    assert calls == ["safe.mp4"]
    with pytest.raises(PermissionError):
        discovery.forward(FootballSource("pending", "Canal", "youtube_channel", "https://example.test"))


@pytest.mark.parametrize("term", ["EA FC", "FIFA gameplay", "eFootball", "Ultimate Team", "modo carreira", "videogame"])
def test_classifier_rejects_video_game_terms(term):
    result = RealFootballClassifier().classify({"title": f"Melhores gols {term}"})
    assert result.label == "video_game"
    assert not result.is_real


def test_classifier_accepts_real_football_only_above_threshold():
    classifier = RealFootballClassifier()
    metadata = {"title": "Gol no campeonato de futebol", "content_type": "highlights"}
    result = classifier.classify(metadata)
    assert result.label == "real_highlights"
    assert classifier.allows_automatic(metadata, threshold=.75)
    assert not classifier.allows_automatic({"title": "programa qualquer"})


def test_cut_variants_are_materially_distinct():
    variants = create_cut_variants(event())
    assert len(variants) == 5
    assert len({variant.variant_signature for variant in variants}) == 5
    windows = {(item.editorial_metadata["start_seconds"], item.editorial_metadata["end_seconds"]) for item in variants}
    assert len(windows) >= 4


def test_viral_score_prioritizes_goal_and_duplicate_loses_novelty():
    goal = event("goal", "goal")
    dribble = event("dribble", "dribble")
    duplicated = event("goal", "dup", duplicate=True)
    assert score_event(goal) > score_event(dribble)
    assert score_event(goal) > score_event(duplicated)


@pytest.mark.parametrize("target", [30, 100])
def test_daily_planner_reaches_target_without_artificial_duplicates(target):
    events = [event(("goal", "penalty", "dribble")[index % 3], f"event-{index}") for index in range(20)]
    plan = DailyContentPlanner().plan(events, target=target)
    assert len(plan.selected) == target
    assert plan.deficit == 0
    assert len({variant.variant_signature for variant in plan.selected}) == target


def test_daily_planner_records_deficit_instead_of_duplicate_content():
    plan = DailyContentPlanner().plan([event()], target=30)
    assert len(plan.selected) == 5
    assert plan.deficit == 25


def test_daily_planner_skips_duplicate_events_and_caps_at_100():
    plan = DailyContentPlanner().plan([event(duplicate=True)], target=999)
    assert plan.target == 100
    assert not plan.selected
    assert plan.deficit == 100
