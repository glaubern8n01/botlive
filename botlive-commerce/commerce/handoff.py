"""Entrega do LiveAssetPackage ao Live Pilot, pela API que ele ja expoe.

O documento manda manter a extensao isolada e so altera-la com necessidade
clara. Entao este modulo NAO importa codigo do Live Pilot, NAO escreve em
shop-live.db e NAO exige nenhuma mudanca na extensao: ele traduz o pacote
para as rotas publicas que o agente do Shop LIVE ja tem hoje.

Mapeamento (conferido em botlive-shop/apps/local-agent/app/schemas.py):

    talking_points          -> ProductIn.approved_answers
    metadata.claims_blocked -> ProductIn.prohibited_claims
    metadata.title/price    -> ProductIn.name/price
    cta[]                   -> ScriptBlockIn(kind="cta")
    videos[]                -> MediaAssetIn(kind="video")

O encaixe de claims e literal: o Live Pilot ja separa resposta aprovada de
alegacao proibida, e o Commerce Studio ja separa claim sustentado de claim
bloqueado. As duas listas se encontram sem adaptacao.

O que NAO cabe hoje esta em LIMITACOES: images[] e overlays[] nao tem lugar
no contrato atual do Live Pilot (MediaAssetIn aceita apenas video|audio).
Isso e reportado, nunca descartado em silencio.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import livepilot
from .store import CommerceError, agora, obter


# Partes do pacote que o contrato atual do Live Pilot nao recebe.
LIMITACOES = {
    "images": (
        "MediaAssetIn do Live Pilot aceita apenas kind video|audio. "
        "Receber imagem exigiria ampliar o Literal em schemas.py e o storage."
    ),
    "overlays": (
        "O Live Pilot nao tem entidade de overlay. Receber overlays exigiria "
        "uma tabela/rota nova na extensao."
    ),
}


def base_url() -> str:
    return os.getenv("SHOP_LIVE_API_URL", "http://127.0.0.1:8765").rstrip("/")


def token() -> str:
    return os.getenv("SHOP_LIVE_LOCAL_TOKEN", "")


def dry_run_padrao() -> bool:
    return os.getenv("COMMERCE_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "sim"}


def traduzir(payload: dict) -> dict:
    """Converte o pacote em chamadas HTTP. Nao envia nada."""
    metadata = payload.get("metadata", {})
    chamadas = [
        {
            "metodo": "POST",
            "rota": "/shop-live/v1/products",
            "corpo": {
                "name": metadata.get("title", "")[:160],
                "category": metadata.get("platform", ""),
                "price": float(metadata.get("price") or 0),
                # Aqui esta o encaixe: so claim sustentado vira resposta aprovada.
                "approved_answers": list(payload.get("talking_points", [])),
                "prohibited_claims": list(metadata.get("claims_blocked", [])),
                "tags": ["commerce-studio", f"pacote-v{payload.get('version')}"],
                "notes": (
                    f"Origem: Commerce Studio. Confianca {metadata.get('confidence')} "
                    f"com {metadata.get('evidencias')} evidencia(s). "
                    f"Produto {payload.get('product_id')}."
                ),
                "active": True,
            },
            "depende_de": None,
        }
    ]

    for posicao, cta in enumerate(payload.get("cta", [])):
        chamadas.append(
            {
                "metodo": "POST",
                "rota": "/shop-live/v1/scripts",
                "corpo": {
                    "product_id": "<id do produto criado>",
                    "kind": "cta",
                    "position": posicao,
                    "duration_seconds": 30,
                    "text": cta,
                    "title": "CTA do Commerce Studio",
                },
                "depende_de": "produto",
            }
        )

    for video in payload.get("videos", []):
        chamadas.append(
            {
                "metodo": "POST",
                "rota": "/shop-live/v1/media",
                "corpo": {
                    "product_id": "<id do produto criado>",
                    "kind": "video",
                    "name": os.path.basename(video)[:160],
                    "local_path": video,
                    "authorized": True,
                    "authorization_source": "Commerce Studio - direitos declarados no asset",
                    "tags": ["commerce-studio"],
                    "notes": "",
                },
                "depende_de": "produto",
            }
        )

    nao_entregue = {
        chave: {"quantidade": len(payload.get(chave, [])), "motivo": motivo}
        for chave, motivo in LIMITACOES.items()
        if payload.get(chave)
    }

    return {
        "product_id": payload.get("product_id"),
        "version": payload.get("version"),
        "chamadas": chamadas,
        "nao_entregue": nao_entregue,
        "extensao_precisa_mudar": bool(nao_entregue),
    }


def _post(rota: str, corpo: dict) -> dict:
    requisicao = urllib.request.Request(
        base_url() + rota,
        data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Shop-Live-Token": token()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=20) as resposta:
            return json.loads(resposta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:300]
        raise CommerceError(f"Live Pilot recusou {rota}: {erro.code} {detalhe}") from erro
    except urllib.error.URLError as erro:
        raise CommerceError(f"Live Pilot indisponivel em {base_url()}: {erro.reason}") from erro


def entregar(package_id: str, dry_run: bool | None = None) -> dict:
    """Traduz e, fora do dry-run, envia. Dry-run nunca faz requisicao."""
    registro = obter("commerce_packages", package_id)
    if not registro:
        raise CommerceError("Pacote inexistente")
    payload = livepilot.carregar(package_id)  # confere checksum
    plano = traduzir(payload)

    seco = dry_run_padrao() if dry_run is None else dry_run
    if seco:
        return {
            **plano,
            "dry_run": True,
            "enviado": False,
            "chamadas_previstas": len(plano["chamadas"]),
            "verificado_em": agora(),
        }

    if not token():
        raise CommerceError("SHOP_LIVE_LOCAL_TOKEN ausente: o Live Pilot recusaria a entrega")

    produto = _post(plano["chamadas"][0]["rota"], plano["chamadas"][0]["corpo"])
    novo_id = produto.get("id")
    if not novo_id:
        raise CommerceError("Live Pilot nao devolveu o id do produto")

    criados = {"produto": novo_id, "scripts": [], "media": []}
    for chamada in plano["chamadas"][1:]:
        corpo = {**chamada["corpo"], "product_id": novo_id}
        resposta = _post(chamada["rota"], corpo)
        destino = "scripts" if chamada["rota"].endswith("/scripts") else "media"
        criados[destino].append(resposta.get("id"))

    return {
        **plano,
        "dry_run": False,
        "enviado": True,
        "criados": criados,
        "verificado_em": agora(),
    }


def relatorio_de_compatibilidade() -> dict:
    """O que o contrato atual cobre e o que exigiria mexer na extensao."""
    return {
        "extensao_alterada": False,
        "integracao": "HTTP nas rotas publicas do Live Pilot",
        "cobre": {
            "talking_points": "ProductIn.approved_answers",
            "claims_blocked": "ProductIn.prohibited_claims",
            "cta": "ScriptBlockIn(kind='cta')",
            "videos": "MediaAssetIn(kind='video')",
            "metadata": "ProductIn.name/category/price/notes",
        },
        "nao_cobre": LIMITACOES,
        "mudanca_necessaria_na_extensao": [
            "schemas.py: MediaAssetIn.kind aceitar 'image' para receber images[]",
            "modelo/rota nova para overlays[], que hoje nao existe no Live Pilot",
        ],
    }
