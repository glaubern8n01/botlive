from pathlib import Path


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
