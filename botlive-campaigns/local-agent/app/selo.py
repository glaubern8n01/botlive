"""Selo obrigatorio queimado DENTRO do corte.

Por que isto existe
-------------------
Tres campanhas seguidas exigem elemento visual dentro do video, e nao na
legenda:

  - GabePeixe: "todo corte precisa ter o LOWER, legivel durante todo o corte e
    embaixo do rosto do Gabe";
  - Juninho Manella: "precisa divulgar a Kick NO CORTE - nao e na legenda, nem
    no titulo do video, e NO CORTE";
  - Lucas Clash ON: nao exige selo, mas proibe overlay com marca nao
    autorizada - por isso o selo e por campanha, nunca global.

O overlay_editor do BotLive desenha titulo, marca e CTA por alguns segundos.
Aqui o requisito e outro: uma imagem (o lower que a organizacao distribui) ou
uma linha de texto fixa, presente do primeiro ao ultimo quadro. Sem isso o
corte e desclassificado mesmo tendo hashtag e mencao certas.

Fica em ffmpeg puro, num passe de video sobre o arquivo ja renderizado: o audio
e copiado sem recodificar e o corte original nunca e sobrescrito antes do
sucesso.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


# O lower fica na faixa de baixo, mas acima da area onde Reels e TikTok
# empilham legenda e botoes. 0.72 da altura deixa o selo embaixo do rosto (que
# o enquadramento vertical joga para o centro) e ainda longe da interface.
ALTURA_PADRAO = 0.72
LARGURA_PADRAO = 0.62


def _ffmpeg():
    return os.getenv("CAMPAIGNS_FFMPEG", "ffmpeg")


def achar_arquivo(caminho: str) -> Path | None:
    """Acha o arquivo do selo, aqui ou na pasta de selos desta maquina.

    A campanha e cadastrada na VPS e guarda um caminho de la
    (/data/agents/selos/...). Quem renderiza e o PC, onde esse caminho nao
    existe. Em vez de exigir cadastro por maquina, procura o mesmo nome de
    arquivo em CAMPAIGNS_SELOS_DIR.
    """
    if not caminho:
        return None
    direto = Path(caminho)
    if direto.is_file():
        return direto
    pasta = os.getenv("CAMPAIGNS_SELOS_DIR", "").strip()
    if pasta:
        aqui = Path(pasta) / direto.name
        if aqui.is_file():
            return aqui
    return None


def conferir(config: dict) -> None:
    """Levanta erro se a campanha exige selo e ele nao esta disponivel.

    Serve para checar ANTES de renderizar: sem isto o corte era renderizado
    inteiro - minutos de CPU - so para morrer no passo seguinte, e ainda tres
    vezes, por causa das tentativas do job.
    """
    if not config:
        return
    tipo = (config.get("tipo") or ("imagem" if config.get("arquivo") else "texto")).lower()
    if tipo != "imagem":
        montar_filtro(config)
        return
    if achar_arquivo(config.get("arquivo") or "") is None:
        raise FileNotFoundError(
            f"Selo obrigatorio nao encontrado: {config.get('arquivo')}"
            " (coloque o arquivo em CAMPAIGNS_SELOS_DIR)")


def _escapar(texto: str) -> str:
    """No drawtext, dois-pontos, barra e aspa simples sao sintaxe do filtro."""
    return (texto.replace("\\", r"\\").replace(":", r"\:")
            .replace("'", "").replace("%", r"\%"))


def _filtro_imagem(config: dict) -> str:
    largura = float(config.get("largura_pct", LARGURA_PADRAO))
    altura = float(config.get("altura_pct", ALTURA_PADRAO))
    return (f"[1:v]scale=main_w*{largura}:-1:eval=init[selo];"
            f"[0:v][selo]overlay=(main_w-overlay_w)/2:main_h*{altura}"
            ":eval=init[v]")


def _caminho_de_fonte(config: dict) -> str:
    """Fonte do selo, no formato que o drawtext aceita.

    Sem fontfile o ffmpeg cai numa serifada padrao que destoa de todo o resto
    do BotLive - a Anton embarcada no repo e a mesma do overlay_editor, entao
    o corte de campanha sai com a mesma cara dos outros.

    O caminho do Windows precisa de tratamento: no drawtext a barra invertida e
    escape e os dois-pontos de "G:" separam parametros do filtro.
    """
    escolhida = (config.get("fonte") or "").strip()
    if not escolhida:
        padrao = Path(__file__).resolve().parents[3] / "fonts" / "Anton-Regular.ttf"
        if not padrao.exists():
            return ""
        escolhida = str(padrao)
    return escolhida.replace("\\", "/").replace(":", r"\:")


def _filtro_texto(config: dict) -> str:
    texto = _escapar(str(config.get("texto", "")).strip())
    altura = float(config.get("altura_pct", ALTURA_PADRAO))
    fonte = _caminho_de_fonte(config)
    arquivo = f"fontfile='{fonte}':" if fonte else ""
    # Caixa atras do texto: o requisito das campanhas e ser LEGIVEL o corte
    # inteiro, e texto branco sozinho some em cena clara.
    return (f"[0:v]drawtext={arquivo}text='{texto}':fontcolor=white:"
            f"fontsize=h/24:box=1:boxcolor=black@0.6:boxborderw=16:"
            f"x=(w-text_w)/2:y=h*{altura}[v]")


def montar_filtro(config: dict) -> str:
    """Monta o filtro do selo. Levanta erro quando a campanha pede o
    impossivel - selo obrigatorio sem arquivo nem texto e falha de cadastro,
    nao algo para descobrir depois de publicar."""
    tipo = (config.get("tipo") or ("imagem" if config.get("arquivo") else "texto")).lower()
    if tipo == "imagem":
        if not config.get("arquivo"):
            raise ValueError("Selo de imagem sem arquivo")
        return _filtro_imagem(config)
    if not str(config.get("texto") or "").strip():
        raise ValueError("Selo de texto sem texto")
    return _filtro_texto(config)


def aplicar(video: str | Path, config: dict) -> dict:
    """Queima o selo no corte, do primeiro ao ultimo quadro.

    Devolve o que o rules.py precisa para registrar a checagem. Sem config,
    devolve `aplicado: False` e nao toca no arquivo.
    """
    video = Path(video)
    if not config:
        return {"aplicado": False, "motivo": "campanha nao exige selo"}

    tipo = (config.get("tipo") or ("imagem" if config.get("arquivo") else "texto")).lower()
    arquivo = config.get("arquivo")
    if tipo == "imagem":
        # Acontece de verdade: o lower do GabePeixe vem de uma pasta no Drive e
        # alguem precisa baixar. Travar aqui e melhor que publicar corte
        # desclassificado.
        encontrado = achar_arquivo(arquivo or "")
        if encontrado is None:
            raise FileNotFoundError(f"Selo obrigatorio nao encontrado: {arquivo}")
        arquivo = str(encontrado)

    filtro = montar_filtro(config)
    saida = video.with_name(video.stem + "-selo.mp4")
    comando = [_ffmpeg(), "-y", "-i", str(video)]
    if tipo == "imagem":
        comando += ["-i", str(arquivo)]
    comando += ["-filter_complex", filtro, "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                str(saida)]

    processo = subprocess.run(comando, capture_output=True, text=True, timeout=1800)
    if processo.returncode != 0 or not saida.exists():
        detalhe = (processo.stderr or "").strip().splitlines()
        raise RuntimeError("ffmpeg falhou ao aplicar o selo: "
                           + (detalhe[-1][:300] if detalhe else ""))

    shutil.move(str(saida), str(video))
    return {"aplicado": True, "tipo": tipo,
            "referencia": str(arquivo) if tipo == "imagem" else config.get("texto", "")}
