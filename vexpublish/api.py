"""API local do VexPublish.

Serve a aba de canais de publicacao do dashboard. Roda como agente local,
autenticado por token e por papel, e nunca publica nada sozinha: aprovar e
liberar um job apenas o move na fila, que continua presa as flags do modulo.
"""

from __future__ import annotations

import hmac
import json
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import adapters
from .accounts import registry
from .core import analytics, doctor, models, quotas, store
from .core.errors import VexPublishError
from .core.flags import PLATAFORMAS, carregar
from .queue import jobs as fila
from .sessions import vault


PAPEIS = {
    "admin": {"*"},
    "operator": {"read", "write", "jobs"},
    "reviewer": {"read", "approve"},
}


def modulo_disponivel() -> bool:
    """A aba de canais nao exige publicacao ligada, so multi-canais ligado."""
    flags = carregar()
    return flags.multichannel or flags.enabled


def tokens() -> dict:
    return {
        "admin": os.getenv("VEXPUBLISH_ADMIN_TOKEN", os.getenv("VEXPUBLISH_LOCAL_TOKEN", "")),
        "operator": os.getenv("VEXPUBLISH_OPERATOR_TOKEN", ""),
        "reviewer": os.getenv("VEXPUBLISH_REVIEWER_TOKEN", ""),
    }


def identidade(candidato: str | None) -> dict:
    for papel, token in tokens().items():
        if token and candidato and hmac.compare_digest(token, candidato):
            return {"actor": papel, "role": papel}
    raise HTTPException(401, "Token invalido")


def exigir(acao: str):
    def dependencia(x_vexpublish_token: str | None = Header(default=None)):
        if not modulo_disponivel():
            raise HTTPException(404, "Modulo desativado")
        usuario = identidade(x_vexpublish_token)
        permitido = PAPEIS[usuario["role"]]
        if "*" not in permitido and acao not in permitido:
            raise HTTPException(403, "Permissao insuficiente")
        return usuario

    return dependencia


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.migrar()
    yield


app = FastAPI(title="BotLive VexPublish", version="1.0.0", lifespan=lifespan)
origens = [
    x.strip()
    for x in os.getenv(
        "VEXPUBLISH_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if x.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origens,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-VexPublish-Token"],
)


class ChannelIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    niche: str = ""
    platforms: list[str] = []
    identity: dict = {}
    voice: str = ""
    calendar: dict = {}
    content_rules: dict = {}
    preferred_providers: list[str] = []
    notes: str = ""


class AccountIn(BaseModel):
    channel_id: str
    platform: str
    handle: str = Field(min_length=1, max_length=160)
    label: str = ""
    max_posts_per_day: int = Field(0, ge=0, le=1000)
    minimum_interval_minutes: int = Field(0, ge=0, le=10080)
    allowed_hours: list[int] = []
    timezone: str = "UTC"


class LimitsIn(BaseModel):
    max_posts_per_day: int | None = Field(None, ge=0, le=1000)
    minimum_interval_minutes: int | None = Field(None, ge=0, le=10080)
    allowed_hours: list[int] | None = None
    timezone: str | None = None


class SnapshotIn(BaseModel):
    channel_id: str
    platform: str
    job_id: str | None = None
    views: int = Field(0, ge=0)
    watch_seconds: float = Field(0, ge=0)
    retention: float = Field(0, ge=0, le=1)
    revenue: float = Field(0, ge=0)
    source: str = "manual"


def _erro(exc: VexPublishError) -> HTTPException:
    return HTTPException(422, exc.mensagem)


@app.get("/vexpublish/v1/health")
def health():
    flags = carregar()
    return {
        "ok": True,
        "multichannel": flags.multichannel,
        "enabled": flags.enabled,
        "dry_run": flags.dry_run,
        "auto_publish": flags.auto_publish,
        "require_approval": flags.require_approval,
        "plataformas": flags.plataformas,
        "adapters": adapters.compatibilidade(),
        "publicacao_real_liberada": {
            plataforma: flags.pode_publicar_de_verdade(plataforma) for plataforma in PLATAFORMAS
        },
    }


