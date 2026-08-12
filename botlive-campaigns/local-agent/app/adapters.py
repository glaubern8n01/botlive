from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class Adapter:
    id: str
    label: str
    mode: str = "manual"
    official_api_verified: bool = False
    supports_import: bool = False
    notes: str = "Cadastro e envio manuais; confirme regras dentro da plataforma."

ADAPTERS = {
    item.id: item for item in (
        Adapter("networking-club", "Networking Club"),
        Adapter("viewx", "ViewX"),
        Adapter("manual", "Plataforma genérica"),
    )
}

def public_adapters():
    return [asdict(item) for item in ADAPTERS.values()]

