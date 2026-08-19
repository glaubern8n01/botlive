"""Criativos comerciais e o QA que os libera.

Os 12 tipos vem do documento. Cada criativo guarda produto, objetivo, gancho,
roteiro, claims usados, assets, provider, seed/config, resultado e status.

O QA e a trava principal: um criativo nao e aprovado se o roteiro afirmar algo
que nao esta sustentado por evidencia, ou se repetir um claim bloqueado. Vale
para o texto inteiro, nao so para a lista de claims marcada.
"""

from __future__ import annotations

import hashlib
import json

from . import products
from .store import CommerceError, agora, atualizar, conectar, inserir, listar, obter


TIPOS = (
    "UGC_SELFIE",
    "PRODUCT_HERO",
    "FEATURE_WALKTHROUGH",
    "PREMIUM_REVEAL",
    "LOOKBOOK",
    "DEMO",
    "COMPARISON",
    "PROBLEM_SOLUTION",
    "HOOK_CTA",
    "STATIC_IMAGE",
    "THUMBNAIL",
    "LIVE_SCENE",
)

ESTADOS = ("draft", "generated", "qa_failed", "approved", "rejected", "queued")


def _json(valor) -> str:
    return json.dumps(valor if valor is not None else [], ensure_ascii=False)


def chave(product_id: str, kind: str, hook: str, script: str) -> str:
    bruto = "|".join([product_id, kind, hook, script])
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def criar(
    product_id: str,
    kind: str,
    objective: str = "",
    hook: str = "",
    script: str = "",
    cta: str = "",
    claim_ids=None,
    asset_ids=None,
    provider: str = "",
    seed: str = "",
    config=None,
) -> dict:
    produto = obter("commerce_products", product_id)
    if not produto:
        raise CommerceError("Produto inexistente")
    if kind not in TIPOS:
        raise CommerceError(f"Tipo de criativo invalido: {kind}. Use {list(TIPOS)}")

    claim_ids = list(claim_ids or [])
    do_produto = {x["id"] for x in products.claims(product_id)}
    forasteiros = [x for x in claim_ids if x not in do_produto]
    if forasteiros:
        raise CommerceError(f"Claim nao pertence ao produto: {forasteiros}")

    idem = chave(product_id, kind, hook, script)
    with conectar() as db:
        existente = db.execute(
            "SELECT * FROM commerce_creatives WHERE idempotency_key=?", (idem,)
        ).fetchone()
    if existente:
        return dict(existente)

    stamp = agora()
    registro = inserir(
        "commerce_creatives",
        {
            "product_id": product_id,
            "kind": kind,
            "objective": objective,
            "hook": hook,
            "script": script,
            "cta": cta,
            "claim_ids": _json(claim_ids),
            "asset_ids": _json(list(asset_ids or [])),
            "provider": provider,
            "seed": str(seed),
            "config": json.dumps(config or {}, ensure_ascii=False),
            "status": "draft",
            "qa": "{}",
            "idempotency_key": idem,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    return obter("commerce_creatives", registro["id"])


def rodar_qa(creative_id: str) -> dict:
    """Confere claims, evidencia, assets e CTA. Nao aprova nada sozinho."""
    criativo = obter("commerce_creatives", creative_id)
    if not criativo:
        raise CommerceError("Criativo inexistente")
    produto = products.ficha(criativo["product_id"])
    roteiro = f"{criativo['hook']} {criativo['script']} {criativo['cta']}".lower()

    bloqueados_no_texto = [x for x in produto["claims_blocked"] if x.lower() in roteiro]
    propostos_no_texto = [x for x in produto["claims_propostos"] if x.lower() in roteiro]

    claim_ids = json.loads(criativo["claim_ids"] or "[]")
    marcados = [obter("commerce_claims", x) for x in claim_ids]
    marcados_sem_suporte = [x["text"] for x in marcados if x and x["state"] != "supported"]

    problemas = []
    if bloqueados_no_texto:
        problemas.append({"regra": "claim_bloqueado", "itens": bloqueados_no_texto})
    if propostos_no_texto:
        problemas.append({"regra": "claim_sem_evidencia", "itens": propostos_no_texto})
    if marcados_sem_suporte:
        problemas.append({"regra": "claim_marcado_sem_suporte", "itens": marcados_sem_suporte})
    if not json.loads(criativo["asset_ids"] or "[]"):
        problemas.append({"regra": "sem_asset", "itens": []})
    if not criativo["cta"].strip():
        problemas.append({"regra": "sem_cta", "itens": []})

    resultado = {
        "ok": not problemas,
        "problemas": problemas,
        "claims_sustentados": produto["claims_allowed"],
        "confidence": produto["confidence"],
        "verificado_em": agora(),
    }
    novo_status = criativo["status"] if resultado["ok"] else "qa_failed"
    atualizar(
        "commerce_creatives",
        creative_id,
        {
            "qa": json.dumps(resultado, ensure_ascii=False),
            "status": novo_status,
            "updated_at": agora(),
        },
    )
    return resultado


def aprovar(creative_id: str) -> dict:
    """Aprovacao humana, e so depois de QA limpo."""
    criativo = obter("commerce_creatives", creative_id)
    if not criativo:
        raise CommerceError("Criativo inexistente")
    resultado = rodar_qa(creative_id)
    if not resultado["ok"]:
        raise CommerceError(
            "QA reprovou o criativo: " + ", ".join(x["regra"] for x in resultado["problemas"])
        )
    return atualizar(
        "commerce_creatives", creative_id, {"status": "approved", "updated_at": agora()}
    )


def rejeitar(creative_id: str, motivo: str = "") -> dict:
    if not obter("commerce_creatives", creative_id):
        raise CommerceError("Criativo inexistente")
    return atualizar(
        "commerce_creatives",
        creative_id,
        {"status": "rejected", "objective": motivo or "", "updated_at": agora()},
    )


def registrar_asset(
    product_id: str, kind: str, path: str, rights: str, source: str = "", provider: str = ""
) -> dict:
    """Asset sem direito declarado nao entra na biblioteca."""
    if not obter("commerce_products", product_id):
        raise CommerceError("Produto inexistente")
    if not (rights or "").strip():
        raise CommerceError("Asset precisa de direito de uso declarado")
    if kind not in {"imagem", "video", "audio", "overlay"}:
        raise CommerceError(f"Tipo de asset invalido: {kind}")
    return inserir(
        "commerce_assets",
        {
            "product_id": product_id,
            "kind": kind,
            "path": path,
            "rights": rights.strip(),
            "source": source,
            "provider": provider,
            "metadata": "{}",
            "created_at": agora(),
        },
    )


def biblioteca(product_id: str | None = None) -> list:
    if product_id:
        return listar("commerce_assets", 200, where="product_id=?", params=(product_id,))
    return listar("commerce_assets", 200)


def por_produto(product_id: str, status: str | None = None) -> list:
    if status:
        return listar(
            "commerce_creatives", 200, where="product_id=? AND status=?", params=(product_id, status)
        )
    return listar("commerce_creatives", 200, where="product_id=?", params=(product_id,))
