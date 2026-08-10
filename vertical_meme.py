from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from moviepy.editor import CompositeVideoClip, ImageClip, VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import CompositeVideoClip, ImageClip, VideoFileClip


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
MARGIN_X = 64
BACKGROUND_COLOR = (13, 13, 13)
CAPTION_COLOR = (255, 255, 255)
CREATOR_COLOR = (255, 235, 120)
CHANNEL_COLOR = (185, 185, 185)
CAPTION_MAX_CHARS = 90
CAPTION_MAX_LINES = 2
FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# Credito do canal proprio por nicho. Troca por comando (--credito-canal) ou
# editando aqui.
CREDITO_CANAL_POR_NICHO = {
    "football": "Futebol Respira",
    "gta": "@GTA6brasilcortesoficial",
}


import random as _random

# Legendas de topo variadas por tipo de lance (nunca repetir sempre a mesma).
LEGENDAS_POR_LANCE = {
    "defesa": ["QUE DEFESA ABSURDA!", "O GOLEIRO SALVOU TUDO", "VOCÊ VIU ESSA DEFESA?!",
               "PEGOU O IMPOSSÍVEL", "MURALHA NO GOL", "DEFESA DE OUTRO MUNDO"],
    "gol": ["QUE GOLAÇO!", "ISSO FOI PINTURA", "GOL DE PLACA", "NÃO ACREDITO NESSE GOL",
            "GOL ABSURDO DEMAIS", "TINHA QUE SER ASSIM"],
    "penalti": ["PÊNALTI DECISIVO!", "NA HORA DA PRESSÃO", "BATEU E MARCOU", "COBRANÇA PERFEITA"],
    "drible": ["QUE DRIBLE FOI ESSE?!", "DEIXOU O MARCADOR NO CHÃO", "MAGIA PURA", "DRIBLE DESCONCERTANTE"],
    "var": ["O VAR ENTROU EM AÇÃO", "POLÊMICA NO LANCE", "REVISÃO MUDOU TUDO"],
    "expulsao": ["CARTÃO VERMELHO!", "EXPULSÃO POLÊMICA", "ACABOU O JOGO PRA ELE"],
    "reacao": ["A REAÇÃO FOI ÉPICA", "OLHA ESSA COMEMORAÇÃO", "EMOÇÃO PURA"],
}
LEGENDAS_GENERICAS = ["ISSO É FUTEBOL DE VERDADE", "MELHOR MOMENTO DA RODADA", "LANCE PRA REVER MIL VEZES",
                      "FUTEBOL QUE ARREPIA", "MOMENTO INESQUECÍVEL", "PRA QUEM AMA FUTEBOL"]


def legenda_aleatoria(highlight: Optional[str] = None, seed: Optional[int] = None) -> str:
    """Legenda de topo variada e coerente com o lance (não usa o título cru)."""
    rng = _random.Random(seed)
    key = (highlight or "").lower()
    pool = next((v for k, v in LEGENDAS_POR_LANCE.items() if k in key), None) or LEGENDAS_GENERICAS
    return rng.choice(pool + LEGENDAS_GENERICAS)


# Contexto real extraído do título do vídeo (competição, clássico, craques) para
# gerar hooks específicos como o Futebol Respira ("MAIOR CLÁSSICO DO BRASIL",
# "MOMENTO RAIVA NA FINAL DA LIBERTADORES"), em vez de frase genérica.
_COMPETICOES = {
    "libertadores": "NA LIBERTADORES", "copa do brasil": "NA COPA DO BRASIL",
    "champions": "NA CHAMPIONS", "brasileir": "NO BRASILEIRÃO", "copa américa": "NA COPA AMÉRICA",
    "copa america": "NA COPA AMÉRICA", "conmebol": "NA CONMEBOL", "mundial": "NO MUNDIAL",
    "copa do mundo": "NA COPA DO MUNDO", "premier": "NA PREMIER LEAGUE", "la liga": "NA LA LIGA",
    "sul-americana": "NA SUL-AMERICANA", "sudamericana": "NA SUL-AMERICANA", "paulista": "NO PAULISTÃO",
    "carioca": "NO CARIOCA", "final": "NA FINAL",
}
_CRAQUES = ("neymar", "messi", "cristiano", "ronaldo", "romário", "romario", "ronaldinho",
            "maradona", "pelé", "pele", "raphinha", "vini", "vinícius", "vinicius", "endrick",
            "haaland", "mbappé", "mbappe", "suárez", "suarez", "gabigol", "hulk", "arrascaeta")
