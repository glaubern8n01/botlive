import hmac
import hashlib
import os
import time
from fastapi import Header, HTTPException, WebSocket

def auth_disabled() -> bool:
    return os.getenv("SHOP_LIVE_AUTH_DISABLED", "false").lower() == "true"

def configured_token() -> str:
    return os.getenv("SHOP_LIVE_LOCAL_TOKEN", "")

def valid_token(candidate: str | None) -> bool:
    if auth_disabled(): return True
    expected = configured_token()
    return bool(expected and candidate and hmac.compare_digest(candidate, expected))

def require_http_auth(x_shop_live_token: str | None = Header(default=None)) -> None:
    if not valid_token(x_shop_live_token):
        raise HTTPException(status_code=401, detail="Token local inválido")

async def require_websocket_auth(socket: WebSocket) -> bool:
    return valid_token(socket.query_params.get("token"))

def media_ticket(media_id: str, expires: int) -> str:
    secret=configured_token() or "controlled-test-only"
    return hmac.new(secret.encode(),f"{media_id}:{expires}".encode(),hashlib.sha256).hexdigest()

def valid_media_ticket(media_id: str, expires: int, candidate: str | None) -> bool:
    return bool(candidate and expires >= int(time.time()) and expires <= int(time.time())+600 and hmac.compare_digest(media_ticket(media_id,expires),candidate))

def websocket_ticket(expires: int) -> str:
    secret=configured_token() or "controlled-test-only"
    return hmac.new(secret.encode(),f"websocket:{expires}".encode(),hashlib.sha256).hexdigest()

def valid_websocket_ticket(expires: int, candidate: str | None) -> bool:
    return bool(candidate and expires >= int(time.time()) and expires <= int(time.time())+180 and hmac.compare_digest(websocket_ticket(expires),candidate))
