"""Adapter YouTube Shorts. Estado: PARCIAL - login validado, envio nao.

O login reaproveita o OAuth que ja existe em yt_publisher.py: mesmo
client_secret, mesmos tokens em .tokens/youtube/<conta>.json, mesma renovacao
de access token. Nada e duplicado e o publisher legado nao e alterado.

check_session e login sao somente leitura: a prova de conexao e um
channels.list (1 unidade de cota). O fluxo interativo de autorizacao continua
sendo acao humana - este adapter nunca abre navegador sozinho.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from ..core.errors import CodigoErro, VexPublishError
from ..sessions import vault
from .base import Adapter, validar_midia


LIMITE_TITULO = 100
REPO_ROOT = Path(__file__).resolve().parents[2]


def _yt_publisher():
    """Carrega o publisher legado da raiz do repo sem tocar nele."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    caminho = REPO_ROOT / "yt_publisher.py"
    spec = importlib.util.spec_from_file_location("vexpublish_legacy_yt", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


VISIBILIDADES = ("private", "unlisted", "public")
TAGS_MAX_TOTAL_CHARS = 400


def conta_legada(conta: dict) -> str:
    """O handle da conta e o nome usado em .tokens/youtube/<conta>.json."""
    return (conta.get("handle") or "").lstrip("@").strip()


def _visibilidade(valor: str | None) -> str:
    """Padrao private. Publico exige opt-in explicito no ambiente.

    Ja aconteceu de corte errado vazar para o canal; deixar 'public' a um
    campo de distancia e risco desnecessario enquanto o adapter e novo.
    """
    escolhida = (valor or "private").strip().lower()
    if escolhida not in VISIBILIDADES:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, f"Visibilidade invalida: {escolhida}"
        )
    if escolhida == "public" and os.getenv(
        "VEXPUBLISH_YOUTUBE_ALLOW_PUBLIC", "false"
    ).strip().lower() not in {"1", "true", "yes", "sim"}:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR,
            "Publicacao publica bloqueada: ligue VEXPUBLISH_YOUTUBE_ALLOW_PUBLIC para liberar",
        )
    return escolhida


def _tags(bruto) -> list:
    """Aceita lista ou o JSON guardado no job. Respeita o teto de caracteres."""
    if isinstance(bruto, str):
        try:
            bruto = json.loads(bruto or "[]")
        except (TypeError, ValueError):
            bruto = []
    saida, total = [], 0
    for tag in bruto or []:
        limpa = str(tag).lstrip("#").strip()
        if not limpa or limpa in saida:
            continue
        if total + len(limpa) > TAGS_MAX_TOTAL_CHARS:
            break
        saida.append(limpa)
        total += len(limpa)
    return saida


def _codigo_do_erro(erro: Exception) -> str:
    texto = str(erro).lower()
    if "cota" in texto or "quota" in texto or "limit" in texto:
        return CodigoErro.RATE_LIMITED
    if "rede" in texto or "network" in texto or "timeout" in texto:
        return CodigoErro.NETWORK_ERROR
    return CodigoErro.UPLOAD_FAILED


