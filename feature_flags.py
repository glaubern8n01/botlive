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
        )
