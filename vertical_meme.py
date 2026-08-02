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
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1080
VIDEO_TOP = 360
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
    if override:
        return override
    if nicho:
        return CREDITO_CANAL_POR_NICHO.get(nicho)
    return None


@dataclass(frozen=True)
class MemeTextConfig:
    """Textos das tarjas do layout vertical social.

    legenda: titulo chamativo na faixa superior, em caixa alta.
    credito_streamer: primeira linha da faixa inferior.
    canal_proprio: segunda linha da faixa inferior.
    """

    legenda: Optional[str] = None
    credito_streamer: Optional[str] = None
    canal_proprio: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return any([self.legenda, self.credito_streamer, self.canal_proprio])


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        FONTS_DIR / "Anton-Regular.ttf",
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _quebrar_linhas(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
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
    for size in range(size_max, size_min - 1, -4):
        font = _font(size)
        line_height = int(size * 1.18)
        lines = _quebrar_linhas(draw, text, font, max_width)
        if len(lines) <= CAPTION_MAX_LINES and len(lines) * line_height <= max_height:
            return font, lines, line_height

    font = _font(size_min)
    line_height = int(size_min * 1.18)
    lines = _quebrar_linhas(draw, text, font, max_width)[:CAPTION_MAX_LINES]
    if not lines:
        return font, [""], line_height
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
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    max_text_width = CANVAS_WIDTH - 2 * MARGIN_X

    if texts.legenda and video_top > 80:
        caption = texts.legenda.strip().upper()
        if len(caption) > CAPTION_MAX_CHARS:
            caption = caption[:CAPTION_MAX_CHARS].rstrip() + "..."
        band_height = max(80, video_top - 48)
        font, lines, line_height = _ajustar_legenda(
            draw,
            caption,
            max_text_width,
            band_height,
        )
        _desenhar_linhas_centralizadas(
            draw,
            lines,
            font,
            line_height,
            video_top // 2,
            CAPTION_COLOR,
        )

    bottom_band_height = CANVAS_HEIGHT - video_bottom
    if bottom_band_height > 80:
        entries: list[tuple[str, ImageFont.FreeTypeFont, tuple[int, int, int], int]] = []
        if texts.credito_streamer:
            size = 60
            entries.append(
                (
                    texts.credito_streamer.strip(),
                    _font(size),
                    CREATOR_COLOR,
                    int(size * 1.25),
                )
            )
        if texts.canal_proprio:
            size = 44
            entries.append(
                (
                    texts.canal_proprio.strip(),
                    _font(size),
                    CHANNEL_COLOR,
                    int(size * 1.25),
                )
            )
        block_height = sum(item[3] for item in entries)
        y = int(video_bottom + (bottom_band_height - block_height) / 2)
        for text, font, color, line_height in entries:
            width = draw.textlength(text, font=font)
            x = int((CANVAS_WIDTH - width) / 2)
            draw.text((x, y), text, font=font, fill=color)
            y += line_height

    return image


def _resize_cover_square(source: VideoFileClip):
    """Amplia e recorta pelo centro para preencher 1080x1080.

    Antes o vídeo 16:9 era apenas encaixado e ficava com cerca de 608 px de
    altura no canvas 9:16. Agora ele ocupa uma janela quadrada de largura total,
    como nos Shorts/Reels de referência. O crop é central e nunca deforma.
    """
    source_w, source_h = source.size
    scale = max(VIDEO_WIDTH / source_w, VIDEO_HEIGHT / source_h)
    resized_w = max(VIDEO_WIDTH, int(round(source_w * scale)))
    resized_h = max(VIDEO_HEIGHT, int(round(source_h * scale)))
    if resized_w % 2:
        resized_w += 1
    if resized_h % 2:
        resized_h += 1

    resized = source.resize((resized_w, resized_h))
    x_center = resized_w / 2
    y_center = resized_h / 2
    cropped = resized.crop(
        x_center=x_center,
        y_center=y_center,
        width=VIDEO_WIDTH,
        height=VIDEO_HEIGHT,
    )
    return resized, cropped


def renderizar_vertical_meme(
    input_path: str | Path,
    output_path: str | Path,
    texts: MemeTextConfig,
    preset: str = "medium",
) -> Path:
    """Renderiza 1080x1920 com título, vídeo grande quadrado e faixa inferior.

    O arquivo final continua 9:16 para Shorts, Reels, TikTok e Kwai. O vídeo
    horizontal passa a preencher 1080x1080 por recorte central, evitando a
    miniatura pequena no meio da tela.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = VideoFileClip(str(input_path))
    resized = None
    cropped = None
    background = None
    composed = None
    try:
        video_top = VIDEO_TOP
        video_bottom = VIDEO_TOP + VIDEO_HEIGHT
        resized, cropped = _resize_cover_square(source)

        frame = np.asarray(gerar_moldura(video_top, video_bottom, texts))
        background = ImageClip(frame).set_duration(source.duration)
        composed = CompositeVideoClip(
            [background, cropped.set_position((0, video_top))],
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
            kwargs["temp_audiofile"] = str(
                output_path.with_name(f"{output_path.stem}_temp_audio.m4a")
            )
            kwargs["remove_temp"] = True
        else:
            kwargs["audio"] = False
        composed.write_videofile(str(output_path), **kwargs)
    finally:
        for clip in (composed, cropped, resized, background):
            if clip is not None and clip is not source:
                try:
                    clip.close()
                except Exception:
                    pass
        source.close()
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gera versão vertical 9:16 com vídeo grande, título e créditos."
    )
    parser.add_argument("input", help="Arquivo do corte horizontal já renderizado.")
    parser.add_argument(
        "--legenda",
        default=None,
        help="Título chamativo da faixa superior (vira CAIXA ALTA).",
    )
    parser.add_argument("--credito", default=None, help="@ do streamer na faixa inferior.")
    parser.add_argument(
        "--credito-canal",
        default=None,
        help="Canal próprio abaixo do crédito. Sem valor, usa o padrão do nicho.",
    )
    parser.add_argument(
        "--nicho",
        choices=sorted(CREDITO_CANAL_POR_NICHO),
        default=None,
        help="Nicho do corte, define o crédito de canal padrão.",
    )
    parser.add_argument(
        "--saida",
        default=None,
        help="Arquivo de saída. Padrão: <input>_vertical.mp4.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = (
        Path(args.saida)
        if args.saida
        else input_path.with_name(f"{input_path.stem}_vertical.mp4")
    )
    texts = MemeTextConfig(
        legenda=args.legenda,
        credito_streamer=args.credito,
        canal_proprio=credito_canal_para_nicho(args.nicho, args.credito_canal),
    )
    result = renderizar_vertical_meme(input_path, output_path, texts)
    print(f"Vertical social finalizado: {result}")