_CLASSICOS = ("clássico", "classico", "derby", "dérbi")


def contexto_do_titulo(titulo: Optional[str]) -> dict:
    """Extrai competição, craque e se é clássico do título real (minúsculo)."""
    t = " ".join((titulo or "").split()).lower()
    comp = next((rotulo for termo, rotulo in _COMPETICOES.items() if termo in t), None)
    craque = next((c for c in _CRAQUES if c in t), None)
    classico = any(m in t for m in _CLASSICOS)
    return {"competicao": comp, "craque": craque, "classico": classico, "cru": t}


def legenda_contextual(titulo_real: Optional[str], highlight: Optional[str] = None,
                       seed: Optional[int] = None) -> str:
    """Hook de topo específico do vídeo quando o título dá contexto real; senão
    cai no pool variado por tipo de lance."""
    rng = _random.Random(seed)
    ctx = contexto_do_titulo(titulo_real)
    opcoes: list[str] = []
    if ctx["craque"]:
        nome = ctx["craque"].upper()
        opcoes += [f"OLHA O QUE {nome} FEZ", f"{nome} DECIDIU O JOGO", f"CRAQUE É CRAQUE: {nome}"]
    if ctx["competicao"]:
        opcoes += [f"MOMENTO QUENTE {ctx['competicao']}", f"ISSO ACONTECEU {ctx['competicao']}",
                   f"LANCE PRA HISTÓRIA {ctx['competicao']}"]
    if ctx["classico"]:
        opcoes += ["TENSÃO NO CLÁSSICO", "CLÁSSICO PEGA FOGO", "ISSO É CLÁSSICO DE VERDADE"]
    if opcoes:
        return rng.choice(opcoes)
    return legenda_aleatoria(highlight, seed=seed)


# Subtexto (linha menor de baixo): fala do vídeo/torcida, nunca @ nem nome de canal.
SUBTEXTOS_POR_LANCE = {
    "defesa": ["O goleiro fez o impossível", "Salvou o time no último segundo", "A torcida foi à loucura",
               "Reflexo de outro nível", "Ninguém esperava essa defesa"],
    "gol": ["A torcida explodiu", "Gol que ficou na história", "O estádio veio abaixo",
            "Comemoração emocionante", "Craque decidiu a partida"],
    "penalti": ["Nervos de aço na cobrança", "Decidiu tudo na marca da cal", "Frieza total sob pressão"],
    "drible": ["Humilhou o marcador", "Jogada digna de vídeo game", "Talento puro em campo"],
    "var": ["Lance que gerou discussão", "Revisão que mudou o jogo"],
    "expulsao": ["Clima esquentou em campo", "Time ficou com um a menos"],
    "reacao": ["Emoção do início ao fim", "Reação que viralizou"],
}
SUBTEXTOS_GENERICOS = ["Você precisa ver até o final", "Salva esse pra rever depois",
                       "Momento que arrepia qualquer torcedor", "Futebol em estado puro",
                       "Marca aquele amigo que ama futebol", "Comenta o que achou"]


def subtexto_aleatorio(highlight: Optional[str] = None, seed: Optional[int] = None) -> str:
    """Linha menor de baixo: fala do vídeo, variada, sem @ nem nome de canal."""
    rng = _random.Random(None if seed is None else seed + 991)
    key = (highlight or "").lower()
    pool = next((v for k, v in SUBTEXTOS_POR_LANCE.items() if k in key), None) or SUBTEXTOS_GENERICOS
    return rng.choice(pool + SUBTEXTOS_GENERICOS)


