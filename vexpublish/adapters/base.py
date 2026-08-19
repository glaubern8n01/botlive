"""Contrato dos adapters de plataforma.

Cinco passos, sempre nesta ordem: login -> check_session -> validate ->
prepare -> publish. O passo publish e o unico que toca a plataforma de
verdade, e ele nao roda em dry-run - nem por engano, nem por flag isolada.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..core import obs
from ..core.errors import CodigoErro, VexPublishError
from ..core.flags import carregar
from ..sessions import vault


class Adapter(ABC):
    """Base dos adapters. Subclasse define plataforma e os cinco passos."""

    plataforma: str = ""
    # SIM / PARCIAL / NAO / NAO VALIDADO - preenchido apos teste real.
    compatibilidade: str = "NAO VALIDADO"

    def login(self, conta: dict, sessao: dict) -> dict:
        """Abre sessao. Captcha/2FA devem chamar vault.exigir_acao_manual."""
        raise VexPublishError(
            CodigoErro.LOGIN_REQUIRED,
            f"Login de {self.plataforma} ainda nao implementado",
            {"platform": self.plataforma},
        )

    def check_session(self, conta: dict, sessao: dict) -> str:
        """Devolve um estado de vault.ESTADOS sem tocar em credencial."""
        return (sessao or {}).get("state", "missing")

    @abstractmethod
    def validate(self, job: dict, conta: dict) -> None:
        """Valida job contra as regras da plataforma. Erra com VALIDATION_ERROR."""

    @abstractmethod
    def prepare(self, job: dict, conta: dict) -> dict:
        """Monta o payload de upload. Nao envia nada."""

    @abstractmethod
    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        """Envia de verdade. Deve devolver {'url': ..., 'external_id': ...}.

        So pode declarar sucesso com evidencia de conclusao da plataforma:
        upload iniciado nao e publicacao concluida.
        """


def validar_midia(job: dict) -> Path:
    caminho = Path(job.get("media_path", ""))
    if not caminho.exists():
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, "Arquivo de midia inexistente", {"job_id": job.get("id")}
        )
    if caminho.stat().st_size <= 0:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, "Arquivo de midia vazio", {"job_id": job.get("id")}
        )
    return caminho


def executar(adapter: Adapter, job: dict, conta: dict) -> dict:
    """Roda o ciclo completo respeitando flags e dry-run.

    Em dry-run a funcao vai ate prepare e para. publish nunca e chamado.
    """
    flags = carregar()
    plataforma = adapter.plataforma

    if not flags.enabled:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, "VEXPUBLISH_ENABLED=false", {"platform": plataforma}
        )
    if not flags.plataforma_ativa(plataforma):
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR,
            f"VEXPUBLISH_{plataforma.upper()}_ENABLED=false",
            {"platform": plataforma},
        )

    sessao = vault.obter(conta["id"], plataforma) or vault.registrar(conta["id"], plataforma)
    # A trava de acao manual vale sobre o estado gravado: nenhum adapter pode
    # dizer que a sessao esta boa depois de um humano marcar captcha/2FA.
    if sessao.get("state") == "manual_required":
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED, "Sessao aguarda acao humana", {"platform": plataforma}
        )
    estado = adapter.check_session(conta, sessao)
    if estado == "manual_required":
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED, "Sessao aguarda acao humana", {"platform": plataforma}
        )
    if estado in {"missing", "expired"}:
        sessao = adapter.login(conta, sessao) or sessao

    adapter.validate(job, conta)
    payload = adapter.prepare(job, conta)

    seco = bool(job.get("dry_run")) or flags.dry_run
    if seco:
        obs.registrar(
            "adapter.dry_run",
            "ok",
            job_id=job.get("id"),
            channel_id=job.get("channel_id"),
            platform=plataforma,
            account=conta.get("handle"),
            passos=["check_session", "validate", "prepare"],
        )
        return {"dry_run": True, "url": "", "external_id": "", "payload_keys": sorted(payload)}

    if not flags.pode_publicar_de_verdade(plataforma):
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR, "Publicacao real bloqueada por flag", {"platform": plataforma}
        )

    resultado = adapter.publish(job, conta, payload) or {}
    if not resultado.get("url") and not resultado.get("external_id"):
        raise VexPublishError(
            CodigoErro.UPLOAD_FAILED,
            "Adapter nao devolveu evidencia de publicacao concluida",
            {"platform": plataforma},
        )
    resultado["dry_run"] = False
    return resultado
