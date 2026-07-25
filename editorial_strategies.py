from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

from media_domain import ContentEvent, EditorialVariant


@dataclass(frozen=True)
class CutPolicy:
    min_duration_seconds: int = 10
    max_duration_seconds: int = 60
    pre_event_seconds: int = 15
    post_event_seconds: int = 20
    hook_policy: str = "event_first"
    caption_policy: str = "auto"
    headline: Optional[str] = None
    branding: Optional[str] = None
    cta: Optional[str] = None
    layout: str = "vertical-fit"
    audio_policy: str = "preserve"

    def __post_init__(self) -> None:
        if self.min_duration_seconds < 0 or self.max_duration_seconds <= 0:
            raise ValueError("invalid CUT duration policy")
        if self.min_duration_seconds > self.max_duration_seconds:
            raise ValueError("CUT minimum duration exceeds maximum")
        if self.pre_event_seconds < 0 or self.post_event_seconds < 0:
            raise ValueError("CUT event window cannot be negative")


class CutStrategy:
    name = "cut"

    def create_variant(
        self, event: ContentEvent, policy: CutPolicy
    ) -> EditorialVariant:
        start = max(0.0, event.timestamp_seconds - policy.pre_event_seconds)
        end = event.timestamp_seconds + policy.post_event_seconds
        if end - start > policy.max_duration_seconds:
            end = start + policy.max_duration_seconds
        if end - start < policy.min_duration_seconds:
            end = start + policy.min_duration_seconds
        return EditorialVariant.create(
            event,
            self.name,
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "hook_policy": policy.hook_policy,
                "audio_policy": policy.audio_policy,
                "layout": policy.layout,
                "caption_policy": policy.caption_policy,
                "headline": policy.headline,
                "branding": policy.branding,
                "cta": policy.cta,
            },
        )


@dataclass(frozen=True)
class Script:
    text: str
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Narration:
    audio_path: Optional[str]
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ScriptGenerator(Protocol):
    def generate(
        self, event: ContentEvent, context: Mapping[str, Any], options: Mapping[str, Any]
    ) -> Script: ...


class NarrationProvider(Protocol):
    def narrate(self, script: Script, options: Mapping[str, Any]) -> Narration: ...


class FallbackScriptGenerator:
    def generate(
        self, event: ContentEvent, context: Mapping[str, Any], options: Mapping[str, Any]
    ) -> Script:
        del options
        description = str(
            context.get("description")
            or event.metadata.get("description")
            or event.event_type
        )
        return Script(description, "fallback")


class NoNarrationProvider:
    def narrate(self, script: Script, options: Mapping[str, Any]) -> Narration:
        del script, options
        return Narration(None, "none", {"fallback_without_narration": True})


@dataclass(frozen=True)
class NarrastarsPolicy:
    context_before_seconds: int = 25
    context_after_seconds: int = 20
    include_narration: bool = False
    prepare_only_without_narration: bool = False
    script_options: Mapping[str, Any] = field(default_factory=dict)
    narration_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NarrastarsPlan:
    variant: EditorialVariant
    script: Script
    narration: Narration
    publication_mode: str


class NarrastarsStrategy:
    name = "narrastars"

    def __init__(
        self,
        script_generator: Optional[ScriptGenerator] = None,
        narration_provider: Optional[NarrationProvider] = None,
    ) -> None:
        self.script_generator = script_generator or FallbackScriptGenerator()
        self.narration_provider = narration_provider or NoNarrationProvider()

    def create_plan(
        self,
        event: ContentEvent,
        policy: NarrastarsPolicy,
        context: Optional[Mapping[str, Any]] = None,
    ) -> NarrastarsPlan:
        context = dict(context or {})
        script = self.script_generator.generate(event, context, policy.script_options)
        narration = (
            self.narration_provider.narrate(script, policy.narration_options)
            if policy.include_narration
            else NoNarrationProvider().narrate(script, {})
        )
        start = max(0.0, event.timestamp_seconds - policy.context_before_seconds)
        end = event.timestamp_seconds + policy.context_after_seconds
        variant = EditorialVariant.create(
            event,
            self.name,
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "context": context,
                "narration": {
                    "provider": narration.provider,
                    "audio_path": narration.audio_path,
                    "script_provider": script.provider,
                },
            },
        )
        mode = (
            "prepare_only"
            if policy.prepare_only_without_narration
            and policy.include_narration
            and not narration.audio_path
            else "ready"
        )
        return NarrastarsPlan(variant, script, narration, mode)


class EditorialStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, object] = {}

    def register(self, name: str, strategy: object) -> None:
        if name in self._strategies:
            raise ValueError(f"editorial strategy already registered: {name}")
        self._strategies[name] = strategy

    def get(self, name: str) -> object:
        try:
            return self._strategies[name]
        except KeyError as exc:
            raise ValueError(f"editorial strategy not configured: {name}") from exc


def default_strategy_registry() -> EditorialStrategyRegistry:
    registry = EditorialStrategyRegistry()
    registry.register("cut", CutStrategy())
    registry.register("narrastars", NarrastarsStrategy())
    return registry
