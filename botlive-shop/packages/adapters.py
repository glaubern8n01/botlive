from dataclasses import dataclass
from typing import Protocol, Callable

@dataclass(frozen=True)
class Capability:
    origin: str
    confidence: str
    method: str
    consent_required: bool
    risk: str
    available: bool
    validated_at: str

class LivePlatformAdapter(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def state(self) -> dict: ...
    def subscribe(self, handler: Callable[[dict], None]) -> Callable[[], None]: ...
    def list_products(self) -> list[dict]: ...

class MockLiveAdapter:
    capability = Capability("local", "alta", "simulador", False, "baixo", True, "2026-08-08")
    def __init__(self, seed: int = 42): self.seed, self.connected, self._handlers = seed, False, []
    def connect(self): self.connected = True
    def disconnect(self): self.connected = False
    def state(self): return {"status": "simulation" if self.connected else "disconnected", "seed": self.seed}
    def subscribe(self, handler):
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler) if handler in self._handlers else None
    def list_products(self): return []
