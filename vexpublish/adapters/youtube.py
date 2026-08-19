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


def conta_legada(conta: dict) -> str:
    """O handle da conta e o nome usado em .tokens/youtube/<conta>.json."""
    return (conta.get("handle") or "").lstrip("@").strip()


class YouTubeAdapter(Adapter):
    plataforma = "youtube"
    compatibilidade = "PARCIAL"

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
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED,
            "Publicacao real do YouTube ainda nao ligada ao VexPublish",
            {"platform": self.plataforma},
        )
