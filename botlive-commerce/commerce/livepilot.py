"""Exportacao de LiveAssetPackage para o Live Pilot.

Contrato do documento:

    LiveAssetPackage
    - product_id
    - images[]
    - videos[]
    - overlays[]
    - talking_points[]
    - CTA[]
    - metadata
    - version

O Live Pilot **apenas consome** este pacote. Este modulo nao importa, nao le
e nao escreve nada em shop-live.db: a extensao segue dona do proprio estado.
O acoplamento e o arquivo/JSON, e mais nada.

Regra de conteudo: talking_points saem **somente** de claims sustentados. Um
ponto de fala que a evidencia nao aguenta nao chega na boca de ninguem ao
vivo.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import creatives, products
from .store import CommerceError, agora, conectar, inserir, listar, obter


VERSAO_CONTRATO = 1
CAMPOS = ("product_id", "images", "videos", "overlays", "talking_points", "cta", "metadata", "version")


def montar(product_id: str) -> dict:
    """Monta o pacote a partir do que ja foi aprovado. Nao gera nada novo."""
    ficha = products.ficha(product_id)
    if not ficha["claims_allowed"]:
        raise CommerceError(
            "Produto sem nenhum claim sustentado: nao ha o que falar ao vivo com seguranca"
        )

    aprovados = creatives.por_produto(product_id, "approved")
    if not aprovados:
        raise CommerceError("Nenhum criativo aprovado para exportar")

    assets = creatives.biblioteca(product_id)
    imagens = [x["path"] for x in assets if x["kind"] == "imagem"]
    videos = [x["path"] for x in assets if x["kind"] == "video"]
    overlays = [x["path"] for x in assets if x["kind"] == "overlay"]

    ctas = sorted({x["cta"].strip() for x in aprovados if x["cta"].strip()})

    return {
        "product_id": product_id,
        "images": imagens,
        "videos": videos,
        "overlays": overlays,
        # So claim sustentado vira ponto de fala.
        "talking_points": ficha["claims_allowed"],
        "cta": ctas,
        "metadata": {
            "platform": ficha["platform"],
            "title": ficha["title"],
            "brand": ficha["brand"],
            "price": ficha["price"],
            "currency": ficha["currency"],
            "confidence": ficha["confidence"],
            "claims_blocked": ficha["claims_blocked"],
            "evidencias": len(ficha["evidencias"]),
            "criativos_aprovados": [x["id"] for x in aprovados],
            "gerado_em": agora(),
            "contrato": VERSAO_CONTRATO,
        },
        "version": VERSAO_CONTRATO,
    }


def _checksum(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def exportar(product_id: str, destino: str | Path | None = None) -> dict:
    """Grava uma versao nova do pacote. Versao anterior nunca e sobrescrita."""
    payload = montar(product_id)
    with conectar() as db:
        linha = db.execute(
            "SELECT MAX(version) AS ultima FROM commerce_packages WHERE product_id=?",
            (product_id,),
        ).fetchone()
    versao = int(linha["ultima"] or 0) + 1
    payload["metadata"]["pacote_versao"] = versao

    registro = inserir(
        "commerce_packages",
        {
            "product_id": product_id,
            "version": versao,
            "payload": json.dumps(payload, ensure_ascii=False),
            "checksum": _checksum(payload),
            "exported_to": "live-pilot",
            "created_at": agora(),
        },
    )

    if destino:
        caminho = Path(destino)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        registro["arquivo"] = str(caminho)

    return {
        "package_id": registro["id"],
        "product_id": product_id,
        "version": versao,
        "checksum": registro["checksum"],
        "talking_points": len(payload["talking_points"]),
        "arquivo": registro.get("arquivo", ""),
    }


def historico(product_id: str) -> list:
    return listar("commerce_packages", 100, where="product_id=?", params=(product_id,))


def carregar(package_id: str) -> dict:
    registro = obter("commerce_packages", package_id)
    if not registro:
        raise CommerceError("Pacote inexistente")
    payload = json.loads(registro["payload"])
    if _checksum(payload) != registro["checksum"]:
        raise CommerceError("Pacote adulterado: checksum nao confere")
    return payload
