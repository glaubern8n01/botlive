from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib import parse, request

from cryptography.fernet import Fernet, InvalidToken

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
USER_INFO_URL = (
    "https://open.tiktokapis.com/v2/user/info/"
    "?fields=open_id,union_id,avatar_url,display_name"
)
DEFAULT_SCOPES = ("user.info.basic", "video.upload")


class TikTokOAuthError(RuntimeError):
    pass


def _urlsafe_key(raw: str) -> bytes:
    try:
        key = raw.encode("ascii")
        Fernet(key)
        return key
    except (ValueError, UnicodeEncodeError):
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


class EncryptedTokenStore:
    """Atomic encrypted server-side token storage; never returns secrets to the UI."""

    def __init__(self, root: Path, encryption_key: str) -> None:
        if not encryption_key:
            raise TikTokOAuthError("token encryption key is not configured")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.fernet = Fernet(_urlsafe_key(encryption_key))

    def _path(self, account_key: str) -> Path:
        safe = "".join(c for c in account_key if c.isalnum() or c in "-_")
        if not safe or safe != account_key:
            raise TikTokOAuthError("invalid account key")
        return self.root / f"{safe}.token"

    def save(self, account_key: str, value: Mapping[str, Any]) -> str:
        payload = json.dumps(dict(value), separators=(",", ":")).encode("utf-8")
        target = self._path(account_key)
        fd, name = tempfile.mkstemp(prefix=".tiktok-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self.fernet.encrypt(payload))
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return f"tiktok-encrypted:{account_key}"

    def load(self, account_key: str) -> dict[str, Any]:
        try:
            raw = self.fernet.decrypt(self._path(account_key).read_bytes())
            value = json.loads(raw)
        except (OSError, InvalidToken, json.JSONDecodeError) as exc:
            raise TikTokOAuthError("authorization is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise TikTokOAuthError("invalid authorization record")
        return value

    def delete(self, account_key: str) -> bool:
        try:
            self._path(account_key).unlink()
            return True
        except FileNotFoundError:
            return False

    def status(self, account_key: str) -> dict[str, Any]:
        value = self.load(account_key)
        expires_at = int(value.get("expires_at") or 0)
        return {
            "connected": bool(value.get("access_token")),
            "open_id": value.get("open_id"),
            "scope": sorted(set(str(value.get("scope") or "").split(",")) - {""}),
            "expires_at": expires_at or None,
            "token_valid": expires_at > int(time.time()) + 30,
        }


@dataclass(frozen=True)
class OAuthState:
    value: str
    expires_at: int


class OAuthStateStore:
    def __init__(self, root: Path, ttl_seconds: int = 600) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def issue(self) -> OAuthState:
        value = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + self.ttl_seconds
        digest = hashlib.sha256(value.encode()).hexdigest()
        (self.root / digest).write_text(str(expires_at), encoding="ascii")
        return OAuthState(value, expires_at)

    def consume(self, value: str) -> bool:
        if not value:
            return False
        path = self.root / hashlib.sha256(value.encode()).hexdigest()
        try:
            expires_at = int(path.read_text(encoding="ascii"))
            path.unlink()
        except (OSError, ValueError):
            return False
        return expires_at >= int(time.time())


class TikTokOAuthClient:
    def __init__(self, client_key: str, client_secret: str, redirect_uri: str) -> None:
        self.client_key = client_key
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorization_url(self, state: str, scopes: tuple[str, ...] = DEFAULT_SCOPES) -> str:
        query = parse.urlencode(
            {
                "client_key": self.client_key,
                "response_type": "code",
                "scope": ",".join(scopes),
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    def _form(self, url: str, data: Mapping[str, str]) -> dict[str, Any]:
        req = request.Request(
            url,
            data=parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.load(response)
        except Exception as exc:
            raise TikTokOAuthError("TikTok authorization request failed") from exc
        if not isinstance(payload, dict):
            raise TikTokOAuthError("TikTok rejected the authorization request")
        api_error = payload.get("error")
        if isinstance(api_error, dict) and api_error.get("code") in {None, "", "ok"}:
            api_error = None
        if api_error:
            raise TikTokOAuthError("TikTok rejected the authorization request")
        return payload

    def exchange_code(self, code: str) -> dict[str, Any]:
        value = self._form(
            TOKEN_URL,
            {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
        )
        now = int(time.time())
        value["expires_at"] = now + int(value.get("expires_in") or 0)
        value["refresh_expires_at"] = now + int(value.get("refresh_expires_in") or 0)
        return value

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        value = self._form(
            TOKEN_URL,
            {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        now = int(time.time())
        value["expires_at"] = now + int(value.get("expires_in") or 0)
        value["refresh_expires_at"] = now + int(value.get("refresh_expires_in") or 0)
        return value

    def revoke(self, access_token: str) -> None:
        self._form(
            REVOKE_URL,
            {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "token": access_token,
            },
        )
