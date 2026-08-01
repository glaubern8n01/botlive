from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import gta_tiktok_bridge as bridge
from gta_tiktok_bridge import GtaTikTokBridge, bridge_enabled, gta_tiktok_text, normalize_hashtags


class Result:
    def __init__(self, data): self.data = data


class Query:
    def __init__(self, table, store): self.table, self.store = table, store
    def select(self, *_): return self
    def eq(self, *_a): return self
    def single(self): self._single = True; return self
    def execute(self):
        rows = self.store.data.get(self.table, [])
        return Result(rows[0] if getattr(self, "_single", False) else rows)
    def insert(self, payload):
        self.store.inserts.setdefault(self.table, []).append(payload)
        returned = dict(payload)
        returned.setdefault("event_id", "evt-1")
        returned.setdefault("variant_id", "var-1")
        return Query.Immediate([returned])
    class Immediate:
        def __init__(self, data): self._data = data
        def execute(self): return Result(self._data)


class FakeClient:
    def __init__(self, data=None):
        self.data = data or {}
        self.inserts = {}
    def table(self, name): return Query(name, self)


VERTICAL = SimpleNamespace(sha256="a1b2c3d4e5", perceptual_hash="ph", audio_fingerprint=None,
                           duration=30.0, width=1080, height=1920, aspect_ratio="9:16",
                           codec="h264", audio_codec="aac", filesize=1234)
HORIZONTAL = SimpleNamespace(sha256="ffff", perceptual_hash="ph", audio_fingerprint=None,
                             duration=30.0, width=1920, height=1080, aspect_ratio="other",
                             codec="h264", audio_codec="aac", filesize=1234)


def _bridge(client, asset=VERTICAL):
    return GtaTikTokBridge(client, inspector=lambda *_: asset, fingerprinter=lambda *_: "af")


def _master(tmp_path: Path) -> Path:
    path = tmp_path / "corte_gta_vertical.mp4"
    path.write_bytes(b"x")
    return path


def test_flag_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("GTA_TIKTOK_AUTO_DRAFT_ENABLED", raising=False)
    assert bridge_enabled() is False
    monkeypatch.setenv("GTA_TIKTOK_AUTO_DRAFT_ENABLED", "1")
    assert bridge_enabled() is True


def test_hashtags_are_normalized() -> None:
    out = normalize_hashtags(["#gol", "gol", "##gta6", "", "GOL", "melhor, momento"])
    tags = out.split()
    assert "," not in out and "##" not in out
    assert tags == ["#gol", "#gta6", "#melhor", "#momento"]  # sem duplicadas (gol/GOL)


def test_caption_has_description_credits_hashtags_and_varies() -> None:
    d0, c0, h0 = gta_tiktok_text("Perseguição insana", ["#gta"], seed=0)
    d1, _, _ = gta_tiktok_text("Perseguição insana", ["#gta"], seed=1)
    assert "Perseguição insana" in d0 and c0.startswith("Créditos:") and h0.startswith("#")
    assert d0 != d1  # gancho varia por seed


def test_only_vertical_masters_go_to_tiktok(tmp_path) -> None:
    result = _bridge(FakeClient(), asset=HORIZONTAL).bridge(_master(tmp_path))
    assert result["status"] == "skipped" and result["reason"].startswith("nao_vertical")


def test_missing_master_never_downloads(tmp_path) -> None:
    result = _bridge(FakeClient()).bridge(tmp_path / "inexistente.mp4")
    assert result["status"] == "error" and result["reason"] == "master_inexistente"


def test_creates_only_tiktok_job_with_upload_draft(tmp_path) -> None:
    client = FakeClient({"profile_destinations": [{"id": "dest-tt", "account_id": "acc-tt", "enabled": True}]})
    result = _bridge(client).bridge(_master(tmp_path), title="Corte GTA")
    assert result["status"] == "created"
    jobs = client.inserts["publication_jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["platform"] == "tiktok_standard"
    assert job["metadata"]["publication_mode"] == "upload_draft"
    assert job["publication_key"] == "gta-tiktok:default:tiktok_standard:a1b2c3d4e5"
    # Nunca cria YouTube/Instagram.
    assert all(j["platform"] == "tiktok_standard" for j in jobs)
    # Usa o master original (nome do arquivo), não baixa de lugar nenhum.
    assert job["metadata"]["download_filename"] == "corte_gta_vertical.mp4"


def test_idempotent_when_tiktok_job_already_active(tmp_path) -> None:
    client = FakeClient({
        "media_assets": [{"asset_id": "asset-1"}],
        "publication_jobs": [{"status": "processing"}],
        "profile_destinations": [{"id": "dest-tt", "account_id": "acc-tt", "enabled": True}],
    })
    result = _bridge(client).bridge(_master(tmp_path))
    assert result["status"] == "skipped" and result["reason"] == "tiktok_job_ja_existe"
    assert "publication_jobs" not in client.inserts  # nada inserido


def test_youtube_or_instagram_job_does_not_block_tiktok(tmp_path) -> None:
    # A checagem de duplicidade filtra por platform=tiktok_standard; um job de outro
    # destino no mesmo asset não impede a criação do TikTok (dedup por destino).
    client = FakeClient({
        "media_assets": [{"asset_id": "asset-1"}],
        "publication_jobs": [],  # select ja filtrado por tiktok_standard -> vazio
        "profile_destinations": [{"id": "dest-tt", "account_id": "acc-tt", "enabled": True}],
    })
    result = _bridge(client).bridge(_master(tmp_path))
    assert result["status"] == "created"


def test_failed_job_allows_retry(tmp_path) -> None:
    client = FakeClient({
        "media_assets": [{"asset_id": "asset-1"}],
        "publication_jobs": [{"status": "failed"}],  # failed não bloqueia
        "profile_destinations": [{"id": "dest-tt", "account_id": "acc-tt", "enabled": True}],
    })
    result = _bridge(client).bridge(_master(tmp_path))
    assert result["status"] == "created"


def test_dry_run_inserts_nothing(tmp_path) -> None:
    client = FakeClient({"profile_destinations": [{"id": "dest-tt", "account_id": "acc-tt", "enabled": True}]})
    result = _bridge(client).bridge(_master(tmp_path), dry_run=True)
    assert result["status"] == "dry_run" and result["hashtags"].startswith("#")
    assert client.inserts == {}


def test_disabled_destination_skips(tmp_path) -> None:
    client = FakeClient({"profile_destinations": [{"id": "dest-tt", "account_id": "acc-tt", "enabled": False}]})
    result = _bridge(client).bridge(_master(tmp_path))
    assert result["status"] == "skipped" and result["reason"] == "destino_tiktok_desabilitado"


def test_blocking_states_never_include_failure_states() -> None:
    assert "failed" not in bridge.BLOCKING_JOB_STATES
    assert "rejected" not in bridge.BLOCKING_JOB_STATES
    assert "cancelled" not in bridge.BLOCKING_JOB_STATES
    assert "published_manual" in bridge.BLOCKING_JOB_STATES
