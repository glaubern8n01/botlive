"""Download em lote de fontes autorizadas, via yt-dlp.

O executor que faltava: os dois interruptores (ambiente + fonte) ja existiam
em sources.py, mas nada baixava de fato.

Regra que nao muda: so baixa de fonte com autorizacao declarada. Isso nao e
burocracia - repostar video de terceiro sem direito e violacao de direito
autoral e motivo de derrubada de conta. A trava fica no codigo para nao
depender de lembrar na hora.

Nada aqui contorna login, paywall ou protecao tecnica. Conteudo que exige
sessao so e acessivel com cookies do proprio dono, informados por ele.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .library import EXTENSOES, registrar
from .sources import exigir_ativa, exigir_download_permitido
from .store import ImportError_, agora, auditar


# 0 = perfil inteiro. O padrao e 20 para a primeira execucao nao virar um
# download de horas sem querer; quem quer tudo passa limite=0 explicitamente.
LIMITE_PADRAO = int(os.getenv("IMPORT_DOWNLOAD_LIMITE", "20"))
TUDO = 0
TIMEOUT = int(os.getenv("IMPORT_DOWNLOAD_TIMEOUT", "600"))


def ferramenta() -> list:
    """Comando do yt-dlp, como lista de argumentos.

    O pacote esta no requirements do BotLive, mas nem sempre coloca o
    executavel no PATH (foi o caso no Windows do Glauber). Cair para
    "python -m yt_dlp" evita depender de como o pip instalou.
    """
    caminho = shutil.which("yt-dlp")
    if caminho:
        return [caminho]
    import importlib.util

    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    raise ImportError_(
        "yt-dlp nao encontrado. Instale com: python -m pip install yt-dlp"
    )


def _cookies() -> list:
    """Cookies do proprio dono da conta, quando ele fornece.

    Serve para baixar o que a conta dele ja ve - nao para acessar o que ela
    nao veria.
    """
    arquivo = os.getenv("IMPORT_COOKIES_FILE", "").strip()
    if arquivo and Path(arquivo).is_file():
        return ["--cookies", arquivo]
    return []


def listar(url: str, limite: int = LIMITE_PADRAO) -> list:
    """Lista o que existe na URL sem baixar nada (--flat-playlist).

    limite=0 lista o perfil inteiro. Util para conferir o tamanho antes de
    mandar baixar tudo.
    """
    comando = [*ferramenta(), "--flat-playlist", "--dump-json"]
    if limite and limite > 0:
        comando += ["--playlist-end", str(limite)]
    comando += [*_cookies(), url]
    processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT)
    if processo.returncode != 0:
        raise ImportError_(f"yt-dlp nao listou a fonte: {processo.stderr[-400:].strip()}")

    itens = []
    for linha in processo.stdout.splitlines():
        try:
            dado = json.loads(linha)
        except json.JSONDecodeError:
            continue
        itens.append({
            "id": dado.get("id"),
            "titulo": dado.get("title") or "",
            "url": dado.get("url") or dado.get("webpage_url") or "",
            "duracao": dado.get("duration"),
        })
    return itens


@dataclass
class Resultado:
    baixados: list
    repetidos: list
    falhas: list

    def resumo(self) -> dict:
        return {
            "baixados": len(self.baixados),
            "repetidos": len(self.repetidos),
            "falhas": len(self.falhas),
            "item_ids": self.baixados,
            "detalhe_falhas": self.falhas[:20],
        }


def baixar(source_id: str, url: str | None = None, limite: int = LIMITE_PADRAO,
           actor: str = "operator") -> dict:
    """Baixa da fonte e coloca tudo na biblioteca, com deduplicacao.

    limite=0 (TUDO) baixa o perfil inteiro. O historico do yt-dlp evita
    rebaixar o que ja veio, entao rodar de novo so pega o que e novo.

    Item ja existente pelo SHA-256 nao vira arquivo novo: o mesmo video
    baixado de novo continua sendo um item so.
    """
    fonte = exigir_ativa(source_id)
    exigir_download_permitido(fonte)

    alvo = (url or fonte["location"] or "").strip()
    if not alvo:
        raise ImportError_("Fonte sem URL de origem para baixar")

    destino = Path(os.getenv("IMPORT_DOWNLOAD_DIR", Path(__file__).resolve().parents[2] / "data" / "downloads"))
    destino = destino / source_id
    destino.mkdir(parents=True, exist_ok=True)

    comando = [
        *ferramenta(),
        "--no-playlist-reverse",
        "--no-overwrites",
        # Perfil inteiro pode ser centenas de itens: sem arquivo de historico
        # cada execucao tentaria tudo de novo.
        "--download-archive", str(destino / ".baixados.txt"),
        "--ignore-errors",
        "--restrict-filenames",
        "--merge-output-format", "mp4",
        "-o", str(destino / "%(id)s.%(ext)s"),
        *_cookies(),
    ]
    if limite and limite > 0:
        comando += ["--playlist-end", str(limite)]
    comando.append(alvo)
    processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT)

    baixados, repetidos, falhas = [], [], []
    if processo.returncode != 0 and not any(destino.iterdir()):
        raise ImportError_(f"download falhou: {processo.stderr[-400:].strip()}")
    if processo.returncode != 0:
        falhas.append({"etapa": "yt-dlp", "motivo": processo.stderr[-200:].strip()})

    for arquivo in sorted(destino.iterdir()):
        if not arquivo.is_file() or arquivo.suffix.lower() not in EXTENSOES:
            continue
        try:
            from .library import por_sha, sha256

            antes = por_sha(sha256(arquivo))
            item = registrar(source_id, arquivo, origin_url=alvo)
            (repetidos if antes else baixados).append(item["id"])
        except ImportError_ as erro:
            falhas.append({"arquivo": arquivo.name, "motivo": str(erro)})

    resultado = Resultado(baixados, repetidos, falhas).resumo()
    auditar("source.downloaded", "source", source_id,
            {**resultado, "url": alvo, "quando": agora()}, actor=actor)
    return resultado
