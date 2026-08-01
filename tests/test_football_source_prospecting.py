from football_source_prospecting import discover_prospects

def test_prospecting_keeps_real_action_and_deduplicates(monkeypatch):
    monkeypatch.setenv("KWAI_DISCOVERY_QUERIES", "teste")
    def search(_query):
        return [
            {"id": "1", "url": "https://youtube.com/watch?v=1", "title": "Gol no futebol highlights"},
            {"id": "1", "url": "https://youtube.com/watch?v=1&si=x", "title": "Gol no futebol highlights"},
            {"id": "2", "url": "https://youtube.com/watch?v=2", "title": "Entrevista coletiva"},
        ]
    rows = discover_prospects(search)
    assert len(rows) == 1
    assert rows[0].external_id == "1"
