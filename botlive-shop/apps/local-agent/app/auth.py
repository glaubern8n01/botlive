import hmac
import os
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
