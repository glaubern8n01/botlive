"""Diretorio de plataformas de campanha.

Nenhuma delas tem integracao automatica. O adapter existe como referencia de
cadastro: guarda o que foi verificado, o que segue sem confirmacao e o que a
plataforma proibe. Login e scraping nesses sites nao sao automatizados.
"""

from dataclasses import dataclass, asdict, field

from .platform_catalog import PLATFORMS


@dataclass(frozen=True)
class Adapter:
    id: str
    label: str
    mode: str = "manual"
    official_api_verified: bool = False
    supports_import: bool = False
    country: str = ""
    url: str = ""
    confidence: str = "low"
    unconfirmed: tuple = field(default_factory=tuple)
    prohibits: tuple = field(default_factory=tuple)
    notes: str = "Cadastro e envio manuais; confirme regras dentro da plataforma."


def _do_catalogo(item):
    return Adapter(
        id=item["id"],
        label=item["label"],
        mode=item.get("integration", "manual"),
        country=item.get("country", ""),
        url=item.get("url", ""),
        confidence=item.get("confidence", "low"),
        unconfirmed=tuple(item.get("unconfirmed", ())),
        prohibits=tuple(item.get("prohibits", ())),
    )


ADAPTERS = {item["id"]: _do_catalogo(item) for item in PLATFORMS}

# Entrada coringa para campanha de plataforma ainda nao catalogada.
ADAPTERS["manual"] = Adapter("manual", "Plataforma generica")


def public_adapters():
    return [asdict(item) for item in ADAPTERS.values()]
