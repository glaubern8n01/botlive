"""Envio da resposta no direct, pela Private Reply oficial do Instagram.

Como o ManyChat faz, e como aqui tambem e feito: a Graph API permite UMA
resposta privada por comentario, dentro de 7 dias. O endpoint e
POST /{ig_user_id}/messages com recipient={"comment_id": ...}.

E oficial - nao automatiza o app, nao usa sessao de navegador e nao viola os
termos. Por isso nao derruba conta.

Tres travas antes de qualquer envio:
  1. DM_ENABLED ligado e DM_DRY_RUN desligado;
  2. teto por hora e por dia, por conta;
  3. comment_id unico no banco - a mesma pessoa nunca recebe duas vezes.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import regras
from .store import DmError, agora, atualizar, auditar, conectar, inserir, obter


GRAPH = "https://graph.facebook.com/v23.0"


def flags() -> dict:
    def ligado(nome, padrao="false"):
        return os.getenv(nome, padrao).strip().lower() in {"1", "true", "yes", "sim"}

    return {
        "enabled": ligado("DM_ENABLED"),
        "dry_run": ligado("DM_DRY_RUN", "true"),
        "max_por_hora": int(os.getenv("DM_MAX_POR_HORA", "20")),
        "max_por_dia": int(os.getenv("DM_MAX_POR_DIA", "150")),
    }


def _credenciais(conta: str) -> dict:
    """Reaproveita o token que o instagram_publisher ja guarda."""
    from pathlib import Path

    caminho = Path(__file__).resolve().parents[2] / ".tokens" / "instagram" / f"{conta}.json"
    if not caminho.is_file():
        raise DmError(
            f"Conta {conta!r} sem token. Autorize com: "
            f"python instagram_publisher.py autorizar --conta {conta}"
        )
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not dados.get("ig_user_id"):
        raise DmError(f"Token da conta {conta!r} sem ig_user_id")
    return dados


def enviados_na_janela(conta: str, horas: int) -> int:
    corte = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    with conectar() as db:
        linha = db.execute(
            "SELECT COUNT(*) AS total FROM dm_respostas "
            "WHERE conta=? AND status='enviado' AND dry_run=0 AND enviado_em>=?",
            (conta, corte),
        ).fetchone()
    return int(linha["total"]) if linha else 0


def dentro_do_teto(conta: str) -> tuple[bool, str]:
    atual = flags()
    if atual["max_por_hora"] and enviados_na_janela(conta, 1) >= atual["max_por_hora"]:
        return False, "teto_por_hora"
    if atual["max_por_dia"] and enviados_na_janela(conta, 24) >= atual["max_por_dia"]:
        return False, "teto_por_dia"
    return True, ""


def ja_respondido(comment_id: str) -> dict | None:
    with conectar() as db:
        linha = db.execute(
            "SELECT * FROM dm_respostas WHERE comment_id=?", (comment_id,)
        ).fetchone()
    return dict(linha) if linha else None


def _post(ig_user_id: str, token: str, comment_id: str, texto: str) -> dict:
    corpo = json.dumps({
        "recipient": {"comment_id": comment_id},
        "message": {"text": texto},
    }).encode("utf-8")
    requisicao = urllib.request.Request(
        f"{GRAPH}/{ig_user_id}/messages?access_token={urllib.parse.quote(token)}",
        data=corpo, method="POST",
    )
    requisicao.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(requisicao, timeout=30) as resposta:
            return json.loads(resposta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:300]
        raise DmError(f"Instagram recusou o direct (HTTP {erro.code}): {detalhe}") from erro
    except urllib.error.URLError as erro:
        raise DmError(f"rede indisponivel: {erro.reason}") from erro


def responder(comentario: dict) -> dict:
    """Casa a regra e responde o comentario no direct.

    comentario: {comment_id, conta, texto, media_id, autor}
    """
    comment_id = comentario["comment_id"]
    conta = comentario["conta"]

    anterior = ja_respondido(comment_id)
    if anterior:
        # Nao e erro: webhook repetido e normal. So nao manda de novo.
        return {"status": "ja_respondido", "resposta_id": anterior["id"]}

    regra = regras.casar(comentario.get("texto", ""), conta, comentario.get("media_id", ""))
    if not regra:
        auditar("comentario.sem_regra", "comentario", comment_id,
                {"texto": comentario.get("texto", "")[:120]})
        return {"status": "sem_regra"}

    texto = regras.montar_resposta(regra)
    estado = flags()

    if not estado["enabled"]:
        auditar("dm.bloqueado", "comentario", comment_id, {"motivo": "DM_ENABLED=false"},
                resultado="blocked")
        return {"status": "modulo_desligado", "texto_previsto": texto}

    permitido, motivo = dentro_do_teto(conta)
    if not permitido:
        auditar("dm.bloqueado", "comentario", comment_id, {"motivo": motivo}, resultado="blocked")
        return {"status": "teto_atingido", "motivo": motivo}

    registro = inserir("dm_respostas", {
        "comment_id": comment_id,
        "regra_id": regra["id"],
        "conta": conta,
        "texto": texto,
        "status": "pendente",
        "dry_run": 1 if estado["dry_run"] else 0,
        "created_at": agora(),
    })

    if estado["dry_run"]:
        atualizar("dm_respostas", registro["id"],
                  {"status": "simulado", "enviado_em": agora()})
        auditar("dm.simulado", "comentario", comment_id, {"regra": regra["nome"]})
        return {"status": "simulado", "resposta_id": registro["id"], "texto": texto}

    dados = _credenciais(conta)
    try:
        envio = _post(dados["ig_user_id"], dados["access_token"], comment_id, texto)
    except DmError as erro:
        atualizar("dm_respostas", registro["id"], {"status": "falha", "erro": str(erro)[:400]})
        auditar("dm.falha", "comentario", comment_id, {"erro": str(erro)[:200]}, resultado="erro")
        raise

    atualizar("dm_respostas", registro["id"], {"status": "enviado", "enviado_em": agora()})
    auditar("dm.enviado", "comentario", comment_id,
            {"regra": regra["nome"], "message_id": envio.get("message_id", "")})
    return {"status": "enviado", "resposta_id": registro["id"], "resposta": envio}


def registrar_comentario(comment_id: str, conta: str, texto: str,
                         media_id: str = "", autor: str = "") -> dict:
    """Guarda o comentario recebido. Repetido nao vira linha nova."""
    with conectar() as db:
        linha = db.execute(
            "SELECT * FROM dm_comentarios WHERE comment_id=?", (comment_id,)
        ).fetchone()
    if linha:
        return dict(linha)
    return inserir("dm_comentarios", {
        "comment_id": comment_id,
        "media_id": media_id,
        "conta": conta,
        "autor": autor,
        "texto": texto,
        "recebido_em": agora(),
    })
