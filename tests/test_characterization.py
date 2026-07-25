from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import instagram_publisher
import publisher
import social_publisher
import yt_publisher
from dedup import timestamps_colidentes
from watcher import VigiaConfig


REPO_DIR = Path(__file__).resolve().parents[1]


def test_cli_help_preserves_current_modes_and_publish_flags() -> None:
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "live-clips" in result.stdout
    assert "vod-clips" in result.stdout
    assert "--post-youtube" in result.stdout
    assert "--post-instagram" in result.stdout


def test_legacy_vigia_defaults_remain_unchanged() -> None:
    config = VigiaConfig()

    assert config.enabled is False
    assert config.vod_mode_enabled is True
    assert config.content_filter == "gta"
    assert config.clip_duration_seconds == 45
    assert config.post_youtube_enabled is False
    assert config.post_instagram_enabled is False


def test_manifest_generation_keeps_current_shape_without_external_calls(
    monkeypatch, tmp_path: Path
) -> None:
    clip = tmp_path / "corte_demo.mp4"
    clip.write_bytes(b"video")
    vertical = tmp_path / "corte_demo_vertical.mp4"

    monkeypatch.setattr(
        publisher,
        "transcrever_fala",
        lambda _path: SimpleNamespace(text="fala teste", error=None),
    )
    monkeypatch.setattr(
        publisher,
        "gerar_legenda",
        lambda *_args, **_kwargs: SimpleNamespace(
            legenda="LEGENDA TESTE",
            hashtags=("#teste",),
            source="mock",
            weak=False,
            model=None,
            error=None,
            prompt_tokens=0,
            completion_tokens=0,
        ),
    )
    monkeypatch.setattr(
        publisher,
        "renderizar_vertical_meme",
        lambda _input, output, _texts: Path(output).write_bytes(b"vertical"),
    )
    monkeypatch.setattr(
        publisher,
        "validar_video_final",
        lambda _path, require_audio=False: SimpleNamespace(valid=True, reason="ok"),
    )

    manifest = publisher.publicar_corte(clip, nicho="gta")
    saved = json.loads((tmp_path / "corte_demo_publish.json").read_text(encoding="utf-8"))

    assert manifest["horizontal"] == str(clip)
    assert manifest["vertical"] == str(vertical)
    assert manifest["legenda"] == "LEGENDA TESTE"
    assert saved["hashtags"] == ["#teste"]
    assert saved["transcricao"] == "fala teste"
    assert "tempos_s" in saved


def test_temporal_dedup_preserves_current_collision_rules() -> None:
    indexed = [{"clip_start_vod": 100, "clip_end_vod": 140}]

    assert timestamps_colidentes([80, 120, 170], indexed, 30, 10) == {80, 120}


def test_social_dispatch_is_lazy_idempotent_and_records_account(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    class FakePlugin:
        @staticmethod
        def postar_corte_registro(_registro, config):
            calls.append(config.conta)
            return {"erro": None, "external_id": "123"}

    monkeypatch.setattr(social_publisher, "_carregar_plugin", lambda _rede: FakePlugin)
    path = tmp_path / "publish.json"
    record: dict = {}
    config = social_publisher.SocialConfig(redes=("youtube",), conta="principal")

    social_publisher.postar_redes(record, config, json_path=path)
    social_publisher.postar_redes(record, config, json_path=path)

    assert calls == ["principal"]
    assert record["postagens"]["youtube"]["conta"] == "principal"
    assert json.loads(path.read_text(encoding="utf-8"))["postagens"]["youtube"]["external_id"] == "123"


def test_youtube_metadata_is_built_without_api_calls() -> None:
    record = {
        "legenda": "Grande momento",
        "hashtags": ["#futebol"],
        "credito_streamer": "@streamer",
        "horizontal": "horizontal.mp4",
        "vertical": "vertical.mp4",
    }

    metadata = yt_publisher.montar_metadados(record, "vertical", "unlisted")

    assert metadata["visibilidade"] == "unlisted"
    assert "#shorts" in metadata["descricao"]
    assert metadata["titulo"]


def test_instagram_payload_is_built_without_api_calls() -> None:
    payload = instagram_publisher.montar_post(
        {
            "legenda": "Grande momento",
            "hashtags": ["#futebol"],
            "credito_streamer": "@streamer",
        }
    )

    assert payload["media_type"] == "REELS"
    assert payload["upload_type"] == "resumable"
    assert "#futebol" in payload["caption"]
