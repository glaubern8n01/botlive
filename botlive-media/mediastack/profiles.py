"""Perfis de hardware: LOW_RESOURCE, BALANCED, QUALITY.

O documento pede para nao baixar modelo gigante sem avaliar hardware. O perfil
e o orcamento: provider que pede mais VRAM ou RAM do que o perfil permite
simplesmente nao entra na selecao.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Perfil:
    nome: str
    vram_gb: float
    ram_gb: float
    descricao: str

    def cabe(self, provider) -> bool:
        return provider.vram_gb <= self.vram_gb and provider.ram_gb <= self.ram_gb


LOW_RESOURCE = Perfil(
    "LOW_RESOURCE", 6.0, 16.0,
    "Maquina sem GPU dedicada forte. Prioriza modelo pequeno e quantizado.",
)
BALANCED = Perfil(
    "BALANCED", 12.0, 32.0,
    "GPU intermediaria. Equilibra qualidade e tempo de render.",
)
QUALITY = Perfil(
    "QUALITY", 24.0, 64.0,
    "GPU dedicada grande. Libera os modelos maiores.",
)

PERFIS = {x.nome: x for x in (LOW_RESOURCE, BALANCED, QUALITY)}


def obter(nome: str | None = None) -> Perfil:
    escolhido = (nome or os.getenv("MEDIA_PROFILE", "LOW_RESOURCE")).strip().upper()
    if escolhido not in PERFIS:
        raise ValueError(f"Perfil desconhecido: {escolhido}. Use {sorted(PERFIS)}")
    return PERFIS[escolhido]


def cabe_no_hardware(perfil: Perfil, vram_gb: float | None, ram_gb: float | None) -> bool | None:
    """None quando a ferramenta ainda nao foi medida: sem dado nao ha veredito."""
    if vram_gb is None or ram_gb is None:
        return None
    return vram_gb <= perfil.vram_gb and ram_gb <= perfil.ram_gb
