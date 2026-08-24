"""Traz as campanhas e as fontes da VPS para o banco local do PC.

Por que isto existe
-------------------
Render de campanha e trabalho pesado e em lote. Na VPS ele briga com o vigia e
com o produtor do Kwai - que sao o que ja da dinheiro - e em 23/08 a Hostinger
estrangulou a maquina (95% de steal), matando um render depois de 37 minutos de
gravacao e transcricao ja pagos.

O desenho certo passou a ser: a VPS guarda o cadastro (campanha, regra, fonte,
prazo) e o PC faz o peso (baixar, transcrever, cortar, renderizar). Para isso o
PC precisa das MESMAS campanhas, com os MESMOS ids - senao os dois lados falam
de coisas diferentes.

O que NAO vem junto
-------------------
Material, candidato, publicacao e metrica ficam de cada lado. Sincronizar isso
seria replicacao de verdade, com conflito e ordem de escrita; aqui o cadastro e
so-leitura para o PC e o resto e local. Se o cadastro mudar na VPS, roda de
novo e o PC atualiza.
"""

from __future__ import annotations

import json

from .store import connect, get, insert, now, rows, update


TABELAS = ("campaign_campaigns", "campaign_sources")


def exportar() -> dict:
    """Tira uma foto do cadastro. Roda no lado que manda (a VPS)."""
    return {
        "gerado_em": now(),
        "campaign_campaigns": rows("campaign_campaigns", 200, 0),
        "campaign_sources": rows("campaign_sources", 200, 0),
    }


def _colunas(db, tabela: str) -> set:
    return {x["name"] for x in db.execute(f"PRAGMA table_info({tabela})")}


def importar(dados: dict) -> dict:
    """Grava o cadastro no banco local, preservando os ids.

    Campanha que sumiu da VPS nao e apagada aqui: pode haver corte local
    pendurado nela, e apagar levaria o material junto. Ela so para de ser
    atualizada.
    """
    resumo = {"criados": 0, "atualizados": 0, "ignorados": 0}
    with connect() as db:
        for tabela in TABELAS:
            conhecidas = _colunas(db, tabela)
            for linha in dados.get(tabela, []):
                # Coluna que existe la e nao existe aqui (ou o contrario) nao
                # pode derrubar a sincronia inteira.
                payload = {k: v for k, v in linha.items() if k in conhecidas}
                if not payload.get("id"):
                    resumo["ignorados"] += 1
                    continue
                existe = db.execute(f"SELECT 1 FROM {tabela} WHERE id=?",
                                    (payload["id"],)).fetchone()
                if existe:
                    campos = {k: v for k, v in payload.items() if k != "id"}
                    setters = ",".join(f"{k}=?" for k in campos)
                    db.execute(f"UPDATE {tabela} SET {setters} WHERE id=?",
                               (*campos.values(), payload["id"]))
                    resumo["atualizados"] += 1
                else:
                    cols = ",".join(payload)
                    marcas = ",".join("?" for _ in payload)
                    db.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marcas})",
                               tuple(payload.values()))
                    resumo["criados"] += 1
    return resumo


def de_arquivo(caminho) -> dict:
    with open(caminho, "r", encoding="utf-8") as stream:
        return importar(json.load(stream))
