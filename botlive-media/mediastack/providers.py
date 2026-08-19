"""Adapters de provider por capacidade.

Prioridade do projeto, nesta ordem exata:
    LOCAL > GRATUITO > FREE TIER > PAGO

Duas regras que valem mais que a ordem:
  1. provider pago nunca liga sozinho - precisa de autorizacao explicita
     registrada, e nao basta uma variavel de ambiente;
  2. provider pago indisponivel nao pode derrubar o caminho gratuito: se o
     pago some, a selecao cai para o proximo da fila e segue funcionando.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .catalog import CAPACIDADES


TIERS = ("local", "gratuito", "free_tier", "pago")
ORDEM = {tier: indice for indice, tier in enumerate(TIERS)}


class ProviderError(RuntimeError):
    """Falha de selecao de provider, com motivo legivel."""


@dataclass
class Provider:
    id: str
    capacidade: str
    tier: str
    ferramenta_id: str | None = None
    vram_gb: float = 0.0
    ram_gb: float = 2.0
    custo_por_uso: float = 0.0
    disponivel: bool = True
    autorizado: bool = False
    observacao: str = ""

    def __post_init__(self):
        if self.capacidade not in CAPACIDADES:
            raise ProviderError(f"Capacidade desconhecida: {self.capacidade}")
        if self.tier not in TIERS:
            raise ProviderError(f"Tier desconhecido: {self.tier}")
        if self.tier == "pago" and self.custo_por_uso <= 0:
            raise ProviderError("Provider pago precisa declarar custo por uso")
        if self.tier != "pago" and self.custo_por_uso:
            raise ProviderError("Provider nao pago nao pode ter custo")

    @property
    def pago(self) -> bool:
        return self.tier == "pago"

    @property
    def utilizavel(self) -> bool:
        """Pago sem autorizacao explicita nao e utilizavel, nem que esteja de pe."""
        if not self.disponivel:
            return False
        return self.autorizado if self.pago else True


REGISTRO: dict[str, Provider] = {}


def registrar(provider: Provider) -> Provider:
    REGISTRO[provider.id] = provider
    return provider


def limpar() -> None:
    REGISTRO.clear()


def autorizar_pago(provider_id: str, confirmacao: str) -> Provider:
    """Liga um provider pago. Exige a confirmacao literal do operador.

    O texto exigido e proposital: ligar gasto nao pode acontecer por descuido
    de configuracao nem por default de codigo.
    """
    provider = REGISTRO.get(provider_id)
    if not provider:
        raise ProviderError(f"Provider desconhecido: {provider_id}")
    if not provider.pago:
        raise ProviderError("Somente provider pago precisa de autorizacao")
    if confirmacao.strip().lower() != "autorizo custo":
        raise ProviderError("Autorizacao invalida: confirme com 'autorizo custo'")
    provider.autorizado = True
    return provider


def revogar_pago(provider_id: str) -> Provider:
    provider = REGISTRO.get(provider_id)
    if not provider:
        raise ProviderError(f"Provider desconhecido: {provider_id}")
    provider.autorizado = False
    return provider


def candidatos(capacidade: str, orcamento=None) -> list:
    """Providers utilizaveis para a capacidade, ja na ordem de prioridade."""
    if capacidade not in CAPACIDADES:
        raise ProviderError(f"Capacidade desconhecida: {capacidade}")
    itens = [x for x in REGISTRO.values() if x.capacidade == capacidade and x.utilizavel]
    if orcamento:
        itens = [x for x in itens if orcamento.cabe(x)]
    return sorted(itens, key=lambda x: (ORDEM[x.tier], x.custo_por_uso, x.id))


def escolher(capacidade: str, orcamento=None) -> Provider:
    fila = candidatos(capacidade, orcamento)
    if not fila:
        raise ProviderError(
            f"Nenhum provider utilizavel para {capacidade}"
            + (f" dentro do perfil {orcamento.nome}" if orcamento else "")
        )
    return fila[0]


def plano(capacidades=None, orcamento=None) -> dict:
    """Monta o plano de providers, dizendo tambem o que ficou descoberto."""
    alvo = tuple(capacidades or CAPACIDADES)
    escolhidos, faltando = {}, []
    for capacidade in alvo:
        try:
            escolhidos[capacidade] = escolher(capacidade, orcamento)
        except ProviderError:
            faltando.append(capacidade)
    return {
        "perfil": orcamento.nome if orcamento else None,
        "escolhidos": {k: v.id for k, v in escolhidos.items()},
        "tiers": {k: v.tier for k, v in escolhidos.items()},
        "sem_cobertura": faltando,
        "custo_estimado": round(sum(v.custo_por_uso for v in escolhidos.values()), 4),
        "usa_pago": sorted(k for k, v in escolhidos.items() if v.pago),
    }
