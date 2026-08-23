"""Projetos: o lote de trabalho, com pastas proprias.

Cada projeto tem sua arvore no disco, para o operador retomar depois sem
misturar campanhas:

    <raiz>/<projeto>/
        downloads/   o que veio da fonte, intocado
        editados/    a saida do editor
        exports/     ZIP e material pronto para entregar

Regra do documento que virou codigo: os originais nunca sao sobrescritos. O
editor sempre escreve em `editados/`, nunca por cima de `downloads/`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .store import MassaError, agora, atualizar, auditar, inserir, listar, obter


SUBPASTAS = ("downloads", "editados", "exports")
NOME_INVALIDO = re.compile(r"[^\w\s.-]", re.UNICODE)


def raiz() -> Path:
    padrao = Path(__file__).resolve().parents[1] / "data" / "projetos"
    return Path(os.getenv("MASS_PROJECTS_DIR", padrao))


def _pasta_segura(nome: str) -> str:
    limpo = NOME_INVALIDO.sub("", nome).strip().replace(" ", "-").lower()
    if not limpo:
        raise MassaError("Nome de projeto invalido")
    return limpo[:60]


def criar(nome: str, template_id: str | None = None, notas: str = "") -> dict:
    if not (nome or "").strip():
        raise MassaError("Projeto precisa de nome")
    pasta = raiz() / _pasta_segura(nome)
    for sub in SUBPASTAS:
        (pasta / sub).mkdir(parents=True, exist_ok=True)

    stamp = agora()
    projeto = inserir("mass_projetos", {
        "nome": nome.strip(),
        "pasta": str(pasta),
        "template_id": template_id,
        "status": "aberto",
        "notas": notas,
        "created_at": stamp,
        "updated_at": stamp,
    })
    auditar("projeto.criado", "projeto", projeto["id"], {"pasta": str(pasta)})
    return projeto


def exigir(projeto_id: str) -> dict:
    projeto = obter("mass_projetos", projeto_id)
    if not projeto:
        raise MassaError("Projeto inexistente")
    return projeto


def pasta_de(projeto: dict, sub: str) -> Path:
    if sub not in SUBPASTAS:
        raise MassaError(f"Subpasta invalida: {sub}. Use {list(SUBPASTAS)}")
    destino = Path(projeto["pasta"]) / sub
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def fechar(projeto_id: str) -> dict:
    exigir(projeto_id)
    return atualizar("mass_projetos", projeto_id,
                     {"status": "fechado", "updated_at": agora()})


def abertos() -> list:
    return listar("mass_projetos", 200, "status=?", ("aberto",))


def historico(projeto_id: str) -> dict:
    """Resumo do lote - o que o documento pede na aba Historico."""
    from .store import contar

    projeto = exigir(projeto_id)
    downloads = contar("mass_downloads", "projeto_id=?", (projeto_id,))
    edicoes = contar("mass_edicoes", "projeto_id=?", (projeto_id,))
    publicacoes = contar("mass_publicacoes", "projeto_id=?", (projeto_id,))
    return {
        "projeto": projeto["nome"],
        "pasta": projeto["pasta"],
        "status": projeto["status"],
        "criado_em": projeto["created_at"],
        "downloads": downloads,
        "edicoes": edicoes,
        "publicacoes": publicacoes,
        "totais": {
            "baixados": downloads.get("completed", 0),
            "editados": edicoes.get("completed", 0),
            "publicados": publicacoes.get("completed", 0),
            "falhas": (downloads.get("failed", 0) + edicoes.get("failed", 0)
                       + publicacoes.get("failed", 0)),
        },
    }
