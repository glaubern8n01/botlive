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


def test_manual_publication_deletes_media_immediately() -> None:
    # Regra nova (pedido do operador): marcar como postado = 1 clique, sem link,
    # e o vídeo sai do painel E é apagado da VPS na hora (backend), sem esperar
    # a retenção. O janitor a cada 15min é a rede de segurança.
    page = Path("dashboard/src/pages/KwaiCut.tsx").read_text(encoding="utf-8")
    server = Path("dashboard/server.mjs").read_text(encoding="utf-8")
    assert "Histórico" in page
    assert "apagado da VPS" in page
    assert "unlink(await verifiedMediaPath" in server


def test_volume_migration_preserves_daily_production_and_manual_history() -> None:
    sql = Path("supabase/migrations/20260731_volume_gta_kwai.sql").read_text(encoding="utf-8")
    assert '"daily_target":30' in sql
    assert '"daily_maximum":100' in sql
    assert '"gta_daily_target":8' in sql
    assert '"gta_daily_maximum":12' in sql
    assert "status='published_manual'" in sql
    assert "nullif(trim(p_external_id),'')" in sql
    assert "count(distinct a.asset_id)" in sql


def test_dashboard_supports_platform_text_and_optional_external_id() -> None:
    page = Path("dashboard/src/pages/KwaiCut.tsx").read_text(encoding="utf-8")
    server = Path("dashboard/server.mjs").read_text(encoding="utf-8")
    assert "Copiar legenda + hashtags" in page
    assert "Copiar créditos" in page
    # As RPCs (texto e publicação manual) foram revogadas do anon; o painel chama
    # os endpoints do backend, que usam a service key.
    assert "/api/kwai/update-text" in page and "update_publication_text" in server
    assert "/api/kwai/mark-published" in page and "mark_manual_publication" in server
    # Marcar como postado é 1 clique, SEM link obrigatório: o backend usa um
    # marcador interno quando o link vem vazio (a RPC de produção exige valor).
    assert "Marcar como postado" in page
    assert "postado-manual-" in server
    # E apaga a mídia da VPS na hora (o janitor a cada 15min também cobre).
    assert "unlink(await verifiedMediaPath" in server