class YouTubeAdapter(Adapter):
    plataforma = "youtube"
    compatibilidade = "PARCIAL"  # login validado; envio validado com video private

    def check_session(self, conta: dict, sessao: dict) -> str:
        """Estado da sessao sem enviar nada. Nao renova nem autoriza."""
        nome = conta_legada(conta)
        if not nome:
            return "missing"
        legado = _yt_publisher()
        if not legado._token_path(nome).is_file():
            return "missing"
        try:
            legado._credenciais(nome)
        except Exception:
            return "expired"
        return "valid"

    def login(self, conta: dict, sessao: dict) -> dict:
        """Prova a conexao com channels.list. Nunca abre navegador."""
        nome = conta_legada(conta)
        legado = _yt_publisher()
        if not legado._token_path(nome).is_file():
            raise VexPublishError(
                CodigoErro.LOGIN_REQUIRED,
                f"Conta {nome!r} sem token: rode "
                f"'python yt_publisher.py autorizar --conta {nome}' uma vez",
                {"platform": self.plataforma},
            )
        try:
            info = legado.testar_auth(nome)
        except Exception as erro:
            vault.marcar(conta["id"], self.plataforma, "expired")
            raise VexPublishError(
                CodigoErro.SESSION_EXPIRED,
                f"Sessao do YouTube nao validou: {erro}",
                {"platform": self.plataforma},
            ) from erro
        vault.marcar(conta["id"], self.plataforma, "valid")
        # Nao devolvemos credencial nenhuma: so o que e seguro logar.
        return {
            **(sessao or {}),
            "state": "valid",
            "canal_conectado": info.get("canal"),
            "channel_id_remoto": info.get("channel_id"),
        }

    def validate(self, job: dict, conta: dict) -> None:
        validar_midia(job)
        if not (job.get("title") or "").strip():
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, "YouTube exige titulo")

    def prepare(self, job: dict, conta: dict) -> dict:
        return {
            "video_path": job["media_path"],
            "title": (job.get("title") or "")[:LIMITE_TITULO],
            "description": job.get("caption") or "",
            "tags": job.get("hashtags") or "[]",
            "privacy_status": "private",
            "account": conta["handle"],
        }

    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        """Envia e so declara sucesso com evidencia de conclusao.

        Upload devolver um id nao basta: o adapter consulta videos.list depois
        para confirmar que o video existe de verdade e conferir a visibilidade
        que ficou gravada. Se a consulta nao confirmar, isso vira UPLOAD_FAILED
        em vez de "postado".
        """
        nome = conta_legada(conta)
        legado = _yt_publisher()
        caminho = Path(payload["video_path"])
        if not caminho.is_file():
            raise VexPublishError(
                CodigoErro.VALIDATION_ERROR, "Arquivo sumiu antes do envio", {"path": str(caminho)}
            )

        visibilidade = _visibilidade(payload.get("privacy_status"))
        metadados = {
            "titulo": legado._sanitizar_titulo(payload.get("title") or ""),
            "descricao": payload.get("description") or "",
            "tags": _tags(payload.get("tags")),
            "categoria_id": legado.CATEGORIA_DEFAULT,
            "visibilidade": visibilidade,
            "made_for_kids": False,
        }

        try:
            enviado = legado._upload(caminho, metadados, nome)
        except Exception as erro:
            raise VexPublishError(
                _codigo_do_erro(erro), f"Upload falhou: {erro}", {"platform": self.plataforma}
            ) from erro

        video_id = enviado.get("video_id")
        if not video_id:
            raise VexPublishError(
                CodigoErro.UPLOAD_FAILED, "Upload sem id de video", {"platform": self.plataforma}
            )

        confirmado = self._confirmar(legado, nome, video_id)
        return {
            "url": enviado.get("url") or f"https://youtu.be/{video_id}",
            "external_id": video_id,
            "privacy_status": confirmado["privacy_status"],
            "upload_status": confirmado["upload_status"],
        }

    def _confirmar(self, legado, nome: str, video_id: str) -> dict:
        """videos.list no id recem-criado. Sem confirmacao nao ha publicacao."""
        try:
            resposta = (
                legado._service(nome)
                .videos()
                .list(part="status", id=video_id)
                .execute()
            )
        except Exception as erro:
            raise VexPublishError(
                CodigoErro.UPLOAD_FAILED,
                f"Upload sem confirmacao: {erro}",
                {"video_id": video_id},
            ) from erro
        itens = resposta.get("items") or []
        if not itens:
            raise VexPublishError(
                CodigoErro.UPLOAD_FAILED,
                "Video nao encontrado apos o upload",
                {"video_id": video_id},
            )
        status = itens[0].get("status", {})
        if status.get("uploadStatus") in {"failed", "rejected", "deleted"}:
            raise VexPublishError(
                CodigoErro.UPLOAD_FAILED,
                f"YouTube recusou o video: {status.get('uploadStatus')}",
                {"video_id": video_id, "motivo": status.get("failureReason") or status.get("rejectionReason")},
            )
        return {
            "privacy_status": status.get("privacyStatus", ""),
            "upload_status": status.get("uploadStatus", ""),
        }
