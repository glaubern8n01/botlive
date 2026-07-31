from __future__ import annotations

import html
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import parse_qs, urlencode, urlparse

from tiktok_oauth import (
    DEFAULT_SCOPES,
    EncryptedTokenStore,
    OAuthStateStore,
    TikTokOAuthClient,
    TikTokOAuthError,
)
from tiktok_platform import TIKTOK_STANDARD_ACCOUNT_KEY

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("tiktok-public")
ROOT = Path(os.getenv("TIKTOK_STANDARD_TOKEN_ROOT", ".tokens/tiktok-standard"))
STATE_ROOT = ROOT / "states"
SESSION_ROOT = ROOT / "sessions"
DASHBOARD_URL = os.getenv("BOTLIVE_DASHBOARD_URL", "https://painel.vextriq.online/tiktok")
CONTACT = os.getenv("BOTLIVE_PRIVACY_CONTACT", "Contato disponível no painel privado BotLive.")
VERIFICATION_FILE = "tiktokQB4aDnyXfm23OX24SCdb2xCIevRlnjpE.txt"


def configured() -> bool:
    return all(
        os.getenv(name)
        for name in (
            "TIKTOK_STANDARD_CLIENT_KEY",
            "TIKTOK_STANDARD_CLIENT_SECRET",
            "TIKTOK_STANDARD_REDIRECT_URI",
            "TIKTOK_STANDARD_TOKEN_ENCRYPTION_KEY",
        )
    )


def oauth() -> TikTokOAuthClient:
    return TikTokOAuthClient(
        os.environ["TIKTOK_STANDARD_CLIENT_KEY"],
        os.environ["TIKTOK_STANDARD_CLIENT_SECRET"],
        os.environ["TIKTOK_STANDARD_REDIRECT_URI"],
    )


def token_store() -> EncryptedTokenStore:
    return EncryptedTokenStore(ROOT, os.environ["TIKTOK_STANDARD_TOKEN_ENCRYPTION_KEY"])


