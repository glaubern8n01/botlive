"""Geracao local de imagem, sem GPU e sem custo.

Por que Pillow e nao difusao: a VPS tem 4 vCPU e nenhuma GPU. Wan 2.x, Flux e
Stable Diffusion pedem 6+ GB de VRAM; na CPU levariam minutos por imagem e
horas por video. Aqui cada imagem sai em menos de um segundo.

O que da para gerar assim, e que e exatamente o que o post precisa:
  - capa/thumbnail a partir de um frame do proprio video
  - card de produto (titulo, preco, CTA) para TikTok Shop / Shopee
  - fundo com gradiente quando nao existe imagem de origem

Nada aqui inventa foto de produto. Quando ha imagem de origem, ela e usada;
quando nao ha, o resultado e um card grafico honesto, nao uma foto falsa.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


FONTES = [
    Path(__file__).resolve().parents[2] / "fonts" / "Anton-Regular.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
]

FORMATOS = {
    "vertical": (1080, 1920),   # Reels, Shorts, TikTok, Kwai
    "quadrado": (1080, 1080),   # feed
    "horizontal": (1280, 720),  # thumbnail de YouTube
}


def _fonte(tamanho: int):
    for caminho in FONTES:
        if caminho.exists():
            try:
                return ImageFont.truetype(str(caminho), tamanho)
            except OSError:
                continue
    return ImageFont.load_default()


def _quebrar(texto: str, fonte, largura_max: int, draw) -> list:
    palavras, linhas, atual = texto.split(), [], ""
    for palavra in palavras:
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=fonte) <= largura_max:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def _gradiente(tamanho: tuple, topo=(18, 20, 28), base=(58, 26, 84)) -> Image.Image:
    largura, altura = tamanho
    imagem = Image.new("RGB", (1, altura))
    desenho = ImageDraw.Draw(imagem)
    for y in range(altura):
        t = y / max(altura - 1, 1)
        desenho.point(
            (0, y),
            fill=(
                int(topo[0] + (base[0] - topo[0]) * t),
                int(topo[1] + (base[1] - topo[1]) * t),
                int(topo[2] + (base[2] - topo[2]) * t),
            ),
        )
    return imagem.resize(tamanho)


def frame_do_video(video: str | Path, destino: str | Path, segundo: float = 1.0) -> Path:
    """Tira um frame do video com ffmpeg. E a melhor 'imagem gerada' possivel:
    vem do proprio conteudo, entao nunca promete o que o video nao mostra."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        "ffmpeg", "-y", "-ss", str(segundo), "-i", str(video),
        "-frames:v", "1", "-q:v", "2", str(destino),
    ]
    resultado = subprocess.run(comando, capture_output=True, timeout=120)
    if resultado.returncode != 0 or not destino.is_file():
        raise RuntimeError(f"ffmpeg nao extraiu o frame: {resultado.stderr[-300:]!r}")
    return destino


@dataclass
class Capa:
    """Capa/thumbnail: fundo (frame do video ou gradiente) + faixa de texto."""

    titulo: str
    subtitulo: str = ""
    selo: str = ""
    formato: str = "vertical"
    fundo: str | Path | None = None

    def render(self, destino: str | Path) -> Path:
        if self.formato not in FORMATOS:
            raise ValueError(f"Formato invalido: {self.formato}. Use {list(FORMATOS)}")
        tamanho = FORMATOS[self.formato]
        largura, altura = tamanho

        if self.fundo and Path(self.fundo).is_file():
            base = Image.open(self.fundo).convert("RGB")
            # cobre o quadro inteiro sem distorcer, cortando o excesso
            escala = max(largura / base.width, altura / base.height)
            base = base.resize((int(base.width * escala) + 1, int(base.height * escala) + 1))
            esquerda = (base.width - largura) // 2
            topo = (base.height - altura) // 2
            base = base.crop((esquerda, topo, esquerda + largura, topo + altura))
            # escurece o pe da imagem para o texto ficar legivel
            sombra = Image.new("RGB", tamanho, (0, 0, 0))
            mascara = Image.new("L", tamanho, 0)
            desenho_mascara = ImageDraw.Draw(mascara)
            for y in range(altura):
                t = max(0.0, (y / altura - 0.45) / 0.55)
                desenho_mascara.line([(0, y), (largura, y)], fill=int(215 * t))
            base = Image.composite(sombra, base, mascara.filter(ImageFilter.GaussianBlur(6)))
        else:
            base = _gradiente(tamanho)

        desenho = ImageDraw.Draw(base)
        margem = int(largura * 0.07)
        util = largura - margem * 2

        if self.selo:
            fonte_selo = _fonte(int(largura * 0.035))
            comprimento = desenho.textlength(self.selo.upper(), font=fonte_selo)
            caixa = (margem, margem, margem + comprimento + 34, margem + int(largura * 0.065))
            desenho.rounded_rectangle(caixa, radius=12, fill=(0, 209, 255))
            desenho.text((margem + 17, margem + 10), self.selo.upper(),
                         font=fonte_selo, fill=(8, 10, 16))

        fonte_titulo = _fonte(int(largura * 0.085))
        linhas = _quebrar(self.titulo.upper(), fonte_titulo, util, desenho)[:4]
        altura_linha = int(largura * 0.10)
        y = altura - margem - altura_linha * len(linhas) - (int(largura * 0.06) if self.subtitulo else 0)
        for linha in linhas:
            # contorno para o texto sobreviver a qualquer fundo
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                desenho.text((margem + dx, y + dy), linha, font=fonte_titulo, fill=(0, 0, 0))
            desenho.text((margem, y), linha, font=fonte_titulo, fill=(255, 255, 255))
            y += altura_linha

        if self.subtitulo:
            fonte_sub = _fonte(int(largura * 0.042))
            desenho.text((margem, y + 8), self.subtitulo, font=fonte_sub, fill=(0, 209, 255))

        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        base.save(destino, quality=92)
        return destino


