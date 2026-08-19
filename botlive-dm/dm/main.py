"""API local do respondedor de comentarios.

Duas superficies:
  - gestao das regras (autenticada por token, como os outros agentes);
  - webhook do Instagram, que a Meta chama e por isso NAO usa o token do
    painel: ele e validado por assinatura HMAC do proprio app da Meta.

Desligado por padrao: com DM_ENABLED=false a API responde, mas nenhuma
mensagem sai - o webhook so registra o comentario.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import enviar, regras
from .store import DmError, auditar, listar, migrar, obter


PAPEIS = {"admin": {"*"}, "operator": {"read", "write"}, "reviewer": {"read"}}


def modulo_disponivel() -> bool:
    """A tela de regras abre mesmo com o envio desligado - e assim que se
    prepara a operacao antes de ligar."""
    return os.getenv("DM_MODULE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "sim"}


def exigir(acao: str):
    def dependencia(x_dm_token: str | None = Header(default=None)):
        if not modulo_disponivel():
            raise HTTPException(404, "Modulo desativado")
        tokens = {
            "admin": os.getenv("DM_ADMIN_TOKEN", ""),
            "operator": os.getenv("DM_OPERATOR_TOKEN", ""),
            "reviewer": os.getenv("DM_REVIEWER_TOKEN", ""),
        }
        for papel, token in tokens.items():
            if token and x_dm_token and hmac.compare_digest(token, x_dm_token):
                if "*" in PAPEIS[papel] or acao in PAPEIS[papel]:
                    return {"actor": papel, "role": papel}
                raise HTTPException(403, "Permissao insuficiente")
        raise HTTPException(401, "Token invalido")

    return dependencia


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrar()
    yield


app = FastAPI(title="BotLive DM", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        x.strip() for x in os.getenv(
            "DM_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",") if x.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Dm-Token"],
)


class RegraIn(BaseModel):
    conta: str = Field(min_length=1)
    nome: str = Field(min_length=2, max_length=80)
    palavras: list[str] = []
    resposta: str = Field(min_length=2)
    link: str = ""
    media_id: str = ""
    prioridade: int = Field(100, ge=1, le=1000)


class TesteIn(BaseModel):
    conta: str
    texto: str
    media_id: str = ""


def _erro(exc: DmError) -> HTTPException:
    return HTTPException(422, str(exc))


@app.get("/dm/v1/health")
def health():
    estado = enviar.flags()
    return {
        "ok": True,
        **estado,
        "mecanica": "Private Reply oficial da Graph API",
        "uma_resposta_por_comentario": True,
    }


@app.get("/dm/v1/regras", dependencies=[Depends(exigir("read"))])
def listar_regras(conta: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if conta:
        return {"items": listar("dm_regras", limit, "conta=?", (conta,))}
    return {"items": listar("dm_regras", limit)}


@app.post("/dm/v1/regras", status_code=201)
def criar_regra(value: RegraIn, user=Depends(exigir("write"))):
    try:
        regra = regras.criar(**value.model_dump())
    except DmError as exc:
        raise _erro(exc)
    auditar("regra.criada", "regra", regra["id"], {"nome": regra["nome"]})
    return regra


@app.post("/dm/v1/regras/{item_id}/ativar")
def ativar_regra(item_id: str, ativa: bool = True, user=Depends(exigir("write"))):
    try:
        return regras.ativar(item_id, ativa)
    except DmError as exc:
        raise HTTPException(404, str(exc))


@app.post("/dm/v1/testar")
def testar(value: TesteIn, user=Depends(exigir("read"))):
    """Mostra qual regra casaria e o texto que sairia. Nunca envia."""
    regra = regras.casar(value.texto, value.conta, value.media_id)
    if not regra:
        return {"casou": False, "resposta": None}
    return {
        "casou": True,
        "regra": regra["nome"],
        "resposta": regras.montar_resposta(regra),
    }


@app.get("/dm/v1/respostas", dependencies=[Depends(exigir("read"))])
def listar_respostas(limit: int = Query(100, ge=1, le=500)):
    return {"items": listar("dm_respostas", limit)}


@app.get("/dm/v1/audit", dependencies=[Depends(exigir("read"))])
def auditoria(limit: int = Query(100, ge=1, le=500)):
    return {"items": listar("dm_audit", limit)}


# --- Webhook da Meta -------------------------------------------------------
# Nao usa o token do painel: quem chama e a Meta. A autenticidade vem da
# assinatura HMAC com o app secret.


@app.get("/dm/v1/webhook", response_class=PlainTextResponse)
def verificar_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
):
    """Handshake de verificacao que a Meta faz ao cadastrar o webhook."""
    esperado = os.getenv("DM_WEBHOOK_VERIFY_TOKEN", "")
    if hub_mode == "subscribe" and esperado and hmac.compare_digest(hub_verify_token, esperado):
        return hub_challenge
    raise HTTPException(403, "verify token invalido")


def _assinatura_confere(corpo: bytes, cabecalho: str | None) -> bool:
    segredo = os.getenv("DM_APP_SECRET", "")
    if not segredo:
        return False
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.split("=", 1)[1])


@app.post("/dm/v1/webhook")
async def receber_webhook(
    request: Request, x_hub_signature_256: str | None = Header(default=None)
):
    """Recebe comentarios e responde conforme a regra.

    Comentario sem regra so e registrado. Comentario ja respondido e ignorado
    - webhook repetido e normal e nao pode virar segunda mensagem.
    """
    corpo = await request.body()
    if not _assinatura_confere(corpo, x_hub_signature_256):
        auditar("webhook.assinatura_invalida", "webhook", None, {}, resultado="blocked")
        raise HTTPException(403, "assinatura invalida")

    try:
        evento = json.loads(corpo.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "corpo invalido")

    processados = []
    for entrada in evento.get("entry", []) or []:
        conta_id = str(entrada.get("id", ""))
        for mudanca in entrada.get("changes", []) or []:
            if mudanca.get("field") != "comments":
                continue
            valor = mudanca.get("value", {}) or {}
            comment_id = str(valor.get("id", ""))
            if not comment_id:
                continue
            conta = os.getenv("DM_CONTA_PADRAO", "principal")
            texto = valor.get("text", "") or ""
            media_id = str((valor.get("media") or {}).get("id", ""))
            autor = str((valor.get("from") or {}).get("username", ""))

            enviar.registrar_comentario(comment_id, conta, texto, media_id, autor)
            try:
                resultado = enviar.responder({
                    "comment_id": comment_id, "conta": conta, "texto": texto,
                    "media_id": media_id, "autor": autor,
                })
            except DmError as exc:
                resultado = {"status": "falha", "erro": str(exc)}
            processados.append({"comment_id": comment_id, **resultado})

    return {"recebidos": len(processados), "processados": processados}
