from __future__ import annotations

import argparse
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
    credito_streamer: Optional[str] = None
    canal_proprio: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return any([self.legenda, self.credito_streamer, self.canal_proprio])


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


def renderizar_vertical_meme(
    input_path: str | Path,
    output_path: str | Path,
    texts: MemeTextConfig,
    preset: str = "medium",
) -> Path:
    """Renderiza a versao 9:16 estilo meme: video inteiro no centro, tarjas com texto.

    O video NUNCA e cortado (facecam e HUD preservados). Fundo com texto e uma
    imagem estatica, entao o custo e um unico encode do corte (30-40s).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = VideoFileClip(str(input_path))
    resized = None
    background = None
    composed = None
    try:
        fit_w, fit_h = _dimensoes_fit(*source.size)
        video_top = (CANVAS_HEIGHT - fit_h) // 2
        video_bottom = video_top + fit_h

        frame = np.asarray(gerar_moldura(video_top, video_bottom, texts))
        background = ImageClip(frame).set_duration(source.duration)
        resized = source.resize((fit_w, fit_h))
        composed = CompositeVideoClip(
            [background, resized.set_position("center")],
            size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        )
        if source.audio is not None:
            composed = composed.set_audio(source.audio)

        kwargs: dict[str, Any] = {
            "codec": "libx264",
            "fps": min(float(getattr(source, "fps", 30) or 30), 60),
            "preset": preset,
            "verbose": False,
            "logger": None,
        }
        if source.audio is not None:
            kwargs["audio_codec"] = "aac"
            kwargs["temp_audiofile"] = str(output_path.with_name(f"{output_path.stem}_temp_audio.m4a"))
            kwargs["remove_temp"] = True
        else:
            kwargs["audio"] = False
        composed.write_videofile(str(output_path), **kwargs)
    finally:
        for clip in (composed, resized, background):
            if clip is not None and clip is not source:
                try:
                    clip.close()
                except Exception:
                    pass
        source.close()
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
