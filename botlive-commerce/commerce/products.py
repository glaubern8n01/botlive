"""Produtos, evidencias e claims.

Duas regras do documento viram codigo aqui:

  "produto inserido manualmente nao recebe automaticamente confidence=1"
  "nenhum claim comercial sem suporte documentado"

Confianca nao e digitada: ela e derivada da evidencia registrada. Produto so
cadastrado a mao fica em confianca baixa ate alguem anexar evidencia com
origem, e claim sem evidencia ligada nunca sai de 'proposed'.
"""

from __future__ import annotations

import json

from .store import CommerceError, agora, atualizar, conectar, inserir, listar, obter


PLATAFORMAS = ("tiktok-shop", "shopee")
ORIGENS = ("manual", "catalogo-oficial", "api-afiliado", "importado")
TIPOS_EVIDENCIA = ("especificacao", "pagina-oficial", "laudo", "review", "teste-proprio")
CONFIABILIDADE = {"baixa": 0.2, "media": 0.5, "alta": 0.8}

# Teto de confianca por origem. Manual nunca chega perto de 1 so por ser
# digitado: o que sobe a confianca e a evidencia anexada depois.
TETO_POR_ORIGEM = {
    "manual": 0.3,
    "importado": 0.5,
    "catalogo-oficial": 0.9,
    "api-afiliado": 0.9,
}

CONFIANCA_INICIAL = 0.1
ESTADOS_CLAIM = ("proposed", "supported", "blocked")


def _json(valor) -> str:
    return json.dumps(valor if valor is not None else [], ensure_ascii=False)


