"""Adapter Kwai. Estado: NAO VALIDADO - nada testado com conta brasileira.

Ordem de investigacao definida no projeto, a ser seguida em fase propria:
  1. API oficial Kwai/Kuaishou, se existir para o Brasil;
  2. dreammis/social-auto-upload (skill kuaishou-upload);
  3. Fuploader;
  4. Playwright especifico para Kwai Brasil;
  5. Android Docker + ADB como ultimo recurso.

Kwai Brasil e Kuaishou nao podem ser tratados como o mesmo alvo: dominio,
cookies e seletores precisam ser confirmados um a um antes de qualquer envio.
"""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter, validar_midia


ORDEM_DE_INVESTIGACAO = (
    "api-oficial",
    "social-auto-upload",
    "fuploader",
    "playwright-kwai-br",
    "android-adb",
)


class KwaiAdapter(Adapter):
    plataforma = "kwai"
    compatibilidade = "NAO VALIDADO"

    def validate(self, job: dict, conta: dict) -> None:
        validar_midia(job)

    def prepare(self, job: dict, conta: dict) -> dict:
        return {
            "video_path": job["media_path"],
            "caption": job.get("caption") or "",
            "account": conta["handle"],
            "rota_pretendida": ORDEM_DE_INVESTIGACAO[0],
        }

    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED,
            "Kwai sem rota validada: investigar a ordem definida antes de publicar",
            {"platform": self.plataforma, "ordem": list(ORDEM_DE_INVESTIGACAO)},
        )
