"""Adapter Kwai. Estado: NAO - investigado em 22/08/2026, sem rota automatizavel.

A ordem definida no projeto foi percorrida inteira. O resultado, com a
evidencia de cada passo, esta em docs/VALIDACAO-KWAI.md. Resumo:

  1. API oficial ......... NAO. So existe superficie de anuncios (Kwai for
     Business) e o Creator Marketplace. Nenhuma documentacao publica de
     publicacao de video, cadastro de app ou OAuth para criador brasileiro.
  2. social-auto-upload .. NAO para o Brasil. O uploader dirige
     passport.kuaishou.com e cp.kuaishou.com/article/publish/video, com
     seletores em chines. E o painel de criador da Kuaishou China - conta,
     dominio e interface diferentes do Kwai BR.
  3. Fuploader ........... NAO pelo mesmo motivo: distribui para plataformas
     chinesas (Douyin, Kuaishou, Xiaohongshu, Bilibili) mais TikTok.
  4. Playwright Kwai BR .. NAO tem o que automatizar: creator.kwai.com
     responde 301 para a home e nao existe pagina de upload pela web. O
     proprio ecossistema orienta emulador Android para postar do PC.
  5. Android + ADB ....... impossivel na VPS (nao existe /dev/kvm, e o
     processador nao expoe vmx/svm). No PC seria possivel, e e o que ja
     acontece na pratica pelo celular real.

Ou seja: hoje o Kwai publica por caminho MANUAL no celular, e e assim que os
cortes sobem. Nao ha rota automatizavel para colocar aqui - por isso este
adapter recusa publicar em vez de fingir que funciona.

Kwai Brasil e Kuaishou continuam sendo alvos diferentes: dominio, cookies e
seletores nao coincidem, e foi exatamente o que a investigacao confirmou.
"""

from __future__ import annotations

from ..core.errors import CodigoErro, VexPublishError
from .base import Adapter, validar_midia


# Rota -> veredito da investigacao de 22/08/2026.
ORDEM_DE_INVESTIGACAO = (
    ("api-oficial", "NAO: sem API publica de publicacao para criador BR"),
    ("social-auto-upload", "NAO: dirige cp.kuaishou.com (China), nao Kwai BR"),
    ("fuploader", "NAO: mesmas plataformas chinesas + TikTok"),
    ("playwright-kwai-br", "NAO: Kwai BR nao tem upload pela web"),
    ("android-adb", "impossivel na VPS (sem /dev/kvm); no celular ja e manual"),
)


class KwaiAdapter(Adapter):
    plataforma = "kwai"
    # Investigado, nao "ainda nao olhamos": as cinco rotas foram percorridas e
    # nenhuma serve para a conta brasileira. Ver docs/VALIDACAO-KWAI.md.
    compatibilidade = "NAO"

    def validate(self, job: dict, conta: dict) -> None:
        validar_midia(job)

    def prepare(self, job: dict, conta: dict) -> dict:
        return {
            "video_path": job["media_path"],
            "caption": job.get("caption") or "",
            "account": conta["handle"],
            # A unica rota que existe hoje. Prepare monta o material; quem
            # publica e a pessoa, no celular.
            "rota_pretendida": "manual-mobile",
        }

    def publish(self, job: dict, conta: dict, payload: dict) -> dict:
        raise VexPublishError(
            CodigoErro.MANUAL_ACTION_REQUIRED,
            "Kwai nao tem rota automatizavel: a publicacao e manual, pelo celular. "
            "As cinco rotas foram investigadas em 22/08/2026 (docs/VALIDACAO-KWAI.md).",
            {"platform": self.plataforma, "rotas_investigadas": dict(ORDEM_DE_INVESTIGACAO)},
        )
