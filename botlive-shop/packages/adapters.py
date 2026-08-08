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

class TikTokShopOfficialAdapter:
    """Contrato inerte para a Open Platform oficial; nunca usa cookies, DOM ou credenciais implícitas."""
    capability = Capability("TikTok Shop Open Platform", "documentada", "API V2 + OAuth + webhooks", True, "alto", False, "2026-08-08")
    def __init__(self, app_key: str | None = None, access_token: str | None = None, shop_cipher: str | None = None):
        self.app_key,self.access_token,self.shop_cipher=app_key,access_token,shop_cipher
    def readiness(self):
        missing=[name for name,value in {"app_key":self.app_key,"access_token":self.access_token,"shop_cipher":self.shop_cipher}.items() if not value]
        return {"ready":not missing,"missing":missing,"external_actions":False,"live_studio_control":False}
    def connect(self):
        raise RuntimeError("Adapter oficial desativado: requer app aprovado, escopos e autorização explícita do seller")
    def disconnect(self): return None
    def state(self): return self.readiness()
    def subscribe(self, handler): return lambda: None
    def list_products(self):
        raise RuntimeError("Consulta externa não executada sem credenciais e autorização explícita")
