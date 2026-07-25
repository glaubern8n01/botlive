from __future__ import annotations

from typing import Any, Mapping, Optional

from profile_config import (
    DestinationConfig,
    EditorialPolicy,
    ProfileConfig,
    RenderPolicy,
    SourceConfig,
)
from publisher_contract import PlatformAccount


def _one(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def profile_from_row(row: Mapping[str, Any]) -> ProfileConfig:
    render = _one(row.get("profile_render_settings")) or {}
    sources = tuple(
        SourceConfig(
            source_type=str(source["source_type"]),
            source_ref=str(source["source_ref"]),
            enabled=bool(source.get("enabled", True)),
            settings=source.get("settings") or {},
        )
        for source in (row.get("profile_sources") or [])
    )
    destinations: list[DestinationConfig] = []
    for destination in row.get("profile_destinations") or []:
        account = _one(destination.get("platform_accounts")) or {}
        destinations.append(
            DestinationConfig(
                platform=str(destination["platform"]),
                account_key=str(account.get("account_key") or "principal"),
                enabled=bool(destination.get("enabled", False)),
                publication_mode=str(destination.get("publication_mode") or "disabled"),
                max_posts_per_day=destination.get("max_posts_per_day"),
                minimum_interval_seconds=int(
                    destination.get("minimum_interval_seconds") or 0
                ),
                allowed_hours=tuple(
                    int(hour) for hour in (destination.get("allowed_hours") or [])
                ),
                timezone=str(destination.get("timezone") or "UTC"),
                max_pending_jobs=destination.get("max_pending_jobs"),
                max_attempts=int(destination.get("max_attempts") or 3),
                schedule=destination.get("schedule") or {},
                settings={
                    **(destination.get("settings") or {}),
                    **(destination.get("publisher_options") or {}),
                },
                destination_id=str(destination["id"]),
            )
        )
    return ProfileConfig(
        profile_id=str(row["profile_id"]),
        name=str(row["name"]),
        description=row.get("description"),
        niche=row.get("niche"),
        enabled=bool(row.get("enabled", False)),
        editorial=EditorialPolicy(
            strategy=str(row.get("editorial_strategy") or "default"),
            language=str(row.get("language") or "pt-BR"),
            captions_enabled=bool(render.get("captions_enabled", True)),
            headline_enabled=bool(render.get("headline_enabled", True)),
            brand=render.get("brand"),
            cta=render.get("cta"),
            settings=row.get("settings") or {},
        ),
        render=RenderPolicy(
            aspect_ratio=str(render.get("aspect_ratio") or "9:16"),
            layout=str(render.get("layout") or "vertical-fit"),
            min_duration_seconds=int(render.get("min_duration_seconds") or 5),
            max_duration_seconds=int(render.get("max_duration_seconds") or 60),
            target_height=render.get("target_height"),
            settings=render.get("settings") or {},
        ),
        sources=sources,
        destinations=tuple(destinations),
        settings=row.get("settings") or {},
    )


def account_from_row(row: Mapping[str, Any]) -> PlatformAccount:
    return PlatformAccount(
        account_id=str(row["id"]),
        platform=str(row["platform"]),
        account_key=str(row["account_key"]),
        secret_ref=row.get("secret_ref"),
        mode=str((row.get("metadata") or {}).get("mode") or "api"),
        options=row.get("metadata") or {},
    )


class SupabaseProfileRepository:
    def __init__(self, client) -> None:
        self.client = client

    def list_profiles(self, enabled_only: bool = False) -> tuple[ProfileConfig, ...]:
        query = self.client.table("profiles").select(
            "*, profile_sources(*), profile_render_settings(*), "
            "profile_destinations(*, platform_accounts(id,account_key,status))"
        )
        if enabled_only:
            query = query.eq("enabled", True)
        response = query.order("profile_id").execute()
        return tuple(profile_from_row(row) for row in (response.data or []))

    def get_profile(self, profile_id: str) -> Optional[ProfileConfig]:
        profiles = [
            profile
            for profile in self.list_profiles()
            if profile.profile_id == profile_id
        ]
        return profiles[0] if profiles else None

    def list_accounts(self) -> Mapping[tuple[str, str], PlatformAccount]:
        response = self.client.table("platform_accounts").select(
            "id,platform,account_key,secret_ref,metadata"
        ).execute()
        accounts = [account_from_row(row) for row in (response.data or [])]
        return {(account.platform, account.account_key): account for account in accounts}
