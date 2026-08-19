"""Variacoes de edicao a partir de um mesmo material.

Para que serve: publicar o mesmo video, sem alteracao, em varias contas faz o
Instagram tratar como conteudo repetido e derrubar o alcance. Cada conta
precisa receber um corte com identidade propria.

Para que NAO serve: isto nao existe para disfarcar material de terceiro. A
fonte continua tendo que ser autorizada (sources.py), e o credito da origem
continua obrigatorio no plano (adapt.py). Variar edicao de material que voce
nao pode usar nao torna o uso legitimo - so torna a violacao mais dificil de
ver.

Cada variacao e deterministica: a mesma semente devolve sempre o mesmo plano,
entao da para reproduzir e auditar o que foi publicado em cada conta.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from .store import ImportError_


# Faixas escolhidas para mudar o arquivo de verdade sem estragar o video.
# Velocidade fora de 0.94-1.06 fica audivel; recorte fora de 0.35-0.65 corta
# o assunto; trim acima de 1.2s costuma comer o gancho dos primeiros frames.
VELOCIDADES = (0.95, 0.97, 1.0, 1.03, 1.05)
FOCOS = (0.38, 0.44, 0.5, 0.56, 0.62)
TRIMS = (0.0, 0.3, 0.6, 0.9, 1.2)
POSICOES = ("inferior", "superior", "centro")
LAYOUTS = ("vertical-fit", "vertical-crop")


@dataclass(frozen=True)
class Variacao:
    indice: int
    semente: str
    layout: str
    focus_x: float
    velocidade: float
    trim_inicial: float
    posicao_texto: str
    sufixo_titulo: str

    def como_plano(self, base: dict) -> dict:
        """Funde a variacao no plano de adaptacao, sem apagar o que ja veio."""
        plano = dict(base or {})
        plano["layout"] = self.layout
        plano["focus_x"] = self.focus_x
        titulo = (plano.get("title") or "").strip()
        if self.sufixo_titulo and titulo:
            plano["title"] = f"{titulo} {self.sufixo_titulo}".strip()
        return plano


def _semente(item_id: str, indice: int) -> str:
    return hashlib.sha256(f"{item_id}:{indice}".encode("utf-8")).hexdigest()[:16]


def _escolher(semente: str, posicao: int, opcoes):
    """Escolha estavel: mesma semente e mesma posicao dao sempre o mesmo item."""
    fatia = semente[posicao * 2 : posicao * 2 + 2] or "00"
    return opcoes[int(fatia, 16) % len(opcoes)]


def gerar(item_id: str, quantidade: int, sufixos=None) -> list:
    """Monta N variacoes distintas e reproduziveis para um item.

    sufixos: textos opcionais por variacao (ex.: o @ de cada conta), para o
    titulo tambem mudar entre elas.
    """
    if quantidade < 1:
        raise ImportError_("Quantidade de variacoes precisa ser ao menos 1")
    if quantidade > len(VELOCIDADES) * len(FOCOS):
        raise ImportError_(
            f"Quantidade alta demais para variar de verdade (maximo "
            f"{len(VELOCIDADES) * len(FOCOS)}); acima disso as edicoes se repetem"
        )
    sufixos = list(sufixos or [])

    variacoes = []
    vistos = set()
    for indice in range(quantidade):
        semente = _semente(item_id, indice)
        candidata = Variacao(
            indice=indice,
            semente=semente,
            layout=_escolher(semente, 0, LAYOUTS),
            focus_x=_escolher(semente, 1, FOCOS),
            velocidade=_escolher(semente, 2, VELOCIDADES),
            trim_inicial=_escolher(semente, 3, TRIMS),
            posicao_texto=_escolher(semente, 4, POSICOES),
            sufixo_titulo=sufixos[indice] if indice < len(sufixos) else "",
        )
        assinatura = (candidata.layout, candidata.focus_x, candidata.velocidade,
                      candidata.trim_inicial)
        # Colisao acontece: empurra a velocidade ate a assinatura ficar unica.
        tentativa = 0
        while assinatura in vistos and tentativa < len(VELOCIDADES):
            nova_velocidade = VELOCIDADES[(VELOCIDADES.index(candidata.velocidade) + 1 + tentativa) % len(VELOCIDADES)]
            candidata = Variacao(**{**asdict(candidata), "velocidade": nova_velocidade})
            assinatura = (candidata.layout, candidata.focus_x, candidata.velocidade,
                          candidata.trim_inicial)
            tentativa += 1
        vistos.add(assinatura)
        variacoes.append(candidata)
    return variacoes


def assinatura(variacao: Variacao) -> str:
    """Identificador curto da edicao, para registrar o que foi para cada conta."""
    bruto = f"{variacao.layout}:{variacao.focus_x}:{variacao.velocidade}:{variacao.trim_inicial}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]


def distintas(variacoes: list) -> bool:
    return len({assinatura(v) for v in variacoes}) == len(variacoes)
