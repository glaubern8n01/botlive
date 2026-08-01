from pathlib import Path

from football_source_discovery import MultiChannelFootballDiscovery
from kwai_cut_football import FootballSource
from kwai_real_pipeline import action_metadata, audio_fingerprint


def test_action_metadata_is_separated_and_grounded_in_source_title() -> None:
    title, description, hashtags = action_metadata("Gol decisivo no fim da partida")
    assert title == "Gol em destaque"
    assert description == "Gol decisivo no fim da partida"
    assert "Fonte:" not in description
    assert 3 <= len(hashtags.split()) <= 5


def test_inactive_or_unlicensed_source_is_not_silently_ignored() -> None:
    source = FootballSource("id", "Canal", "youtube_channel", "https://example.test", usage_status="review_required")
    report = MultiChannelFootballDiscovery(lambda _: []).scan_all([source])
    assert report.channels_consulted == 1
    assert report.checks[0].status == "skipped"


def test_audio_fingerprint_uses_pcm_not_filename(monkeypatch, tmp_path: Path) -> None:
    first, second = tmp_path / "a.mp4", tmp_path / "renamed.mp4"
    first.write_bytes(b"container-a")
    second.write_bytes(b"container-b")
    class Result:
        stdout = b"same normalized pcm"
    monkeypatch.setattr("kwai_real_pipeline.subprocess.run", lambda *args, **kwargs: Result())
    assert audio_fingerprint(first) == audio_fingerprint(second)


def test_real_pipeline_contains_duplicate_guards() -> None:
    source = Path("kwai_real_pipeline.py").read_text(encoding="utf-8")
    for reason in ("duplicate_source_sha256", "duplicate_final_sha256", "duplicate_visual_hash", "duplicate_audio_fingerprint"):
        assert reason in source
    assert '"audio_policy": "preserve_original"' in source


def test_migration_invalidates_generic_batches_and_adds_unique_indexes() -> None:
    sql = Path("supabase/migrations/20260731_kwai_real_highlights.sql").read_text(encoding="utf-8")
    assert "generic_historical_content_forbidden_by_kwai_spec" in sql
    assert "kwai_media_sha_unique" in sql
