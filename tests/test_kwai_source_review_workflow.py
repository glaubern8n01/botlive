from datetime import datetime, timedelta, timezone
from pathlib import Path

MIGRATION = Path("supabase/migrations/20260731_kwai_source_review_workflow.sql").read_text(encoding="utf-8")
PAGE = Path("dashboard/src/pages/KwaiCut.tsx").read_text(encoding="utf-8")
SERVER = Path("dashboard/server.mjs").read_text(encoding="utf-8")


# --- Migration ---------------------------------------------------------------

def test_migration_is_additive_only() -> None:
    lowered = MIGRATION.lower()
    # Comandos destrutivos reais (a palavra "truncate"/"delete" aparece só em REVOKE,
    # que é o oposto de destrutivo — revoga o privilégio).
    assert "drop table" not in lowered
    assert "truncate table" not in lowered
    assert "truncate public." not in lowered
    assert "drop column" not in lowered
    assert "delete from" not in lowered


def test_migration_allows_approved_usage_status_on_sources() -> None:
    assert "football_sources_usage_status_check" in MIGRATION
    assert "'approved'" in MIGRATION
    assert "authorization_expires_at" in MIGRATION


def test_migration_adds_block_expiry_and_audit_columns() -> None:
    for column in ("blocked_reason", "blocked_at", "authorization_expires_at", "previous_review_state"):
        assert f"add column if not exists {column}" in MIGRATION
    assert "football_source_review_history" in MIGRATION


def test_review_rpc_requires_evidence_and_blocks_transition() -> None:
    assert "owner, authorization reason, license/CUT task and evidence are required" in MIGRATION
    assert "blocked_reason is required" in MIGRATION
    assert "source is blocked; reevaluate before approving" in MIGRATION
    # Bloqueio retira a fonte ligada da produção.
    assert "set usage_status = 'blocked', enabled = false" in MIGRATION


def test_reevaluate_rpc_exists_and_requires_reason() -> None:
    assert "function public.reevaluate_football_source_prospect" in MIGRATION
    assert "reason is required" in MIGRATION
    assert "source is not blocked, pending or expired" in MIGRATION


# --- Producer ----------------------------------------------------------------

def test_producer_allows_approved_state() -> None:
    import kwai_cut_producer
    assert "approved" in kwai_cut_producer.ALLOWED
    assert "authorized" in kwai_cut_producer.ALLOWED
    assert "licensed" in kwai_cut_producer.ALLOWED
    assert "campaign_allowed" in kwai_cut_producer.ALLOWED
    # Estados não elegíveis nunca entram na tupla.
    assert "review_required" not in kwai_cut_producer.ALLOWED
    assert "blocked" not in kwai_cut_producer.ALLOWED


def test_authorization_active_respects_expiry() -> None:
    from kwai_cut_producer import authorization_active
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert authorization_active({"authorization_expires_at": None}) is True
    assert authorization_active({"authorization_expires_at": future}) is True
    assert authorization_active({"authorization_expires_at": past}) is False


class _Result:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, client, table): self.client, self.table = client, table
    def select(self, *_): return self
    def eq(self, *_): return self
    def in_(self, *_): return self
    def single(self): return self
    def execute(self):
        return _Result(self.client.metrics if self.table == "kwai_cut_daily_metrics" else self.client.sources)
    def upsert(self, payload, **_): self.client.saved = payload; return self


class _Client:
    def __init__(self, sources):
        self.metrics = {"daily_target": 30, "approved": 0}
        self.sources = sources
        self.saved = None
    def table(self, name): return _Query(self, name)


def test_producer_ignores_expired_authorization(monkeypatch) -> None:
    monkeypatch.setenv("KWAI_API_ENABLED", "0")
    monkeypatch.setattr("kwai_cut_producer.resource_block_reason", lambda: None)
    from kwai_cut_producer import KwaiCutProducer
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client = _Client([{"source_ref": "https://x/y", "usage_status": "authorized", "authorization_expires_at": past}])
    result = KwaiCutProducer(client, "test-worker").run_once()
    assert result["eligible_sources"] == 0


# --- Dashboard ---------------------------------------------------------------

def test_dashboard_exposes_review_block_and_reevaluate() -> None:
    assert "Aprovar com evidência" in PAGE
    assert "Bloquear" in PAGE
    assert "Reavaliar" in PAGE
    assert "Histórico da revisão" in PAGE
    # As mutações passam pelo backend, não mais pela RPC direta.
    assert "/api/kwai/prospects/review" in PAGE
    assert "/api/kwai/prospects/reevaluate" in PAGE


# --- Segurança: mutações administrativas fora do alcance do anon --------------

def test_frontend_never_calls_definer_rpc_directly() -> None:
    # O anon key foi revogado dessas funções; o frontend não pode chamá-las direto.
    assert "review_football_source_prospect" not in PAGE
    assert "reevaluate_football_source_prospect" not in PAGE
    assert "supabase.rpc('review" not in PAGE
    assert "supabase.rpc('reevaluate" not in PAGE


def test_migration_revokes_admin_functions_from_anon() -> None:
    lowered = MIGRATION.lower()
    assert "revoke all on function public.review_football_source_prospect" in lowered
    assert "revoke all on function public.reevaluate_football_source_prospect" in lowered
    # Revogado de public/anon/authenticated e concedido só ao backend server-side.
    assert "from public, anon, authenticated" in lowered
    assert "to service_role" in lowered
    # Histórico não pode ser escrito pelo anon.
    assert "revoke insert, update, delete, truncate on public.football_source_review_history" in lowered


def test_backend_proxies_review_with_serverside_credential() -> None:
    assert "/api/kwai/prospects/" in SERVER
    assert "callAdminRpc" in SERVER
    # Credencial administrativa vem de env server-side (nunca VITE_).
    assert "SUPABASE_SERVICE_ROLE_KEY" in SERVER or "ROBO_SUPABASE_KEY" in SERVER
    assert "process.env.VITE_SUPABASE_SERVICE" not in SERVER
    # Sem credencial administrativa, os endpoints ficam desligados (fail closed).
    assert "Backend administrativo não configurado" in SERVER
    assert "review_football_source_prospect" in SERVER
    assert "reevaluate_football_source_prospect" in SERVER


def test_service_key_never_bundled_into_frontend() -> None:
    # A service key não pode ter prefixo VITE_ (senão iria para o bundle do browser).
    assert "VITE_SUPABASE_SERVICE_ROLE_KEY" not in PAGE
    assert "VITE_SUPABASE_SERVICE_ROLE_KEY" not in SERVER
    assert "sb_secret" not in PAGE and "sb_secret" not in SERVER


def test_dashboard_has_expanded_filters_and_bulk_normalization() -> None:
    assert "Filtrar evento" in PAGE
    assert "Filtrar canal/proprietário" in PAGE
    assert "function parseBulkLinks" in PAGE
    assert "split(/[\\s,;]+/)" in PAGE
    # Não trata origem pública como autorização automática.
    assert 'nem "está no YouTube" nem "canal oficial"' in PAGE
