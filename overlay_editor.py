from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from moviepy.editor import VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import VideoFileClip


@dataclass(frozen=True)
class OverlayConfig:
    title: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    cta: Optional[str] = None
    cta_seconds: int = 4

    @property
    def enabled(self) -> bool:
        return any([self.title, self.description, self.brand, self.cta])


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _draw_centered_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    image_width: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] = (255, 255, 255),
    box_fill: tuple[int, int, int, int] = (0, 0, 0, 165),
) -> None:
    if not text:
        return
    margin_x = 44
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(margin_x, int((image_width - text_w) / 2))
    box = [x - 24, y - 16, min(image_width - margin_x, x + text_w + 24), y + text_h + 22]
    draw.rounded_rectangle(box, radius=18, fill=box_fill)
    draw.text((x, y), text, font=font, fill=fill)


def _overlay_frame(frame: np.ndarray, t: float, duration: float, config: OverlayConfig) -> np.ndarray:
    image = Image.fromarray(frame)
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    if config.title:
        _draw_centered_box(draw, config.title[:42], 78, width, _font(58))
    if config.description:
        _draw_centered_box(draw, config.description[:58], 156, width, _font(34), fill=(255, 235, 120))
    if config.brand:
        brand_font = _font(30)
        draw.rounded_rectangle([34, height - 138, 34 + 420, height - 84], radius=16, fill=(0, 0, 0, 145))
        draw.text((56, height - 124), config.brand[:28], font=brand_font, fill=(255, 255, 255))
    if config.cta and t >= max(0, duration - config.cta_seconds):
        _draw_centered_box(draw, config.cta[:44], height - 260, width, _font(46), fill=(255, 255, 255), box_fill=(220, 40, 40, 190))

    return np.asarray(image)


def aplicar_overlay_no_video(
    input_path: str | Path,
    config: OverlayConfig,
    output_path: Optional[str | Path] = None,
) -> Path:
    input_path = Path(input_path)
    if not config.enabled:
        return input_path

    output = Path(output_path) if output_path else input_path.with_name(f"{input_path.stem}_final{input_path.suffix}")
    clip = VideoFileClip(str(input_path))
    try:
        duration = float(clip.duration or 0)
        edited = clip.fl(lambda gf, t: _overlay_frame(gf(t), t, duration, config))
        try:
            edited.write_videofile(
                str(output),
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="medium",
                verbose=False,
                logger=None,
            )
        finally:
            edited.close()
    finally:
        clip.close()
    return output
