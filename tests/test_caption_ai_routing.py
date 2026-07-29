from __future__ import annotations

import json
import urllib.error

import caption_ai


def _clear_ai_env(monkeypatch) -> None:
    monkeypatch.setattr(caption_ai, "_carregar_dotenv", lambda: None)
    for name in (
        "GEMINI_API_KEYS",
        "GEMINI_MODEL",
        "GEMINI_BASE_URL",
        "PUBLISH_AI_PROVIDER",
        "PUBLISH_AI_API_KEY",
        "PUBLISH_AI_BASE_URL",
        "PUBLISH_AI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_configs_put_each_gemini_key_before_claude(monkeypatch) -> None:
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEYS", "gem-1, gem-2")
    monkeypatch.setenv("PUBLISH_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("PUBLISH_AI_API_KEY", "claude-key")
    monkeypatch.setenv("PUBLISH_AI_MODEL", "claude-haiku")

    configs = caption_ai._configs()

    assert [item["provider"] for item in configs] == ["gemini", "gemini", "anthropic"]
    assert [item["api_key"] for item in configs] == ["gem-1", "gem-2", "claude-key"]


def test_quota_failure_rotates_gemini_key_without_calling_claude(monkeypatch) -> None:
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEYS", "gem-1,gem-2")
    monkeypatch.setenv("PUBLISH_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("PUBLISH_AI_API_KEY", "claude-key")
    monkeypatch.setenv("PUBLISH_AI_MODEL", "claude-haiku")
    calls: list[str] = []

    def fake_gemini(_text, _nicho, config):
        calls.append(config["api_key"])
        if config["api_key"] == "gem-1":
            raise urllib.error.HTTPError("url", 429, "quota", {}, None)
        return json.dumps(
            {"legenda": "deu certo", "forca": "forte", "hashtags": ["#gta"]}
        ), 10, 5

    monkeypatch.setattr(caption_ai, "_chamar_api_gemini", fake_gemini)
    monkeypatch.setattr(
        caption_ai,
        "_chamar_api_anthropic",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Claude nao deveria ser chamado")),
    )

    result = caption_ai.gerar_legenda("uma fala", nicho="gta")

    assert calls == ["gem-1", "gem-2"]
    assert result.source == "ia"
    assert result.model == "gemini-flash-latest"
    assert result.legenda == "DEU CERTO"


def test_claude_is_used_only_after_all_gemini_keys_fail(monkeypatch) -> None:
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEYS", "gem-1,gem-2")
    monkeypatch.setenv("PUBLISH_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("PUBLISH_AI_API_KEY", "claude-key")
    monkeypatch.setenv("PUBLISH_AI_MODEL", "claude-haiku")
    calls: list[str] = []

    def fake_gemini(_text, _nicho, config):
        calls.append(config["api_key"])
        raise RuntimeError("quota")

    def fake_claude(_text, _nicho, config):
        calls.append(config["api_key"])
        return '{"legenda":"fallback pago","forca":"forte","hashtags":["#live"]}', 8, 4

    monkeypatch.setattr(caption_ai, "_chamar_api_gemini", fake_gemini)
    monkeypatch.setattr(caption_ai, "_chamar_api_anthropic", fake_claude)

    result = caption_ai.gerar_legenda("uma fala")

    assert calls == ["gem-1", "gem-2", "claude-key"]
    assert result.source == "ia"
    assert result.model == "claude-haiku"
