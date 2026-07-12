from __future__ import annotations

"""Cliente da Twitch Helix API (app access token, client credentials).

NAO confundir com TWITCH_OAUTH_TOKEN do .env: aquele e so do chat IRC
(chat_monitor.py) e continua intocado. Este modulo usa TWITCH_CLIENT_ID +
TWITCH_CLIENT_SECRET (cadastro em dev.twitch.tv/console) para dados publicos:
quem esta ao vivo, viewers por categoria e VODs com stream_id.

CLI de teste (V1 do plano PLANO-VIGIA.md):
    python twitch_api.py top-gta [--language pt] [--min-viewers 100] [--limit 10]
    python twitch_api.py status <login> [<login> ...]
    python twitch_api.py vods <login>
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# Mesma protecao do main.py: console Windows (cp1252) nao encoda emoji e
# titulo de live com emoji nao pode derrubar print nenhum.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

# Tokens ancorados na pasta do repo, como .tokens/youtube/ (funciona de qualquer cwd).
TOKENS_DIR = Path(__file__).resolve().parent / ".tokens" / "twitch"
APP_TOKEN_FILE = TOKENS_DIR / "app_token.json"

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_BASE = "https://api.twitch.tv/helix"

# Renova o token com folga antes de expirar (Helix expira em ~60 dias).
TOKEN_REFRESH_MARGIN_SECONDS = 24 * 3600
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 4


class TwitchAPIError(RuntimeError):
    """Erro de configuracao ou de resposta da Helix que o chamador deve tratar."""


def _credentials() -> tuple[str, str]:
    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise TwitchAPIError(
            "TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET ausentes. Cadastre o app em "
            "dev.twitch.tv/console (client credentials) e defina as envs no .env/EasyPanel."
        )
    return client_id, client_secret


# Python 3.13+ liga VERIFY_X509_STRICT por padrao e cadeias com CA local
# (proxy/antivirus no Windows) falham. Mantemos a verificacao NORMAL de
# certificado e removemos so a flag estrita — mesmo comportamento do 3.12
# que roda no container da VPS.
_SSL_CONTEXT = ssl.create_default_context()
if hasattr(ssl, "VERIFY_X509_STRICT"):
    _SSL_CONTEXT.verify_flags &= ~ssl.VERIFY_X509_STRICT


def _http_json(request: urllib.request.Request, timeout: int = 20) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8"))


class TwitchHelix:
    def __init__(self) -> None:
        self._client_id, self._client_secret = _credentials()
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._game_id_cache: dict[str, str] = {}
        self._load_token_from_disk()

    # ------------------------------------------------------------------ token

    def _load_token_from_disk(self) -> None:
        if not APP_TOKEN_FILE.exists():
            return
        try:
            data = json.loads(APP_TOKEN_FILE.read_text(encoding="utf-8"))
            self._token = data.get("access_token")
            self._token_expires_at = float(data.get("expires_at", 0))
        except (json.JSONDecodeError, ValueError, OSError):
            self._token = None
            self._token_expires_at = 0.0

    def _save_token_to_disk(self) -> None:
        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        APP_TOKEN_FILE.write_text(
            json.dumps({"access_token": self._token, "expires_at": self._token_expires_at}),
            encoding="utf-8",
        )

    def _ensure_token(self, force_refresh: bool = False) -> str:
        if (
            not force_refresh
            and self._token
            and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS
        ):
            return self._token

        body = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            }
        ).encode("ascii")
        request = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        try:
            data = _http_json(request)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise TwitchAPIError(
                f"Falha ao obter app token ({exc.code}): {detail}. "
                "Confira TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET."
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TwitchAPIError(f"Sem conexao com id.twitch.tv: {exc}") from exc

        self._token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 0))
        self._save_token_to_disk()
        print("[twitch] app token renovado.")
        return self._token

    # ---------------------------------------------------------------- request

    def _get(self, path: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        """GET na Helix com renovacao em 401 e backoff em 429/5xx.

        O loop nunca deixa uma falha transitoria virar excecao nao tratada no
        vigia: apos MAX_RETRIES devolve TwitchAPIError para o chamador decidir
        (o vigia pula o ciclo; a CLI mostra o erro).
        """
        url = f"{HELIX_BASE}/{path}?{urllib.parse.urlencode(params)}"
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            token = self._ensure_token()
            request = urllib.request.Request(
                url, headers={"Client-Id": self._client_id, "Authorization": f"Bearer {token}"}
            )
            try:
                return _http_json(request)
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and not refreshed:
                    refreshed = True
                    self._ensure_token(force_refresh=True)
                    continue
                if exc.code in RETRY_STATUS and attempt < MAX_RETRIES:
                    wait = 2**attempt
                    print(f"[twitch] HTTP {exc.code} em {path}; retry em {wait}s...")
                    time.sleep(wait)
                    continue
                detail = exc.read().decode("utf-8", errors="replace")[:200]
                raise TwitchAPIError(f"Helix {path} falhou ({exc.code}): {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < MAX_RETRIES:
                    wait = 2**attempt
                    print(f"[twitch] erro de rede em {path} ({exc}); retry em {wait}s...")
                    time.sleep(wait)
                    continue
                raise TwitchAPIError(f"Helix {path} inacessivel: {exc}") from exc
        raise TwitchAPIError(f"Helix {path}: esgotou as tentativas.")

    # ------------------------------------------------------------------ helix

    def get_game_id(self, name: str) -> str:
        cached = self._game_id_cache.get(name.lower())
        if cached:
            return cached
        data = self._get("games", [("name", name)])
        rows = data.get("data") or []
        if not rows:
            raise TwitchAPIError(f"Categoria nao encontrada na Twitch: {name!r}")
        game_id = str(rows[0]["id"])
        self._game_id_cache[name.lower()] = game_id
        return game_id

    def get_streams_by_game(
        self,
        game_name: str,
        language: Optional[str] = "pt",
        first: int = 100,
    ) -> list[dict[str, Any]]:
        """Lives da categoria, ja ordenadas por viewer_count desc (ordem da API)."""
        params: list[tuple[str, str]] = [
            ("game_id", self.get_game_id(game_name)),
            ("first", str(min(max(first, 1), 100))),
        ]
        if language:
            params.append(("language", language))
        return list((self._get("streams", params)).get("data") or [])

    def get_streams_by_logins(self, logins: list[str]) -> list[dict[str, Any]]:
        """Status ao vivo de ate 100 canais em UMA request. Ausente = offline."""
        if not logins:
            return []
        if len(logins) > 100:
            raise TwitchAPIError("Get Streams aceita no maximo 100 logins por request.")
        params = [("user_login", login.strip().lower()) for login in logins]
        params.append(("first", str(len(logins))))
        return list((self._get("streams", params)).get("data") or [])

    def get_user_id(self, login: str) -> Optional[str]:
        data = self._get("users", [("login", login.strip().lower())])
        rows = data.get("data") or []
        return str(rows[0]["id"]) if rows else None

    def get_videos_archive(self, user_id: str, first: int = 5) -> list[dict[str, Any]]:
        """VODs (type=archive) mais recentes do canal; cada um traz stream_id."""
        params = [("user_id", user_id), ("type", "archive"), ("first", str(first))]
        return list((self._get("videos", params)).get("data") or [])


# ---------------------------------------------------------------------- CLI


def _cmd_top_gta(args: argparse.Namespace) -> None:
    api = TwitchHelix()
    streams = api.get_streams_by_game(args.game, language=args.language or None, first=100)
    filtered = [s for s in streams if int(s.get("viewer_count", 0)) >= args.min_viewers]
    print(
        f"[top] categoria={args.game!r} language={args.language or 'todas'} "
        f"min_viewers={args.min_viewers} | {len(filtered)} de {len(streams)} lives"
    )
    for index, stream in enumerate(filtered[: args.limit], start=1):
        print(
            f"  {index:02d}. {stream['user_login']:<24} {int(stream['viewer_count']):>7} viewers"
            f" | stream_id={stream['id']} | started_at={stream['started_at']}"
            f" | {str(stream.get('title', ''))[:60]}"
        )
    if not filtered:
        print("  (nenhuma live acima do corte agora)")


def _cmd_status(args: argparse.Namespace) -> None:
    api = TwitchHelix()
    live = {s["user_login"].lower(): s for s in api.get_streams_by_logins(args.logins)}
    for login in args.logins:
        stream = live.get(login.strip().lower())
        if stream:
            print(
                f"  AO VIVO  {login:<24} {int(stream['viewer_count']):>7} viewers"
                f" | stream_id={stream['id']} | game_id={stream.get('game_id')}"
                f" | started_at={stream['started_at']}"
            )
        else:
            print(f"  offline  {login}")


def _cmd_vods(args: argparse.Namespace) -> None:
    api = TwitchHelix()
    user_id = api.get_user_id(args.login)
    if not user_id:
        print(f"[vods] canal nao encontrado: {args.login}")
        return
    videos = api.get_videos_archive(user_id, first=args.limit)
    if not videos:
        print(f"[vods] nenhum VOD (archive) visivel para {args.login} (sub-only ou desligado?).")
        return
    for video in videos:
        print(
            f"  {video['url']} | stream_id={video.get('stream_id')}"
            f" | duration={video.get('duration')} | created_at={video.get('created_at')}"
            f" | {str(video.get('title', ''))[:50]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI de teste da Twitch Helix (V1 do vigia).")
    sub = parser.add_subparsers(dest="command", required=True)

    top = sub.add_parser("top-gta", help="Lista lives da categoria por viewers (descoberta aberta).")
    top.add_argument("--game", default="Grand Theft Auto V")
    top.add_argument("--language", default="pt", help="Vazio ('') para todas as linguas.")
    top.add_argument("--min-viewers", type=int, default=100)
    top.add_argument("--limit", type=int, default=10)
    top.set_defaults(func=_cmd_top_gta)

    status = sub.add_parser("status", help="Status ao vivo de canais especificos (lista manual).")
    status.add_argument("logins", nargs="+")
    status.set_defaults(func=_cmd_status)

    vods = sub.add_parser("vods", help="VODs recentes de um canal, com stream_id.")
    vods.add_argument("login")
    vods.add_argument("--limit", type=int, default=5)
    vods.set_defaults(func=_cmd_vods)

    args = parser.parse_args()
    try:
        args.func(args)
    except TwitchAPIError as exc:
        print(f"[twitch][erro] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