@app.get("/vexpublish/v1/channels", dependencies=[Depends(exigir("read"))])
def listar_canais(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return {"items": store.listar("vexpublish_channels", limit, offset)}


@app.post("/vexpublish/v1/channels", status_code=201)
def criar_canal(value: ChannelIn, user=Depends(exigir("write"))):
    try:
        return models.Channel(**value.model_dump()).salvar()
    except VexPublishError as exc:
        raise _erro(exc)


@app.put("/vexpublish/v1/channels/{item_id}")
def editar_canal(item_id: str, value: ChannelIn, user=Depends(exigir("write"))):
    if not store.obter("vexpublish_channels", item_id):
        raise HTTPException(404, "Canal inexistente")
    dados = value.model_dump()
    payload = {
        "name": dados["name"],
        "niche": dados["niche"],
        "voice": dados["voice"],
        "notes": dados["notes"],
        "platforms": json.dumps(dados["platforms"], ensure_ascii=False),
        "identity": json.dumps(dados["identity"], ensure_ascii=False),
        "calendar": json.dumps(dados["calendar"], ensure_ascii=False),
        "content_rules": json.dumps(dados["content_rules"], ensure_ascii=False),
        "preferred_providers": json.dumps(dados["preferred_providers"], ensure_ascii=False),
        "updated_at": store.agora(),
    }
    return store.atualizar("vexpublish_channels", item_id, payload)


@app.post("/vexpublish/v1/channels/{item_id}/status")
def mudar_status_canal(item_id: str, ativo: bool, user=Depends(exigir("write"))):
    if not store.obter("vexpublish_channels", item_id):
        raise HTTPException(404, "Canal inexistente")
    return store.atualizar(
        "vexpublish_channels",
        item_id,
        {"status": "active" if ativo else "paused", "updated_at": store.agora()},
    )


@app.get("/vexpublish/v1/channels/{item_id}", dependencies=[Depends(exigir("read"))])
def resumo_canal(item_id: str, dias: int = Query(30, ge=1, le=365)):
    try:
        return analytics.resumo_canal(item_id, dias)
    except VexPublishError as exc:
        raise HTTPException(404, exc.mensagem)


@app.get("/vexpublish/v1/channels/{item_id}/history", dependencies=[Depends(exigir("read"))])
def historico_canal(item_id: str, limit: int = Query(50, ge=1, le=200)):
    if not store.obter("vexpublish_channels", item_id):
        raise HTTPException(404, "Canal inexistente")
    return {"items": analytics.historico_canal(item_id, limit)}


@app.get("/vexpublish/v1/compare", dependencies=[Depends(exigir("read"))])
def comparar(dias: int = Query(30, ge=1, le=365), incluir_pausados: bool = True):
    return analytics.comparar_canais(dias, incluir_pausados)


@app.get("/vexpublish/v1/accounts", dependencies=[Depends(exigir("read"))])
def listar_contas(channel_id: str | None = None):
    if channel_id:
        return {"items": registry.por_canal(channel_id)}
    return {"items": store.listar("vexpublish_accounts", 500)}


@app.post("/vexpublish/v1/accounts", status_code=201)
def criar_conta(value: AccountIn, user=Depends(exigir("write"))):
    if not store.obter("vexpublish_channels", value.channel_id):
        raise HTTPException(404, "Canal inexistente")
    try:
        registro = models.Account(**value.model_dump()).salvar()
    except VexPublishError as exc:
        raise _erro(exc)
    vault.registrar(registro["id"], registro["platform"])
    return store.obter("vexpublish_accounts", registro["id"])


@app.put("/vexpublish/v1/accounts/{item_id}/limits")
def definir_limites(item_id: str, value: LimitsIn, user=Depends(exigir("write"))):
    if not store.obter("vexpublish_accounts", item_id):
        raise HTTPException(404, "Conta inexistente")
    limites = {k: v for k, v in value.model_dump().items() if v is not None}
    if not limites:
        raise HTTPException(422, "Informe ao menos um limite")
    try:
        return registry.definir_limites(item_id, **limites)
    except VexPublishError as exc:
        raise _erro(exc)


@app.post("/vexpublish/v1/accounts/{item_id}/status")
def mudar_status_conta(item_id: str, ativa: bool, user=Depends(exigir("write"))):
    if not store.obter("vexpublish_accounts", item_id):
        raise HTTPException(404, "Conta inexistente")
    return registry.ativar(item_id) if ativa else registry.pausar(item_id)


@app.get("/vexpublish/v1/sessions", dependencies=[Depends(exigir("read"))])
def listar_sessoes():
    """Estado das sessoes. Nenhum cookie ou caminho de credencial e devolvido."""
    itens = store.listar("vexpublish_sessions", 500)
    return {
        "items": [
            {
                "account_id": x["account_id"],
                "platform": x["platform"],
                "state": x["state"],
                "last_checked_at": x["last_checked_at"],
            }
            for x in itens
        ]
    }


@app.get("/vexpublish/v1/jobs", dependencies=[Depends(exigir("read"))])
def listar_jobs(
    channel_id: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    if channel_id:
        return {"items": store.listar("vexpublish_jobs", limit, offset, "channel_id=?", (channel_id,))}
    return {"items": store.listar("vexpublish_jobs", limit, offset)}


@app.post("/vexpublish/v1/jobs/{item_id}/approve")
def aprovar_job(item_id: str, user=Depends(exigir("approve"))):
    try:
        return models.aprovar(item_id)
    except KeyError:
        raise HTTPException(404, "Job inexistente")
    except VexPublishError as exc:
        raise _erro(exc)


@app.post("/vexpublish/v1/jobs/{item_id}/queue")
def enfileirar_job(item_id: str, user=Depends(exigir("jobs"))):
    try:
        return models.liberar_para_fila(item_id)
    except KeyError:
        raise HTTPException(404, "Job inexistente")
    except VexPublishError as exc:
        raise _erro(exc)


@app.post("/vexpublish/v1/jobs/{item_id}/cancel")
def cancelar_job(item_id: str, motivo: str = "", user=Depends(exigir("jobs"))):
    try:
        return models.cancelar(item_id, motivo)
    except KeyError:
        raise HTTPException(404, "Job inexistente")
    except VexPublishError as exc:
        raise _erro(exc)


@app.get("/vexpublish/v1/queue", dependencies=[Depends(exigir("read"))])
def resumo_fila():
    return fila.resumo()


@app.get("/vexpublish/v1/doctor", dependencies=[Depends(exigir("read"))])
def diagnostico():
    """Saude do modulo: dependencias, banco, sessoes, jobs travados, disco e fila."""
    return doctor.diagnostico()


@app.get("/vexpublish/v1/quotas", dependencies=[Depends(exigir("read"))])
def estado_das_quotas():
    return quotas.estado()


@app.post("/vexpublish/v1/metrics", status_code=201)
def registrar_metrica(value: SnapshotIn, user=Depends(exigir("write"))):
    try:
        return analytics.registrar_snapshot(**value.model_dump())
    except VexPublishError as exc:
        raise _erro(exc)
