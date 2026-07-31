from kwai_cut_producer import KwaiCutProducer


class Result:
    def __init__(self, data): self.data = data


class Query:
    def __init__(self, client, table): self.client, self.table = client, table
    def select(self, *_): return self
    def eq(self, *_): return self
    def in_(self, *_): return self
    def single(self): return self
    def execute(self):
        return Result(self.client.metrics if self.table == "kwai_cut_daily_metrics" else self.client.sources)
    def upsert(self, payload, **_): self.client.saved = payload; return self


class Client:
    metrics = {"daily_target": 30, "approved": 3}
    sources = [{"source_ref": "https://commons.wikimedia.org/test", "usage_status": "licensed"}]
    saved = None
    def table(self, name): return Query(self, name)


def test_producer_records_deficit_without_reusing_historical_fixtures(monkeypatch):
    monkeypatch.setenv("KWAI_API_ENABLED", "0")
    client = Client()
    result = KwaiCutProducer(client, "test-worker").run_once()
    assert result == {"target": 30, "approved": 3, "deficit": 27, "eligible_sources": 0, "status": "deficit"}
    assert "Nenhuma fonte atual" in client.saved["last_error"]


def test_producer_refuses_api_enabled(monkeypatch):
    monkeypatch.setenv("KWAI_API_ENABLED", "1")
    try:
        KwaiCutProducer(Client()).run_once()
    except RuntimeError as exc:
        assert "must remain 0" in str(exc)
    else:
        raise AssertionError("producer accepted external Kwai API")
