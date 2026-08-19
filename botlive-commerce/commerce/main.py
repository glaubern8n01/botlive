"""API local do Commerce Studio.

Desligada por padrao (COMMERCE_ENABLED=false). Ligada, ela nao publica: o que
sai daqui e LiveAssetPackage para o Live Pilot e PublishJob em draft para o
VexPublish.
"""

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import bridge, creatives, handoff, livepilot, products
from .store import CommerceError, auditar, listar, migrar, obter


PAPEIS = {
    "admin": {"*"},
    "operator": {"read", "write", "qa", "queue"},
    "reviewer": {"read", "qa", "approve"},
}


def modulo_ligado() -> bool:
    return os.getenv("COMMERCE_ENABLED", "false").strip().lower() == "true"


def exigir(acao: str):
    def dependencia(x_commerce_token: str | None = Header(default=None)):
        if not modulo_ligado():
            raise HTTPException(404, "Modulo desativado")
        tokens = {
            "admin": os.getenv("COMMERCE_ADMIN_TOKEN", ""),
            "operator": os.getenv("COMMERCE_OPERATOR_TOKEN", ""),
            "reviewer": os.getenv("COMMERCE_REVIEWER_TOKEN", ""),
        }
        for papel, token in tokens.items():
            if token and x_commerce_token and hmac.compare_digest(token, x_commerce_token):
                if "*" in PAPEIS[papel] or acao in PAPEIS[papel]:
                    return {"actor": papel, "role": papel}
                raise HTTPException(403, "Permissao insuficiente")
        raise HTTPException(401, "Token invalido")

    return dependencia


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrar()
    yield


app = FastAPI(title="BotLive Commerce Studio", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        x.strip()
        for x in os.getenv(
            "COMMERCE_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if x.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Commerce-Token"],
)


class ProductIn(BaseModel):
    platform: str
    title: str = Field(min_length=2, max_length=200)
    source: str = "manual"
    brand: str = ""
    affiliate_url: str = ""
    price: float = Field(0, ge=0)
    features: list[str] = []
    target_audience: str = ""
    notes: str = ""


class EvidenceIn(BaseModel):
    kind: str
    statement: str = Field(min_length=3)
    source_label: str = Field(min_length=2)
    source_url: str = ""
    reliability: str = "baixa"


class ClaimIn(BaseModel):
    text: str = Field(min_length=2)


class SupportIn(BaseModel):
    evidence_ids: list[str] = []


class BlockIn(BaseModel):
    reason: str = Field(min_length=3)


class CreativeIn(BaseModel):
    product_id: str
    kind: str
    objective: str = ""
    hook: str = ""
    script: str = ""
    cta: str = ""
    claim_ids: list[str] = []
    asset_ids: list[str] = []
    provider: str = ""
    seed: str = ""
    config: dict = {}


class AssetIn(BaseModel):
    product_id: str
    kind: str
    path: str
    rights: str = Field(min_length=2)
    source: str = ""
    provider: str = ""


class QueueIn(BaseModel):
    channel_id: str
    platform: str | None = None


def _erro(exc: CommerceError) -> HTTPException:
    return HTTPException(422, str(exc))


@app.get("/commerce/v1/health")
def health():
    estado = bridge.flags()
    return {
        "ok": True,
        **estado,
        "publica_direto": False,
        "live_pilot_alterado": False,
        "saidas": ["LiveAssetPackage", "PublishJob em draft"],
        "contrato_live_pilot": livepilot.VERSAO_CONTRATO,
    }


