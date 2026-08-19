"""Feature flags do VexPublish.

Regra do projeto: todo modulo novo nasce desativado e, quando pode publicar,
nasce em dry-run. As flags sao lidas do ambiente a cada chamada para que um
operador possa desligar a publicacao sem reiniciar o worker.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


PLATAFORMAS = ("tiktok", "instagram", "youtube", "kwai")

PADROES = {
    "BOTLIVE_MULTICHANNEL_ENABLED": "false",
    "VEXPUBLISH_ENABLED": "false",
    "VEXPUBLISH_DRY_RUN": "true",
    "VEXPUBLISH_AUTO_PUBLISH": "false",
    "VEXPUBLISH_REQUIRE_APPROVAL": "true",
    "VEXPUBLISH_TIKTOK_ENABLED": "false",
    "VEXPUBLISH_INSTAGRAM_ENABLED": "false",
    "VEXPUBLISH_YOUTUBE_ENABLED": "false",
    "VEXPUBLISH_KWAI_ENABLED": "false",
    "IMPORT_ADAPT_PUBLISH_ENABLED": "false",
}


def _bool(nome: str) -> bool:
    bruto = os.getenv(nome, PADROES.get(nome, "false"))
    return str(bruto).strip().lower() in {"1", "true", "yes", "on", "sim"}


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


@dataclass(frozen=True)
class Flags:
    multichannel: bool
    enabled: bool
    dry_run: bool
    auto_publish: bool
    require_approval: bool
    plataformas: dict
    import_adapt_publish: bool
    max_attempts: int
    backoff_base_seconds: int
    backoff_max_seconds: int
    orphan_seconds: int

    def plataforma_ativa(self, plataforma: str) -> bool:
        return bool(self.plataformas.get(plataforma, False))

    def pode_publicar_de_verdade(self, plataforma: str) -> bool:
        """Publicacao real exige tudo ligado ao mesmo tempo e dry-run desligado."""
        return self.enabled and not self.dry_run and self.plataforma_ativa(plataforma)


def carregar() -> Flags:
    return Flags(
        multichannel=_bool("BOTLIVE_MULTICHANNEL_ENABLED"),
        enabled=_bool("VEXPUBLISH_ENABLED"),
        dry_run=_bool("VEXPUBLISH_DRY_RUN"),
        auto_publish=_bool("VEXPUBLISH_AUTO_PUBLISH"),
        require_approval=_bool("VEXPUBLISH_REQUIRE_APPROVAL"),
        plataformas={
            plataforma: _bool(f"VEXPUBLISH_{plataforma.upper()}_ENABLED")
            for plataforma in PLATAFORMAS
        },
        import_adapt_publish=_bool("IMPORT_ADAPT_PUBLISH_ENABLED"),
        max_attempts=_int("VEXPUBLISH_MAX_ATTEMPTS", 3),
        backoff_base_seconds=_int("VEXPUBLISH_BACKOFF_BASE_SECONDS", 30),
        backoff_max_seconds=_int("VEXPUBLISH_BACKOFF_MAX_SECONDS", 3600),
        orphan_seconds=_int("VEXPUBLISH_ORPHAN_SECONDS", 300),
    )
