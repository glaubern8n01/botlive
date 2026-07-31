from kwai_cut_football import FootballSource
from football_source_discovery import MultiChannelFootballDiscovery, normalized_url


def source(source_id: str, ref: str = "https://youtube.test/channel") -> FootballSource:
    return FootballSource(source_id, f"Canal {source_id}", "youtube_channel", ref, usage_status="licensed")


def test_scans_every_active_authorized_channel_even_after_results():
    calls = []
    def discover(item):
        calls.append(item.source_id)
        return [{"id": item.source_id, "url": f"https://video.test/{item.source_id}",
                 "title": f"Gol decisivo do canal {item.source_id}"}]
    report = MultiChannelFootballDiscovery(discover).scan_all([source("a"), source("b"), source("c")])
    assert calls == ["a", "b", "c"]
    assert report.channels_consulted == 3
    assert len(report.candidates) == 3


def test_channel_failure_is_reported_and_does_not_block_other_channels():
    def discover(item):
        if item.source_id == "b":
            raise TimeoutError("channel timeout")
        return [{"id": item.source_id, "url": f"https://video.test/{item.source_id}", "title": "Defesa incrível"}]
    report = MultiChannelFootballDiscovery(discover).scan_all([source("a"), source("b"), source("c")])
    assert [check.status for check in report.checks] == ["ok", "error", "ok"]
    assert "TimeoutError" in report.checks[1].error
    assert len(report.candidates) == 2


def test_duplicate_and_non_action_results_have_explicit_counts():
    rows = [
        {"id": "same", "url": "https://video.test/watch?v=1&utm_source=x", "title": "Gol da rodada"},
        {"id": "same", "url": "https://video.test/watch?v=1", "title": "Gol da rodada"},
        {"id": "talk", "url": "https://video.test/talk", "title": "Entrevista coletiva"},
    ]
    report = MultiChannelFootballDiscovery(lambda _source: rows).scan_all([source("a")])
    assert len(report.candidates) == 1
    assert report.checks[0].duplicates == 1
    assert report.checks[0].discarded == 1


def test_tracking_parameters_do_not_change_normalized_url():
    assert normalized_url("https://X.test/v/1?utm_source=a&b=2") == "https://x.test/v/1?b=2"