@app.get("/commerce/v1/products", dependencies=[Depends(exigir("read"))])
def listar_produtos(platform: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if platform:
        return {"items": listar("commerce_products", limit, where="platform=?", params=(platform,))}
    return {"items": listar("commerce_products", limit)}


@app.post("/commerce/v1/products", status_code=201)
def criar_produto(value: ProductIn, user=Depends(exigir("write"))):
    try:
        produto = products.criar_produto(**value.model_dump())
    except CommerceError as exc:
        raise _erro(exc)
    auditar("product.created", "product", produto["id"], actor=user["actor"], role=user["role"])
    return produto


@app.get("/commerce/v1/products/{item_id}", dependencies=[Depends(exigir("read"))])
def ficha_produto(item_id: str):
    try:
        return products.ficha(item_id)
    except CommerceError as exc:
        raise HTTPException(404, str(exc))


@app.post("/commerce/v1/products/{item_id}/evidence", status_code=201)
def registrar_evidencia(item_id: str, value: EvidenceIn, user=Depends(exigir("write"))):
    try:
        registro = products.registrar_evidencia(item_id, **value.model_dump())
    except CommerceError as exc:
        raise _erro(exc)
    auditar("evidence.registered", "product", item_id, actor=user["actor"], role=user["role"])
    return registro


@app.post("/commerce/v1/products/{item_id}/claims", status_code=201)
def propor_claim(item_id: str, value: ClaimIn, user=Depends(exigir("write"))):
    try:
        return products.propor_claim(item_id, value.text)
    except CommerceError as exc:
        raise _erro(exc)


@app.post("/commerce/v1/claims/{claim_id}/support")
def sustentar_claim(claim_id: str, value: SupportIn, user=Depends(exigir("approve"))):
    try:
        claim = products.sustentar_claim(claim_id, value.evidence_ids)
    except CommerceError as exc:
        auditar("claim.support_refused", "claim", claim_id, {"reason": str(exc)},
                result="blocked", actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("claim.supported", "claim", claim_id, actor=user["actor"], role=user["role"])
    return claim


@app.post("/commerce/v1/claims/{claim_id}/block")
def bloquear_claim(claim_id: str, value: BlockIn, user=Depends(exigir("approve"))):
    try:
        return products.bloquear_claim(claim_id, value.reason)
    except CommerceError as exc:
        raise _erro(exc)


@app.get("/commerce/v1/assets", dependencies=[Depends(exigir("read"))])
def listar_assets(product_id: str | None = None):
    return {"items": creatives.biblioteca(product_id)}


@app.post("/commerce/v1/assets", status_code=201)
def registrar_asset(value: AssetIn, user=Depends(exigir("write"))):
    try:
        return creatives.registrar_asset(**value.model_dump())
    except CommerceError as exc:
        raise _erro(exc)


@app.get("/commerce/v1/creatives", dependencies=[Depends(exigir("read"))])
def listar_criativos(product_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if product_id:
        return {"items": creatives.por_produto(product_id)}
    return {"items": listar("commerce_creatives", limit)}


@app.get("/commerce/v1/creative-kinds", dependencies=[Depends(exigir("read"))])
def tipos_de_criativo():
    return {"items": list(creatives.TIPOS)}


@app.post("/commerce/v1/creatives", status_code=201)
def criar_criativo(value: CreativeIn, user=Depends(exigir("write"))):
    try:
        return creatives.criar(**value.model_dump())
    except CommerceError as exc:
        raise _erro(exc)


@app.post("/commerce/v1/creatives/{item_id}/qa")
def rodar_qa(item_id: str, user=Depends(exigir("qa"))):
    try:
        return creatives.rodar_qa(item_id)
    except CommerceError as exc:
        raise HTTPException(404, str(exc))


@app.post("/commerce/v1/creatives/{item_id}/approve")
def aprovar_criativo(item_id: str, user=Depends(exigir("approve"))):
    try:
        criativo = creatives.aprovar(item_id)
    except CommerceError as exc:
        auditar("creative.approval_refused", "creative", item_id, {"reason": str(exc)},
                result="blocked", actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("creative.approved", "creative", item_id, actor=user["actor"], role=user["role"])
    return criativo


@app.post("/commerce/v1/creatives/{item_id}/queue")
def enfileirar(item_id: str, value: QueueIn, user=Depends(exigir("queue"))):
    try:
        resultado = bridge.enfileirar(item_id, value.channel_id, value.platform)
    except CommerceError as exc:
        auditar("creative.queue_refused", "creative", item_id, {"reason": str(exc)},
                result="blocked", actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("creative.queued", "creative", item_id, resultado, actor=user["actor"], role=user["role"])
    return resultado


@app.get("/commerce/v1/creatives/{item_id}/precheck", dependencies=[Depends(exigir("read"))])
def checagem(item_id: str):
    try:
        return bridge.checar_antes_de_publicar(item_id)
    except CommerceError as exc:
        raise HTTPException(404, str(exc))


@app.post("/commerce/v1/products/{item_id}/live-package", status_code=201)
def exportar_pacote(item_id: str, user=Depends(exigir("write"))):
    try:
        resultado = livepilot.exportar(item_id)
    except CommerceError as exc:
        raise _erro(exc)
    auditar("package.exported", "product", item_id, resultado, actor=user["actor"], role=user["role"])
    return resultado


@app.get("/commerce/v1/products/{item_id}/live-package", dependencies=[Depends(exigir("read"))])
def historico_pacotes(item_id: str):
    return {"items": livepilot.historico(item_id)}


@app.post("/commerce/v1/packages/{package_id}/handoff")
def entregar_ao_live_pilot(package_id: str, dry_run: bool = True, user=Depends(exigir("queue"))):
    """Entrega o pacote pelas rotas publicas do Live Pilot. Dry-run por padrao."""
    try:
        resultado = handoff.entregar(package_id, dry_run=dry_run)
    except CommerceError as exc:
        auditar("handoff.refused", "package", package_id, {"reason": str(exc)},
                result="blocked", actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("handoff.dry_run" if resultado["dry_run"] else "handoff.sent", "package", package_id,
            {"chamadas": len(resultado["chamadas"]), "nao_entregue": resultado["nao_entregue"]},
            actor=user["actor"], role=user["role"])
    return resultado


@app.get("/commerce/v1/live-pilot/compatibility", dependencies=[Depends(exigir("read"))])
def compatibilidade_live_pilot():
    return handoff.relatorio_de_compatibilidade()


@app.get("/commerce/v1/audit", dependencies=[Depends(exigir("read"))])
def auditoria(limit: int = Query(100, ge=1, le=500)):
    return {"items": listar("commerce_audit", limit)}
