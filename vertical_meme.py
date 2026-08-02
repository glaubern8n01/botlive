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
VIDEO_TOP = 330
MARGIN_X = 58
BACKGROUND_COLOR = (10, 10, 10)
TITLE_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (255, 255, 255)
TITLE_MAX_CHARS = 78
SUBTITLE_MAX_CHARS = 110
FONTS_DIR = Path(__file__).resolve().parent / "fonts"


@dataclass(frozen=True)
class MemeTextConfig:
    """Textos do layout Shorts/Reels/TikTok.

    title: chamada curta na faixa superior.
    subtitle: complemento do próprio lance na faixa inferior.
    Os campos antigos são aceitos apenas por compatibilidade; nome de canal e
    crédito não são desenhados no vídeo.
    """

    title: Optional[str] = None
    subtitle: Optional[str] = None
    legenda: Optional[str] = None
    credito_streamer: Optional[str] = None
    canal_proprio: Optional[str] = None

    @property
    def resolved_title(self) -> Optional[str]:
        return self.title or self.legenda

    @property
    def enabled(self) -> bool:
        return bool(self.resolved_title or self.subtitle)


def credito_canal_para_nicho(nicho: Optional[str], override: Optional[str] = None) -> Optional[str]:
    """Mantido para não quebrar chamadas antigas; não aparece mais no vídeo."""
    return override


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


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
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


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    max_lines: int,
    size_max: int,
    size_min: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(size_max, size_min - 1, -3):
        font = _font(size)
        line_height = int(size * 1.18)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines and len(lines) * line_height <= max_height:
            return font, lines, line_height

    font = _font(size_min)
    line_height = int(size_min * 1.18)
    lines = _wrap(draw, text, font, max_width)[:max_lines] or [""]
    last = lines[-1]
    while last and draw.textlength(f"{last}...", font=font) > max_width:
        last = last[:-1].rstrip()
    lines[-1] = f"{last}..." if last else ""
    return font, lines, line_height


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font,
    line_height: int,
    center_y: int,
    fill: tuple[int, int, int],
) -> None:
    y = int(center_y - (len(lines) * line_height) / 2)
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text(((CANVAS_WIDTH - width) / 2, y), line, font=font, fill=fill)
        y += line_height


def gerar_moldura(texts: MemeTextConfig) -> Image.Image:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    max_width = CANVAS_WIDTH - 2 * MARGIN_X

    title = (texts.resolved_title or "").strip().upper()
    if title:
        title = title[:TITLE_MAX_CHARS].rstrip()
        font, lines, line_height = _fit_text(
            draw, title, max_width, VIDEO_TOP - 30, 2, 96, 54
        )
        _draw_centered(draw, lines, font, line_height, VIDEO_TOP // 2, TITLE_COLOR)

    subtitle = (texts.subtitle or "").strip().upper()
    if subtitle:
        subtitle = subtitle[:SUBTITLE_MAX_CHARS].rstrip()
        lower_top = VIDEO_TOP + VIDEO_HEIGHT
        lower_height = CANVAS_HEIGHT - lower_top
        # Reserva margem inferior para os controles de Reels/TikTok/Kwai.
        center_y = lower_top + int(lower_height * 0.40)
        font, lines, line_height = _fit_text(
            draw, subtitle, max_width, int(lower_height * 0.62), 3, 76, 42
        )
        _draw_centered(draw, lines, font, line_height, center_y, SUBTITLE_COLOR)

    return image


def _resize_cover_square(source: VideoFileClip):
    """Preenche 1080x1080 sem deformar, com recorte central."""
    source_w, source_h = source.size
    scale = max(VIDEO_WIDTH / source_w, VIDEO_HEIGHT / source_h)
    resized_w = max(VIDEO_WIDTH, int(round(source_w * scale)))
    resized_h = max(VIDEO_HEIGHT, int(round(source_h * scale)))
    resized_w += resized_w % 2
    resized_h += resized_h % 2
    resized = source.resize((resized_w, resized_h))
    cropped = resized.crop(
        x_center=resized_w / 2,
        y_center=resized_h / 2,
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
    """Renderiza 1080x1920 com vídeo grande, título e subtítulo."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = VideoFileClip(str(input_path))
    resized = cropped = background = composed = None
    try:
        resized, cropped = _resize_cover_square(source)
        frame = np.asarray(gerar_moldura(texts))
        background = ImageClip(frame).set_duration(source.duration)
        composed = CompositeVideoClip(
            [background, cropped.set_position((0, VIDEO_TOP))],
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
            kwargs.update(
                audio_codec="aac",
                temp_audiofile=str(
                    output_path.with_name(f"{output_path.stem}_temp_audio.m4a")
                ),
                remove_temp=True,
            )
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
    parser = argparse.ArgumentParser(description="Gera vídeo vertical social 9:16.")
    parser.add_argument("input")
    parser.add_argument("--titulo", "--legenda", dest="titulo", default=None)
    parser.add_argument("--subtitulo", default=None)
    parser.add_argument("--saida", default=None)
    parser.add_argument("--credito", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--credito-canal", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--nicho", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.saida) if args.saida else input_path.with_name(
        f"{input_path.stem}_vertical.mp4"
    )
    result = renderizar_vertical_meme(
        input_path,
        output_path,
        MemeTextConfig(title=args.titulo, subtitle=args.subtitulo),
    )
    print(f"Vertical social finalizado: {result}")
