from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from .compliance import evaluate_signal

COMMENTS = [
    ("preco", "O desconto vale hoje?"),
    ("prazo", "Qual é o prazo de entrega?"),
    ("funcionamento", "Como funciona?"),
    ("tamanho", "Tem outro tamanho?"),
]

def scenario(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    events: list[dict] = [{"type": "session.started", "payload": {"seed": seed}}]
    viewers = 120
    for tick in range(1, 15):
        viewers = max(0, viewers + rng.randint(-12, 24))
        events.append({"type": "viewer.count_changed", "payload": {"count": viewers, "tick": tick}})
        if tick in {2, 4, 7, 11}:
            intent, text = COMMENTS[(tick + seed) % len(COMMENTS)]
            events.append({"type": "comment.received", "payload": {"id": f"c-{seed}-{tick}", "author": f"Cliente {rng.randint(1, 99):02d}", "text": text, "intent": intent, "priority": rng.randint(78, 98)}})
        if tick in {5, 10}:
            events.append({"type": "order.detected", "payload": {"quantity": 1, "amount": round(rng.uniform(49, 129), 2), "simulated": True}})
        if tick == 6: events.append({"type": "audio.level", "payload": {"db": -18.4, "muted": False}})
        if tick == 8: events.append({"type": "audio.muted", "payload": {"value": True}})
        if tick == 9: events.append({"type": "video.freeze_seconds", "payload": {"value": 9}})
        if tick == 12: events.append({"type": "connection.packet_loss", "payload": {"value": .18, "latency_ms": 380}})
        if tick == 13: events.append({"type": "connection.recovered", "payload": {"latency_ms": 44}})
    events.append({"type": "session.ended", "payload": {"reason": "scenario_complete"}})
    return events

async def stream(seed: int = 42, speed: float = 1.0, paused: asyncio.Event | None = None, stopped: asyncio.Event | None = None) -> AsyncIterator[dict]:
    for sequence, event in enumerate(scenario(seed), 1):
        if stopped and stopped.is_set(): return
        while paused and paused.is_set():
            if stopped and stopped.is_set(): return
            await asyncio.sleep(.05)
        event = {**event, "sequence": sequence}
        signal_value = event.get("payload", {}).get("value")
        alerts = evaluate_signal(event["type"], signal_value) if signal_value is not None else []
        yield event
        for alert in alerts:
            yield {"type": "compliance.warning_received", "sequence": sequence, "payload": alert}
        await asyncio.sleep(.25 / speed)
