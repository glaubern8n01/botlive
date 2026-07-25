from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_new_migrations_are_additive() -> None:
    for migration in (ROOT / "supabase" / "migrations").glob("*.sql"):
        text = migration.read_text(encoding="utf-8").lower()
        assert "drop table" not in text, migration.name
        assert "truncate " not in text, migration.name


def test_safe_accounts_view_never_selects_secret_value() -> None:
    migration = (
        ROOT / "supabase" / "migrations" / "20260725_publication_dashboard.sql"
    ).read_text(encoding="utf-8").lower()
    view = migration.split("create or replace view public.platform_accounts_safe", 1)[1]
    view = view.split("create or replace function", 1)[0]
    assert "secret_ref," not in view
    assert "secret_configured" in view


def test_dashboard_pages_do_not_query_secret_ref() -> None:
    pages = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "dashboard" / "src" / "pages").glob("*.tsx")
    )
    assert "secret_ref" not in pages
