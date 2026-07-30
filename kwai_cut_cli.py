from __future__ import annotations

import argparse
import json
from uuid import uuid4

from kwai_cut_football import DailyContentPlanner, PROFILE_ID, kwai_cut_profile
from media_domain import ContentEvent


def fixture_events(count: int) -> list[ContentEvent]:
    kinds = ("goal", "penalty", "extraordinary_save", "red_card", "dribble")
    return [ContentEvent(str(uuid4()), PROFILE_ID, f"fixture-{index}", "safe-fixture",
                         30.0 + index, kinds[index % len(kinds)],
                         {"confidence": .9, "context_score": .8, "quality_score": .9})
            for index in range(count)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Operação local do Kwai CUT Futebol.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    process = commands.add_parser("process")
    process.add_argument("--profile", default=PROFILE_ID, choices=[PROFILE_ID])
    process.add_argument("--target", type=int, default=30, choices=range(1, 101))
    process.add_argument("--simulate", action="store_true", help="Usa fixtures seguras; não baixa nem publica.")
    args = parser.parse_args()
    if args.command == "status":
        profile = kwai_cut_profile()
        print(json.dumps({"profile_id": profile.profile_id, "enabled": profile.enabled,
                          "mode": "prepare_only", "api_enabled": False}, indent=2))
    elif not args.simulate:
        raise SystemExit("Informe --simulate ou cadastre fontes autorizadas no dashboard.")
    else:
        plan = DailyContentPlanner().plan(fixture_events(max(20, args.target)), target=args.target)
        print(json.dumps({"target": plan.target, "selected": len(plan.selected),
                          "deficit": plan.deficit, "available_events": plan.available_events,
                          "available_variants": plan.available_variants}, indent=2))


if __name__ == "__main__":
    main()
