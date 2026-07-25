from __future__ import annotations

from media_domain import ContentEvent
from editorial_strategies import (
    CutPolicy,
    CutStrategy,
    NarrastarsPolicy,
    NarrastarsStrategy,
    Narration,
    Script,
)


EVENT = ContentEvent(
    event_id="event",
    profile_id="profile",
    source_event_key="source:100",
    source_ref="source",
    timestamp_seconds=100,
    event_type="goal",
)


def test_cut_strategy_builds_configurable_material_window() -> None:
    variant = CutStrategy().create_variant(
        EVENT,
        CutPolicy(
            min_duration_seconds=20,
            max_duration_seconds=40,
            pre_event_seconds=12,
            post_event_seconds=18,
            hook_policy="action_first",
        ),
    )
    assert variant.strategy == "cut"
    assert variant.editorial_metadata["start_seconds"] == 88
    assert variant.editorial_metadata["end_seconds"] == 118
    assert variant.editorial_metadata["hook_policy"] == "action_first"


class _ScriptGenerator:
    def generate(self, event, context, options):
        return Script(f"{context['team']} marcou", "test-script")


class _NarrationProvider:
    def narrate(self, script, options):
        return Narration("narration.wav", "test-voice")


def test_narrastars_is_provider_agnostic() -> None:
    plan = NarrastarsStrategy(_ScriptGenerator(), _NarrationProvider()).create_plan(
        EVENT,
        NarrastarsPolicy(include_narration=True),
        {"team": "BotLive FC"},
    )
    assert plan.script.provider == "test-script"
    assert plan.narration.provider == "test-voice"
    assert plan.variant.strategy == "narrastars"
    assert plan.publication_mode == "ready"


def test_narrastars_falls_back_without_provider_and_can_prepare_only() -> None:
    plan = NarrastarsStrategy().create_plan(
        EVENT,
        NarrastarsPolicy(
            include_narration=True,
            prepare_only_without_narration=True,
        ),
        {"description": "Gol no fim"},
    )
    assert plan.script.text == "Gol no fim"
    assert plan.narration.audio_path is None
    assert plan.publication_mode == "prepare_only"