def criar_produto(
    platform: str,
    title: str,
    source: str = "manual",
    brand: str = "",
    affiliate_url: str = "",
    price: float = 0.0,
    features=None,
    target_audience: str = "",
    notes: str = "",
) -> dict:
    if platform not in PLATAFORMAS:
        raise CommerceError(f"Plataforma invalida: {platform}. Use {list(PLATAFORMAS)}")
    if source not in ORIGENS:
        raise CommerceError(f"Origem invalida: {source}. Use {list(ORIGENS)}")
    if not (title or "").strip():
        raise CommerceError("Titulo do produto obrigatorio")
    if price < 0:
        raise CommerceError("Preco negativo")

    stamp = agora()
    return inserir(
        "commerce_products",
        {
            "platform": platform,
            "title": title.strip()[:200],
            "brand": brand,
            "affiliate_url": affiliate_url,
            "price": float(price),
            "features": _json(features),
            "target_audience": target_audience,
            "source": source,
            # Sempre comeca no piso, independente da origem.
            "confidence": CONFIANCA_INICIAL,
            "status": "draft",
            "notes": notes,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )


def evidencias(product_id: str) -> list:
    return listar("commerce_evidence", 200, where="product_id=?", params=(product_id,))


def registrar_evidencia(
    product_id: str,
    kind: str,
    statement: str,
    source_label: str,
    source_url: str = "",
    reliability: str = "baixa",
    captured_at: str | None = None,
) -> dict:
    """Evidencia sem origem declarada nao e evidencia."""
    produto = obter("commerce_products", product_id)
    if not produto:
        raise CommerceError("Produto inexistente")
    if kind not in TIPOS_EVIDENCIA:
        raise CommerceError(f"Tipo de evidencia invalido: {kind}. Use {list(TIPOS_EVIDENCIA)}")
    if not (statement or "").strip():
        raise CommerceError("Descreva o que a evidencia sustenta")
    if not (source_label or "").strip():
        raise CommerceError("Evidencia precisa de origem declarada")
    if reliability not in CONFIABILIDADE:
        raise CommerceError(f"Confiabilidade invalida: {reliability}")

    registro = inserir(
        "commerce_evidence",
        {
            "product_id": product_id,
            "kind": kind,
            "statement": statement.strip(),
            "source_url": source_url,
            "source_label": source_label.strip(),
            "captured_at": captured_at or agora(),
            "reliability": reliability,
            "created_at": agora(),
        },
    )
    recalcular_confianca(product_id)
    return registro


def recalcular_confianca(product_id: str) -> float:
    """Confianca = teto da origem aplicado sobre o peso da evidencia reunida.

    Sem evidencia, fica no piso. Com evidencia, sobe ate o teto da origem -
    nunca alem dele, e nunca ate 1.0 por cadastro manual.
    """
    produto = obter("commerce_products", product_id)
    if not produto:
        raise CommerceError("Produto inexistente")
    teto = TETO_POR_ORIGEM[produto["source"]]
    itens = evidencias(product_id)
    if not itens:
        valor = CONFIANCA_INICIAL
    else:
        peso = sum(CONFIABILIDADE[x["reliability"]] for x in itens)
        valor = min(teto, round(CONFIANCA_INICIAL + peso / (peso + 1) * teto, 3))
    atualizar("commerce_products", product_id, {"confidence": valor, "updated_at": agora()})
    return valor


def propor_claim(product_id: str, text: str) -> dict:
    produto = obter("commerce_products", product_id)
    if not produto:
        raise CommerceError("Produto inexistente")
    if not (text or "").strip():
        raise CommerceError("Claim vazio")
    with conectar() as db:
        existente = db.execute(
            "SELECT * FROM commerce_claims WHERE product_id=? AND text=?",
            (product_id, text.strip()),
        ).fetchone()
    if existente:
        return dict(existente)
    stamp = agora()
    return inserir(
        "commerce_claims",
        {
            "product_id": product_id,
            "text": text.strip(),
            "state": "proposed",
            "evidence_ids": "[]",
            "created_at": stamp,
            "updated_at": stamp,
        },
    )


def sustentar_claim(claim_id: str, evidence_ids: list) -> dict:
    """Liga evidencia ao claim. Sem evidencia valida, o claim nao e sustentado."""
    claim = obter("commerce_claims", claim_id)
    if not claim:
        raise CommerceError("Claim inexistente")
    if claim["state"] == "blocked":
        raise CommerceError("Claim bloqueado nao pode ser sustentado")
    if not evidence_ids:
        raise CommerceError("Nenhum claim comercial sem suporte documentado")

    validas = {x["id"] for x in evidencias(claim["product_id"])}
    invalidas = [x for x in evidence_ids if x not in validas]
    if invalidas:
        raise CommerceError(f"Evidencia nao pertence ao produto: {invalidas}")

    return atualizar(
        "commerce_claims",
        claim_id,
        {
            "state": "supported",
            "evidence_ids": _json(sorted(set(evidence_ids))),
            "updated_at": agora(),
        },
    )


def bloquear_claim(claim_id: str, motivo: str) -> dict:
    if not (motivo or "").strip():
        raise CommerceError("Bloqueio exige motivo")
    if not obter("commerce_claims", claim_id):
        raise CommerceError("Claim inexistente")
    return atualizar(
        "commerce_claims",
        claim_id,
        {"state": "blocked", "blocked_reason": motivo.strip(), "updated_at": agora()},
    )


def claims(product_id: str, state: str | None = None) -> list:
    if state and state not in ESTADOS_CLAIM:
        raise CommerceError(f"Estado de claim invalido: {state}")
    if state:
        return listar(
            "commerce_claims", 200, where="product_id=? AND state=?", params=(product_id, state)
        )
    return listar("commerce_claims", 200, where="product_id=?", params=(product_id,))


def claims_permitidos(product_id: str) -> list:
    return [x["text"] for x in claims(product_id, "supported")]


def claims_bloqueados(product_id: str) -> list:
    return [x["text"] for x in claims(product_id, "blocked")]


def ficha(product_id: str) -> dict:
    """Visao completa do produto, com proveniencia junto - nunca separada."""
    produto = obter("commerce_products", product_id)
    if not produto:
        raise CommerceError("Produto inexistente")
    return {
        **produto,
        "evidencias": evidencias(product_id),
        "claims_allowed": claims_permitidos(product_id),
        "claims_blocked": claims_bloqueados(product_id),
        "claims_propostos": [x["text"] for x in claims(product_id, "proposed")],
        "confidence_teto": TETO_POR_ORIGEM[produto["source"]],
    }