@dataclass
class CardProduto:
    """Card de produto para TikTok Shop / Shopee.

    Usa a foto real do produto quando existe. Sem foto, gera um card grafico -
    nunca uma foto inventada, porque imagem falsa de produto e propaganda
    enganosa, nao criativo.
    """

    titulo: str
    preco: str = ""
    cta: str = ""
    marca: str = ""
    foto: str | Path | None = None
    formato: str = "vertical"

    def render(self, destino: str | Path) -> Path:
        tamanho = FORMATOS[self.formato]
        largura, altura = tamanho
        base = _gradiente(tamanho, (12, 14, 20), (28, 18, 52))
        desenho = ImageDraw.Draw(base)
        margem = int(largura * 0.08)

        if self.foto and Path(self.foto).is_file():
            produto = Image.open(self.foto).convert("RGB")
            lado = largura - margem * 2
            produto.thumbnail((lado, lado))
            moldura = Image.new("RGB", (lado, lado), (255, 255, 255))
            moldura.paste(produto, ((lado - produto.width) // 2, (lado - produto.height) // 2))
            base.paste(moldura, (margem, int(altura * 0.16)))
        else:
            desenho.rounded_rectangle(
                (margem, int(altura * 0.16), largura - margem, int(altura * 0.16) + largura - margem * 2),
                radius=28, outline=(70, 74, 92), width=4,
            )
            aviso = _fonte(int(largura * 0.035))
            desenho.text((margem + 30, int(altura * 0.16) + 30), "sem foto do produto",
                         font=aviso, fill=(120, 126, 148))

        if self.marca:
            desenho.text((margem, margem), self.marca.upper(),
                         font=_fonte(int(largura * 0.036)), fill=(0, 209, 255))

        fonte_titulo = _fonte(int(largura * 0.062))
        y = int(altura * 0.16) + (largura - margem * 2) + int(altura * 0.05)
        for linha in _quebrar(self.titulo, fonte_titulo, largura - margem * 2, desenho)[:3]:
            desenho.text((margem, y), linha, font=fonte_titulo, fill=(255, 255, 255))
            y += int(largura * 0.072)

        if self.preco:
            desenho.text((margem, y + 10), self.preco,
                         font=_fonte(int(largura * 0.095)), fill=(74, 222, 128))

        if self.cta:
            fonte_cta = _fonte(int(largura * 0.045))
            comprimento = desenho.textlength(self.cta, font=fonte_cta)
            caixa = (margem, altura - margem - int(largura * 0.10),
                     margem + comprimento + 60, altura - margem)
            desenho.rounded_rectangle(caixa, radius=18, fill=(0, 209, 255))
            desenho.text((margem + 30, altura - margem - int(largura * 0.075)),
                         self.cta, font=fonte_cta, fill=(8, 10, 16))

        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        base.save(destino, quality=92)
        return destino


def capacidades() -> dict:
    """O que este executor entrega de verdade - usado pelo doctor e pelo painel."""
    return {
        "provider": "pillow-local",
        "tier": "local",
        "custo": 0.0,
        "gpu": False,
        "formatos": sorted(FORMATOS),
        "gera": ["capa", "thumbnail", "card_produto", "frame_de_video"],
        "nao_gera": ["foto de produto inexistente", "cena fotorrealista", "video"],
    }
