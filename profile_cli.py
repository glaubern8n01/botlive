from __future__ import annotations

import argparse

from database import _get_client
from feature_flags import FeatureFlags
from profile_repository import SupabaseProfileRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Utilidades multi-perfil do BotLive.")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list-profiles", help="Lista perfis do Supabase sem secrets.")
    listing.add_argument("--enabled-only", action="store_true")
    args = parser.parse_args()

    if not FeatureFlags.from_env().multi_profile:
        raise SystemExit("MULTI_PROFILE_ENABLED está desligada.")
    client = _get_client()
    if client is None:
        raise SystemExit("Supabase não configurado.")
    repository = SupabaseProfileRepository(client)
    for profile in repository.list_profiles(args.enabled_only):
        destinations = ", ".join(
            f"{item.platform}:{item.account_key}:{item.publication_mode}"
            for item in profile.destinations
        ) or "sem destinos"
        print(
            f"{profile.profile_id}\t{'ativo' if profile.enabled else 'inativo'}"
            f"\t{profile.editorial.strategy}\t{destinations}"
        )


if __name__ == "__main__":
    main()
