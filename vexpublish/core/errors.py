"""Codigos de erro e estados do VexPublish.

Os codigos sao fechados de proposito: o dashboard e os logs estruturados so
podem exibir valores desta lista, para que falha nova nunca vire texto solto.
"""

from __future__ import annotations


class CodigoErro:
    SESSION_EXPIRED = "SESSION_EXPIRED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    PLATFORM_CHANGED = "PLATFORM_CHANGED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"
    UNKNOWN = "UNKNOWN"


CODIGOS = frozenset(
    valor for chave, valor in vars(CodigoErro).items() if not chave.startswith("_")
)

# Erros que nao adianta repetir sozinho: exigem acao humana antes de nova tentativa.
CODIGOS_SEM_RETRY = frozenset(
    {
        CodigoErro.LOGIN_REQUIRED,
        CodigoErro.MANUAL_ACTION_REQUIRED,
        CodigoErro.VALIDATION_ERROR,
        CodigoErro.PLATFORM_CHANGED,
    }
)


class VexPublishError(Exception):
    """Erro de publicacao com codigo fechado e detalhe sem segredo."""

    def __init__(self, codigo: str, mensagem: str = "", detalhe: dict | None = None):
        if codigo not in CODIGOS:
            codigo = CodigoErro.UNKNOWN
        super().__init__(mensagem or codigo)
        self.codigo = codigo
        self.mensagem = mensagem or codigo
        self.detalhe = detalhe or {}

    def pode_repetir(self) -> bool:
        return self.codigo not in CODIGOS_SEM_RETRY


# --- Maquina de estados do PublishJob -------------------------------------

ESTADOS = (
    "draft",
    "approved",
    "pending",
    "scheduled",
    "publishing",
    "posted",
    "failed",
    "retry",
    "cancelled",
)

ESTADOS_TERMINAIS = frozenset({"posted", "cancelled"})

TRANSICOES = {
    "draft": {"approved", "cancelled"},
    "approved": {"pending", "scheduled", "cancelled"},
    "pending": {"scheduled", "publishing", "cancelled"},
    "scheduled": {"pending", "publishing", "cancelled"},
    "publishing": {"posted", "failed", "retry"},
    "retry": {"pending", "publishing", "failed", "cancelled"},
    "failed": {"retry", "cancelled"},
    "posted": set(),
    "cancelled": set(),
}


def transicao_valida(origem: str, destino: str) -> bool:
    return destino in TRANSICOES.get(origem, set())


def exigir_transicao(origem: str, destino: str) -> None:
    if not transicao_valida(origem, destino):
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR,
            f"Transicao invalida: {origem} -> {destino}",
            {"from": origem, "to": destino},
        )
