from __future__ import annotations
import asyncio
from fastapi import WebSocket

CLIENTS: set[WebSocket] = set()
CLIENT_LOCKS: dict[WebSocket, asyncio.Lock] = {}

async def broadcast(event: dict) -> None:
    stale=[]
    for client in list(CLIENTS):
        try:
            lock=CLIENT_LOCKS.get(client)
            if lock:
                async with lock: await client.send_json(event)
        except Exception: stale.append(client)
    for client in stale:
        CLIENTS.discard(client);CLIENT_LOCKS.pop(client,None)