def _iso_timestamp(value: object) -> str | None:
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return None
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def _supabase_request(path: str, *, method: str = "GET", payload: object | None = None) -> object:
    base_url = os.getenv("ROBO_SUPABASE_URL", "").rstrip("/")
    api_key = os.getenv("ROBO_SUPABASE_KEY", "")
    if not base_url or not api_key:
        raise RuntimeError("Supabase metadata sync is not configured")
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    req = request.Request(
        f"{base_url}/rest/v1/{path}", data=body, method=method,
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal,resolution=merge-duplicates",
        },
    )
    with request.urlopen(req, timeout=20) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def sync_connection_metadata(tokens: dict[str, object]) -> None:
    """Expose only non-secret OAuth state to the private dashboard."""
    accounts = _supabase_request(
        "platform_accounts?platform=eq.tiktok_standard&account_key="
        f"eq.{TIKTOK_STANDARD_ACCOUNT_KEY}&select=id&limit=1"
    )
    if not isinstance(accounts, list) or not accounts:
        raise RuntimeError("TikTok Standard account metadata was not found")
    raw_scope = str(tokens.get("scope") or "")
    scopes = sorted({item.strip() for item in raw_scope.replace(" ", ",").split(",") if item.strip()})
    now = datetime.now(timezone.utc).isoformat()
    _supabase_request(
        "tiktok_standard_connections?on_conflict=account_id", method="POST",
        payload={
            "account_id": accounts[0]["id"],
            "open_id": tokens.get("open_id"),
            "secret_ref": f"tiktok-encrypted:{TIKTOK_STANDARD_ACCOUNT_KEY}",
            "granted_scopes": scopes,
            "token_expires_at": _iso_timestamp(tokens.get("expires_at")),
            "refresh_expires_at": _iso_timestamp(tokens.get("refresh_expires_at")),
            "review_status": "draft",
            "connection_status": "connected",
            "connected_at": now,
            "disconnected_at": None,
            "updated_at": now,
        },
    )


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — BotLive</title>
<style>body{{font:16px system-ui;background:#09090b;color:#f4f4f5;margin:0}}
main{{max-width:760px;margin:auto;padding:40px 20px}}a{{color:#7dd3fc}}
.card{{border:1px solid #3f3f46;border-radius:14px;padding:22px;background:#18181b}}
button,.button{{display:inline-block;background:white;color:#111;padding:11px 16px;border:0;
border-radius:8px;font-weight:700;text-decoration:none}}li{{margin:.65rem 0}}</style></head>
<body><main><h1>{html.escape(title)}</h1><div class="card">{body}</div>
<p><a href="/privacy">Privacidade</a> · <a href="/terms">Termos</a> ·
<a href="/tiktok/data-deletion">Exclusão de dados</a></p></main></body></html>""".encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "BotLiveTikTok/1"

    def log_message(self, fmt: str, *args: object) -> None:
        logger.info("%s %s", self.command, urlparse(self.path).path)

    def send_html(self, status: int, title: str, body: str) -> None:
        payload = page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def authenticated_session(self) -> bool:
        cookies = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                cookies[key] = value
        session = cookies.get("botlive_tiktok_session", "")
        if not session:
            return False
        path = SESSION_ROOT / hashlib.sha256(session.encode()).hexdigest()
        try:
            return int(path.read_text(encoding="ascii")) >= int(time.time())
        except (OSError, ValueError):
            return False

    def issue_session(self) -> str:
        SESSION_ROOT.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(32)
        digest = hashlib.sha256(value.encode()).hexdigest()
        (SESSION_ROOT / digest).write_text(str(int(time.time()) + 86400), encoding="ascii")
        return value

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == f"/{VERIFICATION_FILE}":
            payload = Path(VERIFICATION_FILE).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=300")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return self.wfile.write(payload)
        if url.path == "/health":
            payload = json.dumps({"ok": True, "configured": configured(), "api_enabled": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            return self.wfile.write(payload)
        if url.path == "/privacy":
            return self.send_html(200, "Política de Privacidade", f"""
<p>O BotLive usa a autorização voluntária do TikTok normal para identificar a
conta conectada e, quando habilitado, enviar vídeos próprios ou autorizados.</p>
<h2>Dados</h2><ul><li>nickname, open_id e escopos concedidos;</li>
<li>access token e refresh token, criptografados no servidor;</li>
<li>estado e resultado dos envios solicitados.</li></ul>
<p>Tokens não são exibidos no navegador, vendidos, fornecidos a anunciantes nem
usados pelo projeto separado TikTok Shop. Eles são retidos enquanto a conexão
estiver ativa e removidos na desconexão/exclusão.</p>
<p>O conteúdo só é enviado após ação autorizada pelo usuário. {html.escape(CONTACT)}</p>""")
        if url.path == "/terms":
            return self.send_html(200, "Termos de Uso", """
<p>O BotLive auxilia na criação, revisão e distribuição de vídeos verticais.
O usuário deve possuir os direitos necessários e revisar vídeo, legenda,
privacidade e opções antes de autorizar qualquer envio.</p>
<p>Serviços externos podem falhar. Não há garantia de alcance, monetização ou
disponibilidade. O uso deve respeitar as regras do TikTok.</p>
<p>TikTok Standard e TikTok Shop são projetos separados; estes termos não
habilitam nem integram o TikTok Shop.</p>""")
        if url.path == "/tiktok/connect":
            if not configured():
                return self.send_html(503, "Conectar TikTok", "<p>Integração ainda não configurada.</p>")
            state = OAuthStateStore(STATE_ROOT).issue()
            return self.redirect(oauth().authorization_url(state.value, DEFAULT_SCOPES))
        if url.path == "/auth/tiktok/callback":
            query = parse_qs(url.query)
            if query.get("error"):
                return self.send_html(400, "Autorização não concluída", "<p>O TikTok não concedeu a autorização.</p>")
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            if not OAuthStateStore(STATE_ROOT).consume(state):
                return self.send_html(400, "State inválido", "<p>A solicitação expirou ou já foi utilizada.</p>")
            try:
                tokens = oauth().exchange_code(code)
                token_store().save(TIKTOK_STANDARD_ACCOUNT_KEY, tokens)
            except TikTokOAuthError:
                logger.exception("OAuth callback failed without logging credentials")
                return self.send_html(502, "Falha na conexão", "<p>Não foi possível concluir a autorização.</p>")
            try:
                sync_connection_metadata(tokens)
            except (RuntimeError, OSError, error.URLError, json.JSONDecodeError):
                # Authorization remains valid; metadata can be reconciled later.
                logger.exception("OAuth succeeded but non-secret dashboard metadata sync is pending")
            session = self.issue_session()
            return self.redirect(
                f"{DASHBOARD_URL}?tiktok=connected",
                f"botlive_tiktok_session={session}; Path=/; Max-Age=86400; Secure; HttpOnly; SameSite=Lax",
            )
        if url.path == "/tiktok/disconnect":
            return self.send_html(200, "Desconectar TikTok", """
<p>A desconexão revoga a autorização e remove os tokens armazenados pelo BotLive.
Ela não apaga vídeos. Confirme somente se deseja encerrar a integração.</p>
<form method="post"><button type="submit">Confirmar desconexão</button></form>""")
        if url.path == "/tiktok/data-deletion":
            return self.send_html(200, "Exclusão de dados TikTok", f"""
<p>A exclusão remove a autorização e os tokens da integração TikTok Standard.
Vídeos e registros editoriais não são apagados sem uma solicitação específica.</p>
<form method="post"><button type="submit">Excluir dados da conexão</button></form>
<p>{html.escape(CONTACT)}</p>""")
        return self.send_html(404, "Não encontrado", "<p>A página solicitada não existe.</p>")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/tiktok/disconnect", "/tiktok/data-deletion"}:
            return self.send_html(404, "Não encontrado", "<p>A página solicitada não existe.</p>")
        if not self.authenticated_session():
            return self.send_html(
                403, "Confirmação necessária",
                "<p>Conecte a conta pelo Login Kit neste navegador antes de remover a autorização.</p>",
            )
        if not configured():
            return self.send_html(503, "Integração indisponível", "<p>A integração ainda não está configurada.</p>")
        try:
            value = token_store().load(TIKTOK_STANDARD_ACCOUNT_KEY)
            access_token = str(value.get("access_token") or "")
            if access_token:
                oauth().revoke(access_token)
            token_store().delete(TIKTOK_STANDARD_ACCOUNT_KEY)
        except TikTokOAuthError:
            token_store().delete(TIKTOK_STANDARD_ACCOUNT_KEY)
        payload = page("Conexão removida", """
<p>A autorização e os tokens da integração foram removidos. Nenhum token é
exibido nesta confirmação.</p><p><a class="button" href="/">Concluir</a></p>""")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", "botlive_tiktok_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("TikTok public service listening on port %s; external posting disabled", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
