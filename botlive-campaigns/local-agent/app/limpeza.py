"""Faxina do material capturado.

Por que isto existe
-------------------
O worker grava meia hora de live por fonte por hora. Sao ~300 MB por gravacao,
e o material bruto nao serve para nada depois que o corte saiu. Em 15/07/2026 o
cache do BotLive encheu 170 GB e derrubou a VPS inteira - o disco lotado nao
avisa antes, so para tudo de uma vez.

O que sai e o que fica
----------------------
Sai o ARQUIVO bruto (a live baixada). Fica:

  - a linha do material no banco, com status `purged`. Ela e a memoria de
    deduplicacao: sem ela o bot baixaria de novo o mesmo VOD amanha;
  - o corte pronto, que e o produto e ocupa quase nada perto do bruto.

Duas travas, porque uma so nao basta: idade (material velho nao vira corte) e
teto de espaco (uma maratona de 12 horas enche o disco em um dia, mesmo com
tudo "novo").
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import connect, now, update


DIAS_PADRAO = int(os.getenv("CAMPAIGNS_RETENCAO_DIAS", "3"))
TETO_GB_PADRAO = float(os.getenv("CAMPAIGNS_TETO_GB", "60"))


def _materiais_com_arquivo() -> list:
    """Materiais que ainda tem arquivo em disco, do mais velho para o mais novo."""
    with connect() as db:
        linhas = db.execute(
            "SELECT id,campaign_id,local_path,size_bytes,created_at,status "
            "FROM campaign_materials WHERE status!='purged' AND local_path!='' "
            "ORDER BY created_at ASC"
        ).fetchall()
    return [dict(x) for x in linhas]


def _tem_corte(material_id: str) -> bool:
    with connect() as db:
        linha = db.execute(
            "SELECT 1 FROM campaign_candidates WHERE material_id=? LIMIT 1",
            (material_id,)).fetchone()
    return bool(linha)


def _apagar(material: dict, motivo: str) -> int:
    caminho = Path(material["local_path"])
    tamanho = 0
    if caminho.exists():
        tamanho = caminho.stat().st_size
        caminho.unlink()
    update("campaign_materials", material["id"],
           {"status": "purged", "rights_notes": f"arquivo removido: {motivo} ({now()})"})
    return tamanho


def limpar(dias: int | None = None, teto_gb: float | None = None,
           agora=None) -> dict:
    """Roda as duas travas e devolve o que foi liberado."""
    dias = DIAS_PADRAO if dias is None else dias
    teto_gb = TETO_GB_PADRAO if teto_gb is None else teto_gb
    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(days=dias)

    materiais = _materiais_com_arquivo()
    liberados = 0
    apagados = []

    for material in materiais:
        try:
            criado = datetime.fromisoformat(str(material["created_at"]))
        except ValueError:
            continue
        if criado.tzinfo is None:
            criado = criado.replace(tzinfo=timezone.utc)
        if criado < limite:
            liberados += _apagar(material, f"mais de {dias} dia(s)")
            apagados.append(material["id"])

    # Segunda trava: mesmo material novo sai quando o disco aperta. Comeca pelo
    # mais velho, e nunca leva material que ainda nao virou corte - esse ainda
    # tem trabalho pela frente.
    restantes = [m for m in materiais if m["id"] not in apagados]
    total = sum(int(m["size_bytes"] or 0) for m in restantes)
    teto = teto_gb * 1e9
    for material in restantes:
        if total <= teto:
            break
        if not _tem_corte(material["id"]):
            continue
        tamanho = _apagar(material, f"teto de {teto_gb:.0f} GB")
        liberados += tamanho
        total -= int(material["size_bytes"] or tamanho)
        apagados.append(material["id"])

    return {"apagados": len(apagados), "liberado_gb": round(liberados / 1e9, 2),
            "restante_gb": round(total / 1e9, 2)}
