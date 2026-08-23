"""Deteccao de plataforma e adapters de fonte.

O documento pede adapters por plataforma em vez de uma funcao gigante. O que
muda entre elas hoje e pouco (yt-dlp cobre todas), mas o ponto e ter onde
encaixar a diferenca quando ela aparecer - e ja aparece: Instagram e TikTok
costumam exigir cookies do proprio dono, YouTube nao.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .store import MassaError


URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


@dataclass(frozen=True)
class Plataforma:
    nome: str
    dominios: tuple
    precisa_cookies: bool
    observacao: str = ""

    def reconhece(self, url: str) -> bool:
        alvo = url.lower()
        return any(d in alvo for d in self.dominios)


PLATAFORMAS = (
    Plataforma("instagram", ("instagram.com", "instagr.am"), True,
               "Reels e posts costumam exigir sessao do proprio dono."),
    Plataforma("tiktok", ("tiktok.com", "vm.tiktok.com"), True,
               "Perfil publico funciona; conteudo restrito exige cookies."),
    Plataforma("youtube", ("youtube.com", "youtu.be", "shorts"), False,
               "Publico funciona sem sessao."),
    Plataforma("kwai", ("kwai.com", "kwai-video.com"), False),
)

GENERICA = Plataforma("generico", (), False, "Qualquer URL que o yt-dlp suporte.")


def detectar(url: str) -> Plataforma:
    for plataforma in PLATAFORMAS:
        if plataforma.reconhece(url):
            return plataforma
    return GENERICA


def extrair_urls(texto: str) -> list:
    """Pega URLs de texto colado, TXT ou area de transferencia.

    Aceita uma por linha, varias na mesma linha, ou texto solto no meio -
    o operador cola o que tem e o modulo separa. Ordem preservada e sem
    repetir.
    """
    vistas, saida = set(), []
    for bruta in URL.findall(texto or ""):
        limpa = bruta.rstrip(".,;)]}\"'")
        if limpa not in vistas:
            vistas.add(limpa)
            saida.append(limpa)
    return saida


def classificar(urls: list) -> dict:
    """Quantas de cada plataforma - e o '47 links detectados' da interface."""
    contagem, detalhe = {}, []
    for url in urls:
        plataforma = detectar(url)
        contagem[plataforma.nome] = contagem.get(plataforma.nome, 0) + 1
        detalhe.append({
            "url": url,
            "plataforma": plataforma.nome,
            "precisa_cookies": plataforma.precisa_cookies,
        })
    return {
        "total": len(urls),
        "por_plataforma": contagem,
        "itens": detalhe,
        "avisos": sorted({
            f"{p.nome}: {p.observacao}"
            for p in PLATAFORMAS
            if p.observacao and contagem.get(p.nome)
        }),
    }


def ler_arquivo(caminho: str) -> list:
    """Importa links.txt. Le como texto e reaproveita a mesma extracao."""
    from pathlib import Path

    arquivo = Path(caminho)
    if not arquivo.is_file():
        raise MassaError(f"Arquivo nao encontrado: {arquivo}")
    if arquivo.stat().st_size > 5 * 1024 * 1024:
        raise MassaError("Arquivo de links acima de 5MB - provavelmente nao e uma lista")
    return extrair_urls(arquivo.read_text(encoding="utf-8", errors="replace"))
