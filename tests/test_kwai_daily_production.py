from pathlib import Path


def test_daily_production_migration_keeps_prepare_only_and_retention() -> None:
    sql = Path("supabase/migrations/20260731_kwai_daily_production.sql").read_text(encoding="utf-8")
    assert '"daily_minimum":30' in sql
    assert '"daily_target":30' in sql
    assert '"daily_maximum":100' in sql
    assert '"published_media_retention_days":30' in sql
    assert "publication_mode = 'prepare_only'" in sql
    assert '"api_enabled":false' in sql
    assert "media_delete_after" in sql
    assert "interval '30 days'" in sql


def test_manual_publication_no_longer_deletes_media_immediately() -> None:
    page = Path("dashboard/src/pages/KwaiCut.tsx").read_text(encoding="utf-8")
    assert "/cleanup" not in page
    assert "Histórico" in page
    assert "período de retenção" in page