def credito_canal_para_nicho(nicho: Optional[str], override: Optional[str] = None) -> Optional[str]:
    """Resolve o credito do canal: override explicito ganha do default do nicho."""
    if override:
        return override
    if nicho:
        return CREDITO_CANAL_POR_NICHO.get(nicho)
    return None


@dataclass(frozen=True)
class MemeTextConfig:
    """Textos das tarjas do layout vertical-meme.

    legenda: clickbait da tarja de cima (sempre renderizada em CAIXA ALTA).
    credito_streamer: @ do streamer, primeira linha da tarja de baixo.
    canal_proprio: canal do dono do bot, segunda linha da tarja de baixo.
    """

    legenda: Optional[str] = None
    subtexto: Optional[str] = None        # linha menor de baixo: fala do vídeo, sem @/canal
    credito_streamer: Optional[str] = None
    canal_proprio: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return any([self.legenda, self.subtexto, self.credito_streamer, self.canal_proprio])


def _font(size: int) -> ImageFont.FreeTypeFont:
    # Anton embarcada no repo: mesma cara no Windows local e no Linux da VPS.
    candidates = [
        FONTS_DIR / "Anton-Regular.ttf",
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _quebrar_linhas(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _ajustar_legenda(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    size_max: int = 96,
    size_min: int = 54,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Encolhe a fonte ate a legenda caber em ate 2 linhas dentro da tarja.

    Retorna (fonte, linhas, altura_da_linha). Se nem no tamanho minimo couber,
    trunca a ultima linha com reticencias: o molde nunca estoura o video.
    """
    for size in range(size_max, size_min - 1, -4):
        font = _font(size)
        line_height = int(size * 1.18)
        lines = _quebrar_linhas(draw, text, font, max_width)
        if len(lines) <= CAPTION_MAX_LINES and len(lines) * line_height <= max_height:
            return font, lines, line_height

    font = _font(size_min)
    line_height = int(size_min * 1.18)
    lines = _quebrar_linhas(draw, text, font, max_width)[:CAPTION_MAX_LINES]
    last = lines[-1]
    while last and draw.textlength(f"{last}...", font=font) > max_width:
        last = last[:-1].rstrip()
    lines[-1] = f"{last}..."
    return font, lines, line_height


def _desenhar_linhas_centralizadas(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    line_height: int,
    center_y: int,
    fill: tuple[int, int, int],
) -> None:
    block_height = len(lines) * line_height
    y = int(center_y - block_height / 2)
    for line in lines:
        width = draw.textlength(line, font=font)
        x = int((CANVAS_WIDTH - width) / 2)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def gerar_moldura(video_top: int, video_bottom: int, texts: MemeTextConfig) -> Image.Image:
    """Gera a imagem 1080x1920 de fundo com as tarjas ja preenchidas.

    video_top/video_bottom delimitam onde o video vai ficar; o texto e desenhado
    apenas nas faixas livres. Imagem estatica = um unico encode no render.
    """
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    max_text_width = CANVAS_WIDTH - 2 * MARGIN_X

    if texts.legenda and video_top > 80:
        caption = texts.legenda.strip().upper()
        if len(caption) > CAPTION_MAX_CHARS:
            caption = caption[:CAPTION_MAX_CHARS].rstrip() + "..."
        band_height = max(80, video_top - 48)
        font, lines, line_height = _ajustar_legenda(draw, caption, max_text_width, band_height)
        _desenhar_linhas_centralizadas(draw, lines, font, line_height, video_top // 2, CAPTION_COLOR)

    bottom_band_top = video_bottom
    bottom_band_height = CANVAS_HEIGHT - bottom_band_top
    if bottom_band_height > 80:
        entries: list[tuple[str, ImageFont.FreeTypeFont, tuple[int, int, int], int]] = []
        if texts.credito_streamer:
            size = 60
            entries.append((texts.credito_streamer.strip(), _font(size), CREATOR_COLOR, int(size * 1.25)))
        if texts.canal_proprio:
            size = 44
            entries.append((texts.canal_proprio.strip(), _font(size), CHANNEL_COLOR, int(size * 1.25)))
        block_height = sum(item[3] for item in entries)
        y = int(bottom_band_top + (bottom_band_height - block_height) / 2)
        for text, font, color, line_height in entries:
            width = draw.textlength(text, font=font)
            x = int((CANVAS_WIDTH - width) / 2)
            draw.text((x, y), text, font=font, fill=color)
            y += line_height

    return image


def _dimensoes_fit(source_w: int, source_h: int) -> tuple[int, int]:
    scale = min(CANVAS_WIDTH / source_w, CANVAS_HEIGHT / source_h)
    fit_w = max(2, int(source_w * scale))
    fit_h = max(2, int(source_h * scale))
    if fit_w % 2:
        fit_w -= 1
    if fit_h % 2:
        fit_h -= 1
    return fit_w, fit_h


def _desenhar_banner(draw, lines, font, line_height, center_y) -> None:
    """Banner branco arredondado com texto preto centralizado (estilo Futebol
    Respira). O banner acompanha a largura do maior texto."""
    widths = [draw.textlength(line, font=font) for line in lines]
    text_w = max(widths) if widths else 0
    text_h = line_height * len(lines)
    pad_x, pad_y = 34, 22
    box_w = min(CANVAS_WIDTH - 40, text_w + 2 * pad_x)
    box_h = text_h + 2 * pad_y
    x0 = (CANVAS_WIDTH - box_w) / 2
    y0 = center_y - box_h / 2
    radius = min(38, box_h / 2)
    draw.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=radius, fill=(255, 255, 255, 245))
    y = y0 + pad_y
    for line, w in zip(lines, widths):
        draw.text(((CANVAS_WIDTH - w) / 2, y), line, font=font, fill=(15, 15, 15, 255))
        y += line_height


def gerar_texto_overlay(texts: MemeTextConfig, top_center: int = 150, bottom_center: int = 1785) -> Image.Image:
    """Overlay 1080x1920 TRANSPARENTE no estilo Futebol Respira/GTA: banner branco
    com texto preto nas BANDAS PRETAS acima/abaixo do vídeo. Topo = hook viral
    GRANDE; rodapé = subtexto MENOR. Sem @ nem nome de canal."""
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    max_text_width = CANVAS_WIDTH - 2 * MARGIN_X - 40

    # Topo: hook viral GRANDE, na banda preta de cima (centro ~y150).
    if texts.legenda:
        caption = texts.legenda.strip().upper()
        if len(caption) > CAPTION_MAX_CHARS:
            caption = caption[:CAPTION_MAX_CHARS].rstrip() + "..."
        font, lines, line_height = _ajustar_legenda(draw, caption, max_text_width, 220)
        _desenhar_banner(draw, lines, font, line_height, top_center)

    # Rodapé: subtexto MENOR, na banda preta de baixo (centro ~y1785).
    sub = texts.subtexto or (" · ".join(t.strip() for t in (texts.credito_streamer, texts.canal_proprio) if t) or None)
    if sub:
        sub = sub.strip().upper()
        font, lines, line_height = _ajustar_legenda(draw, sub, max_text_width, 140)
        _desenhar_banner(draw, lines, font, line_height, bottom_center)

    return image


def renderizar_vertical_meme(
    input_path: str | Path,
    output_path: str | Path,
    texts: MemeTextConfig,
    preset: str = "medium",
) -> Path:
    """Render 9:16 (1080x1920): FUNDO = cópia ampliada/desfocada/escurecida do
    próprio vídeo (nunca tarja preta chapada); vídeo nítido por cima ocupando a
    largura útil (16:9 -> ~1080x608, sem distorção, preservando placar/bola/logos);
    título curto no topo e créditos no rodapé em área segura. Um único encode ffmpeg.
    """
    import subprocess

    import imageio_ffmpeg

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = VideoFileClip(str(input_path))
    try:
        src_w, src_h = source.size
        has_audio = source.audio is not None
        # Cap em 30fps: o Instagram Reels via API (rupload) rejeita 60fps com
        # ProcessingFailedError. 30fps é universalmente aceito (YouTube/IG/TikTok/Kwai).
        _fps_max = float(os.getenv("VERTICAL_MAX_FPS", "30"))
        fps = int(min(float(getattr(source, "fps", 30) or 30), _fps_max)) or 30
    finally:
        source.close()

    del src_w, src_h
    import os as _os
    # Vídeo GRANDE no meio (crop-to-fill na largura), com BANDA PRETA em cima e
    # embaixo para os textos (estilo Futebol Respira/GTA). Altura do vídeo
    # configurável; o resto do canvas fica preto.
    video_h = max(900, min(1920, int(_os.getenv("KWAI_VIDEO_HEIGHT", "1400"))))
    if video_h % 2:
        video_h -= 1
    vtop = (CANVAS_HEIGHT - video_h) // 2
    top_center = max(60, vtop // 2)
    bottom_center = min(CANVAS_HEIGHT - 60, vtop + video_h + (CANVAS_HEIGHT - vtop - video_h) // 2)
    overlay_png = output_path.with_name(output_path.stem + "_overlay.png")
    gerar_texto_overlay(texts, top_center, bottom_center).save(overlay_png)

    # Corta a borda pra TIRAR marca d'água/logo/nome do canal-fonte (a agência
    # Kwai reprova "reproduzido/marca d'água de outras redes"). Padrão maior (8%).
    b = max(0.0, min(0.18, float(_os.getenv("KWAI_LOGO_CROP", "0.08"))))
    crop_mn = f"crop=iw*{1-2*b:.3f}:ih*{1-2*b:.3f}:iw*{b:.3f}:ih*{b:.3f}," if b > 0 else ""
    # Fundo VERMELHO (padrão dos cortes aprovados na agência, tipo Futebol Respira),
    # não preto. Configurável por KWAI_BG_COLOR (hex RRGGBB).
    bg = (_os.getenv("KWAI_BG_COLOR", "ED1C24") or "ED1C24").lstrip("#")[:6] or "ED1C24"
    filtro = (
        f"[0:v]{crop_mn}scale=1080:{video_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop=1080:{video_h},setsar=1,"
        f"pad=1080:1920:0:{vtop}:0x{bg}[base];"
        "[base][1:v]overlay=0:0[vout]"
    )
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-i", str(input_path), "-i", str(overlay_png),
           "-filter_complex", filtro, "-map", "[vout]"]
    if has_audio:
        cmd += ["-map", "0:a", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-movflags", "+faststart", str(output_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    finally:
        overlay_png.unlink(missing_ok=True)
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera versao vertical 9:16 estilo meme de um corte pronto.")
    parser.add_argument("input", help="Arquivo do corte horizontal ja renderizado.")
    parser.add_argument("--legenda", default=None, help="Legenda clickbait da tarja de cima (vira CAIXA ALTA).")
    parser.add_argument("--credito", default=None, help="@ do streamer na tarja de baixo.")
    parser.add_argument(
        "--credito-canal",
        default=None,
        help="Canal proprio abaixo do credito do streamer. Sem esse valor, usa o default do --nicho.",
    )
    parser.add_argument(
        "--nicho",
        choices=sorted(CREDITO_CANAL_POR_NICHO),
        default=None,
        help="Nicho do corte, define o credito de canal padrao (ex.: football -> Futebol Respira).",
    )
    parser.add_argument("--saida", default=None, help="Arquivo de saida. Padrao: <input>_vertical.mp4 na mesma pasta.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.saida) if args.saida else input_path.with_name(f"{input_path.stem}_vertical.mp4")
    texts = MemeTextConfig(
        legenda=args.legenda,
        credito_streamer=args.credito,
        canal_proprio=credito_canal_para_nicho(args.nicho, args.credito_canal),
    )
    result = renderizar_vertical_meme(input_path, output_path, texts)
    print(f"Vertical meme finalizado: {result}")
