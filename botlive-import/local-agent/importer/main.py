"""API local do modulo Importar / Adaptar / Publicar.

Modulo desligado por padrao: com IMPORT_ADAPT_PUBLISH_ENABLED=false a API
inteira responde 404. Ligado, ela ainda nao publica nada - o que sai daqui e
PublishJob em draft para o VexPublish.
"""

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import bridge, library, sources
from .adapt import executar, planejar, validar_plano
from .store import ImportError_, auditar, listar, migrar, obter


PAPEIS = {"admin": {"*"}, "operator": {"read", "write", "render", "queue"}, "reviewer": {"read"}}


def modulo_ligado() -> bool:
    return os.getenv("IMPORT_ADAPT_PUBLISH_ENABLED", "false").strip().lower() == "true"


def tokens() -> dict:
    return {
        "admin": os.getenv("IMPORT_ADMIN_TOKEN", os.getenv("IMPORT_LOCAL_TOKEN", "")),
        "operator": os.getenv("IMPORT_OPERATOR_TOKEN", ""),
        "reviewer": os.getenv("IMPORT_REVIEWER_TOKEN", ""),
    }


def exigir(acao: str):
    def dependencia(x_import_token: str | None = Header(default=None)):
        if not modulo_ligado():
            raise HTTPException(404, "Modulo desativado")
        for papel, token in tokens().items():
            if token and x_import_token and hmac.compare_digest(token, x_import_token):
                if "*" in PAPEIS[papel] or acao in PAPEIS[papel]:
                    return {"actor": papel, "role": papel}
                raise HTTPException(403, "Permissao insuficiente")
        raise HTTPException(401, "Token invalido")

    return dependencia


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrar()
    yield


app = FastAPI(title="BotLive Importar/Adaptar/Publicar", version="1.0.0", lifespan=lifespan)
origens = [
    x.strip()
    for x in os.getenv(
        "IMPORT_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if x.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origens,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Import-Token"],
)


class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: str
    location: str = ""
    channel_id: str = ""
    authorized: bool = False
    authorization_source: str = ""
    license: str = ""
    rights_notes: str = ""
    allow_download: bool = False


class BatchIn(BaseModel):
    source_id: str
    folder: str | None = None


class ItemIn(BaseModel):
    source_id: str
    path: str
    credit: str = ""
    origin_url: str = ""


class PlanIn(BaseModel):
    item_id: str
    channel_id: str = ""
    plan: dict = {}


class QueueIn(BaseModel):
    platform: str | None = None
    caption: str = ""


def _erro(exc: ImportError_) -> HTTPException:
    return HTTPException(422, str(exc))


@app.get("/import/v1/health")
def health():
    return {
        "ok": True,
        "enabled": modulo_ligado(),
        "download_liberado": sources.download_liberado_no_ambiente(),
        "publica_direto": False,
        "saida": "PublishJob em draft no VexPublish",
    }


@app.get("/import/v1/sources", dependencies=[Depends(exigir("read"))])
def listar_fontes(limit: int = Query(100, ge=1, le=500)):
    return {"items": listar("import_sources", limit)}


@app.post("/import/v1/sources", status_code=201)
def criar_fonte(value: SourceIn, user=Depends(exigir("write"))):
    try:
        fonte = sources.criar(**value.model_dump())
    except ImportError_ as exc:
        auditar("source.rejected", "source", payload={"reason": str(exc)}, result="blocked",
                actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("source.created", "source", fonte["id"], actor=user["actor"], role=user["role"])
    return fonte


@app.post("/import/v1/sources/{item_id}/archive")
def arquivar_fonte(item_id: str, user=Depends(exigir("write"))):
    try:
        return sources.arquivar(item_id)
    except ImportError_ as exc:
        raise HTTPException(404, str(exc))


@app.get("/import/v1/items", dependencies=[Depends(exigir("read"))])
def listar_itens(source_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return {"items": library.biblioteca(source_id, limit)}


@app.post("/import/v1/items", status_code=201)
def registrar_item(value: ItemIn, user=Depends(exigir("write"))):
    try:
        item = library.registrar(value.source_id, value.path, value.credit, value.origin_url)
    except ImportError_ as exc:
        raise _erro(exc)
    auditar("item.registered", "item", item["id"], actor=user["actor"], role=user["role"])
    return item


@app.post("/import/v1/batch", status_code=201)
def importar_lote(value: BatchIn, user=Depends(exigir("write"))):
    try:
        resultado = library.importar_pasta(value.source_id, value.folder)
    except ImportError_ as exc:
        raise _erro(exc)
    auditar("batch.imported", "source", value.source_id, resultado,
            actor=user["actor"], role=user["role"])
    return resultado


@app.get("/import/v1/adaptations", dependencies=[Depends(exigir("read"))])
def listar_adaptacoes(limit: int = Query(100, ge=1, le=500)):
    return {"items": listar("import_adaptations", limit)}


@app.post("/import/v1/adaptations", status_code=201)
def planejar_adaptacao(value: PlanIn, user=Depends(exigir("write"))):
    try:
        adaptacao = planejar(value.item_id, value.channel_id, value.plan)
    except ImportError_ as exc:
        auditar("adaptation.rejected", "item", value.item_id, {"reason": str(exc)},
                result="blocked", actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("adaptation.planned", "adaptation", adaptacao["id"],
            actor=user["actor"], role=user["role"])
    return adaptacao


@app.post("/import/v1/adaptations/validate")
def validar_apenas(value: PlanIn, user=Depends(exigir("read"))):
    """Confere o plano sem gravar nada - util para o dashboard avisar antes."""
    try:
        return {"plan": validar_plano(value.plan), "ok": True}
    except ImportError_ as exc:
        raise _erro(exc)


@app.post("/import/v1/adaptations/{item_id}/render")
def renderizar(item_id: str, user=Depends(exigir("render"))):
    try:
        return executar(item_id)
    except ImportError_ as exc:
        raise _erro(exc)


@app.post("/import/v1/adaptations/{item_id}/queue")
def enfileirar(item_id: str, value: QueueIn, user=Depends(exigir("queue"))):
    try:
        resultado = bridge.enfileirar(item_id, value.platform, value.caption)
    except ImportError_ as exc:
        auditar("adaptation.queue_refused", "adaptation", item_id, {"reason": str(exc)},
                result="blocked", actor=user["actor"], role=user["role"])
        raise _erro(exc)
    auditar("adaptation.queued", "adaptation", item_id, resultado,
            actor=user["actor"], role=user["role"])
    return resultado


@app.get("/import/v1/audit", dependencies=[Depends(exigir("read"))])
def auditoria(limit: int = Query(100, ge=1, le=500)):
    return {"items": listar("import_audit", limit)}
