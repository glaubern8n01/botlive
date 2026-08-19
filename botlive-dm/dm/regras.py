"""Regras de resposta: qual comentario recebe qual mensagem no direct.

Funciona como o ManyChat: a pessoa comenta uma palavra ("preco", "link",
"quero") e recebe a resposta no direct. A diferenca e que aqui nao ha
mensalidade - a mecanica usada e a Private Reply oficial do Instagram.

Casamento por palavra inteira, sem acento e sem caixa. "linkin park" nao
dispara a regra de "link", e "PREÇO?" dispara a de "preco".
"""

from __future__ import annotations

import json
import re
import unicodedata

from .store import DmError, agora, atualizar, inserir, listar, obter


LIMITE_RESPOSTA = 900  # o direct corta bem antes disso; folga de proposito


def normalizar(texto: str) -> str:
    """minusculo, sem acento, sem pontuacao - dos dois lados da comparacao."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^\w\s]", " ", sem_acento.lower())


def criar(conta: str, nome: str, palavras: list, resposta: str,
          link: str = "", media_id: str = "", prioridade: int = 100) -> dict:
    palavras = [p.strip() for p in (palavras or []) if p.strip()]
    if not palavras:
        raise DmError("A regra precisa de ao menos uma palavra-gatilho")
    if not (resposta or "").strip():
        raise DmError("A regra precisa do texto da resposta")
    if len(resposta) > LIMITE_RESPOSTA:
        raise DmError(f"Resposta longa demais (max {LIMITE_RESPOSTA} caracteres)")
    if link and not link.startswith(("http://", "https://")):
        raise DmError("Link precisa comecar com http:// ou https://")

    stamp = agora()
    return inserir("dm_regras", {
        "nome": nome.strip(),
        "conta": conta.strip(),
        "palavras": json.dumps([normalizar(p).strip() for p in palavras], ensure_ascii=False),
        "resposta": resposta.strip(),
        "link": link.strip(),
        "media_id": media_id.strip(),
        # Nasce DESLIGADA: ninguem manda mensagem por engano no dia do cadastro.
        "ativa": 0,
        "prioridade": prioridade,
        "created_at": stamp,
        "updated_at": stamp,
    })


def ativar(regra_id: str, ativa: bool = True) -> dict:
    if not obter("dm_regras", regra_id):
        raise DmError("Regra inexistente")
    return atualizar("dm_regras", regra_id,
                     {"ativa": 1 if ativa else 0, "updated_at": agora()})


def ativas(conta: str) -> list:
    return sorted(
        listar("dm_regras", 200, "conta=? AND ativa=1", (conta,)),
        key=lambda r: r["prioridade"],
    )


def casar(texto: str, conta: str, media_id: str = "") -> dict | None:
    """Primeira regra que casa, respeitando prioridade.

    Regra presa a um media_id so vale naquele post; regra sem media_id vale
    para a conta inteira.
    """
    alvo = f" {normalizar(texto)} "
    for regra in ativas(conta):
        if regra["media_id"] and media_id and regra["media_id"] != media_id:
            continue
        for palavra in json.loads(regra["palavras"] or "[]"):
            if not palavra:
                continue
            # palavra inteira: evita "link" casar dentro de "linkin"
            if re.search(rf"(?<!\w){re.escape(palavra)}(?!\w)", alvo):
                return regra
    return None


def montar_resposta(regra: dict) -> str:
    texto = regra["resposta"]
    if regra["link"] and regra["link"] not in texto:
        texto = f"{texto}\n\n{regra['link']}"
    return texto[:LIMITE_RESPOSTA]
