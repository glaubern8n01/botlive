from pathlib import Path

import tiktok_public_server as server


def test_public_server_does_not_log_or_render_secrets() -> None:
    source = Path("tiktok_public_server.py").read_text(encoding="utf-8")
    assert "access_token}</" not in source
    assert "refresh_token}</" not in source
    assert "client_secret}</" not in source
    assert "HttpOnly" in source and "Secure" in source and "SameSite=Lax" in source


def test_destructive_public_actions_require_oauth_session() -> None:
    source = Path("tiktok_public_server.py").read_text(encoding="utf-8")
    assert "if not self.authenticated_session()" in source
    assert "Conecte a conta pelo Login Kit" in source


def test_official_url_verification_file_is_served_without_changes() -> None:
    source = Path("tiktok_public_server.py").read_text(encoding="utf-8")
    signature = Path("tiktokQB4aDnyXfm23OX24SCdb2xCIevRlnjpE.txt")
    assert signature.is_file() and signature.stat().st_size > 0
    assert signature.name in source
    assert "read_bytes()" in source


def test_connection_sync_sends_metadata_but_never_tokens(monkeypatch) -> None:
    calls = []

    def fake_request(path, *, method="GET", payload=None):
        calls.append((path, method, payload))
        if path.startswith("platform_accounts?"):
            return [{"id": "account-id"}]
        return None

    monkeypatch.setattr(server, "_supabase_request", fake_request)
    server.sync_connection_metadata({
        "access_token": "must-not-leave-token-store",
        "refresh_token": "must-not-leave-token-store",
        "open_id": "creator-open-id",
        "scope": "video.upload,user.info.basic",
        "expires_at": 1_800_000_000,
        "refresh_expires_at": 1_900_000_000,
    })

    payload = calls[1][2]
    assert calls[1][1] == "POST"
    assert payload["account_id"] == "account-id"
    assert payload["connection_status"] == "connected"
    assert payload["granted_scopes"] == ["user.info.basic", "video.upload"]
    assert "access_token" not in payload
    assert "refresh_token" not in payload
