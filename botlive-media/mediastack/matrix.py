"""Matriz de decisao e escolha do menor conjunto de ferramentas.

O documento pede: montar a matriz (funcao / qualidade / custo / VRAM / RAM /
licenca / headless / API / CLI / maturidade / integracao) e escolher o menor
conjunto que cubra imagem, video, TTS, transcricao, legendas, montagem,
render, thumbnail e clipping.

Este modulo faz as duas coisas - e se recusa a "escolher" com base em dado que
ninguem levantou. Enquanto as ferramentas estiverem NAO AUDITADO, a selecao
devolve o conjunto como *proposta*, marcada `pronta_para_producao=False`, com
a lista do que falta auditar. Nao existe recomendacao final sem auditoria.
"""

from __future__ import annotations

from . import catalog
from .profiles import Perfil, cabe_no_hardware


COBERTURA_MINIMA = (
    "imagem",
    "video",
    "tts",
    "transcricao",
    "legendas",
    "montagem",
    "render",
    "thumbnail",
    "clipping",
)

COLUNAS = (
    "id",
    "capacidades",
    "prioridade_declarada",
    "licenca",
    "custo",
    "vram_gb",
    "ram_gb",
    "headless",
    "api",
    "cli",
    "maturidade",
    "integracao",
    "auditoria",
)

NAO_MEDIDO = "não medido"


def _celula(valor):
    return NAO_MEDIDO if valor is None else valor


def matriz(perfil: Perfil | None = None) -> list:
    """Uma linha por ferramenta. Campo nao auditado aparece como 'não medido'."""
    linhas = []
    for item in catalog.todas():
        linha = {coluna: _celula(getattr(item, coluna, None)) for coluna in COLUNAS}
        linha["capacidades"] = list(item.capacidades)
        linha["repositorio"] = item.repositorio
        linha["descricao_declarada"] = item.descricao_declarada
        linha["pendencias"] = list(item.pendencias)
        if perfil:
            veredito = cabe_no_hardware(perfil, item.vram_gb, item.ram_gb)
            linha["cabe_no_perfil"] = NAO_MEDIDO if veredito is None else veredito
        linhas.append(linha)
    return sorted(linhas, key=lambda x: (x["auditoria"] != "AUDITADO", x["id"]))


def _peso(item) -> tuple:
    """Ordem de preferencia: auditada, prioridade declarada, mais capacidades."""
    ordem_prioridade = {"muito-alta": 0, "alta": 1, "media": 2, "baixa": 3}
    return (
        0 if item.usavel_em_producao else 1,
        ordem_prioridade.get(item.prioridade_declarada, 9),
        -len(item.capacidades),
        item.id,
    )


def menor_conjunto(capacidades=None, somente_auditadas: bool = False) -> dict:
    """Cobertura gulosa: a cada passo pega quem cobre mais buracos restantes.

    Com somente_auditadas=True o resultado e a stack que da para adotar hoje;
    sem isso, e a proposta a validar.
    """
    alvo = set(capacidades or COBERTURA_MINIMA)
    disponiveis = [x for x in catalog.todas() if x.auditoria != "DESCARTADO"]
    if somente_auditadas:
        disponiveis = [x for x in disponiveis if x.usavel_em_producao]

    escolhidas, restante = [], set(alvo)
    while restante:
        candidatas = [x for x in disponiveis if set(x.capacidades) & restante]
        if not candidatas:
            break
        # A prioridade declarada pesa ANTES da cobertura bruta: o documento
        # manda priorizar WanGP, entao uma ferramenta media que cobre quatro
        # capacidades nao pode passar na frente de uma prioridade muito-alta.
        melhor = min(
            candidatas,
            key=lambda x: (*_peso(x), -len(set(x.capacidades) & restante)),
        )
        escolhidas.append(melhor)
        restante -= set(melhor.capacidades)
        disponiveis.remove(melhor)

    pendentes = sorted(
        {
            campo
            for item in escolhidas
            for campo in item.pendencias
            if not item.usavel_em_producao
        }
    )
    return {
        "capacidades_alvo": sorted(alvo),
        "ferramentas": [x.id for x in escolhidas],
        "cobertura": {
            capacidade: next(
                (x.id for x in escolhidas if capacidade in x.capacidades), None
            )
            for capacidade in sorted(alvo)
        },
        "sem_cobertura": sorted(restante),
        "nao_auditadas": [x.id for x in escolhidas if not x.usavel_em_producao],
        "campos_pendentes": pendentes,
        "pronta_para_producao": bool(escolhidas)
        and not restante
        and all(x.usavel_em_producao for x in escolhidas),
    }


def resumo_auditoria() -> dict:
    itens = catalog.todas()
    por_nivel = {}
    for item in itens:
        por_nivel.setdefault(item.auditoria, []).append(item.id)
    return {
        "total": len(itens),
        "por_nivel": {k: sorted(v) for k, v in sorted(por_nivel.items())},
        "prontas_para_producao": sorted(x.id for x in itens if x.usavel_em_producao),
        "capacidades_sem_ferramenta_auditada": sorted(
            capacidade
            for capacidade in COBERTURA_MINIMA
            if not any(
                capacidade in x.capacidades and x.usavel_em_producao for x in itens
            )
        ),
    }
