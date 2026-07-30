from __future__ import annotations

import os
from dataclasses import dataclass


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FeatureFlags:
    multi_profile: bool = False
    publication_queue: bool = False
    new_publisher_contract: bool = False
    kwai: bool = False
    kwai_api: bool = False
    cut: bool = False
    narrastars: bool = False
    kwai_cut_dashboard: bool = False
    kwai_cut_football: bool = False
    football_source_discovery: bool = False
    football_real_classifier: bool = False

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            multi_profile=_enabled("MULTI_PROFILE_ENABLED"),
            publication_queue=_enabled("PUBLICATION_QUEUE_ENABLED"),
            new_publisher_contract=_enabled("NEW_PUBLISHER_CONTRACT_ENABLED"),
            kwai=_enabled("KWAI_ENABLED"),
            kwai_api=_enabled("KWAI_API_ENABLED"),
            cut=_enabled("CUT_ENABLED"),
            narrastars=_enabled("NARRASTARS_ENABLED"),
            kwai_cut_dashboard=_enabled("KWAI_CUT_DASHBOARD_ENABLED"),
            kwai_cut_football=_enabled("KWAI_CUT_FOOTBALL_ENABLED"),
            football_source_discovery=_enabled("FOOTBALL_SOURCE_DISCOVERY_ENABLED"),
            football_real_classifier=_enabled("FOOTBALL_REAL_CLASSIFIER_ENABLED"),
        )
