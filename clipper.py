from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional
import numpy as np
from PIL import Image
from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func
from runtime_paths import (
    cache_dir,
    cortes_dir,
    ensure_output_dirs,
    live_blocks_dir,
    live_preview_dir,
    temp_dir,
)
from ytdlp_config import com_opcoes_env

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

try:
    from moviepy.editor import ColorClip, CompositeVideoClip, VideoFileClip
except ImportError:  # MoviePy 2.x
    from moviepy import ColorClip, CompositeVideoClip, VideoFileClip


OutputLayout = Literal["original", "vertical-fit", "vertical-crop"]


@dataclass(frozen=True)
class VideoValidationResult:
    valid: bool
    reason: str
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    has_video: bool = False
    has_audio: bool = False
    file_size_bytes: int = 0


def preparar_pastas() -> None:
    ensure_output_dirs()
    os.environ["TMP"] = str(temp_dir())
    os.environ["TEMP"] = str(temp_dir())
    os.environ["TMPDIR"] = str(temp_dir())


def limpar_cache() -> None:
    cache_dir().mkdir(parents=True, exist_ok=True)
    for item in cache_dir().iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def limpar_arquivos_gerados() -> None:
    preparar_pastas()
    for path in cortes_dir().glob("*.mp4"):
        path.unlink(missing_ok=True)
    blocks_dir = live_blocks_dir()
    if blocks_dir.exists():
        for item in blocks_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)


def _find_downloaded_video(work_dir: Path) -> Path:
    candidates = [
        path
        for path in work_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not candidates:
        raise FileNotFoundError("yt-dlp nao gerou nenhum arquivo de video no cache.")
    return max(candidates, key=lambda path: path.stat().st_size)


def _format_selector(target_height: Optional[int]) -> str:
    height = int(target_height or 720)
    return (
        f"bv*[vcodec^=avc1][height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[vcodec^=avc1][height<={height}][ext=mp4]/"
        f"b[height<={height}][ext=mp4]/"
        f"best[height<={height}]/best"
    )


def baixar_trecho(
    video_url: str,
    peak_timestamp: int,
    clip_id: str,
    seconds_before: int = 30,
    seconds_after: int = 30,
    limpar_cache_antes: bool = True,
    target_height: Optional[int] = None,
) -> tuple[Path, bool]:
    """Baixa o trecho [peak-before, peak+after] do VOD.

    Retorna (arquivo, precise). precise=True significa corte exato por
    re-encode do yt-dlp (force_keyframes_at_cuts): o arquivo JA E o corte
    final e nao precisa de novo encode para layout original.
    """
    preparar_pastas()
    if limpar_cache_antes:
        limpar_cache()

    start = max(0, int(peak_timestamp) - seconds_before)
    end = int(peak_timestamp) + seconds_after
    work_dir = cache_dir() / f"job_{clip_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": _format_selector(target_height),
        "outtmpl": str(work_dir / "raw_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "paths": {"home": str(work_dir), "temp": str(temp_dir())},
    }

    print(
        "[download-range] "
        f"timestamp={peak_timestamp}s start={start}s end={end}s "
        f"target_height={target_height or 'best'} "
        f"etapa=yt-dlp_range comando=yt-dlp --download-sections '*{start}-{end}' "
        f"--output \"{work_dir / 'raw_%(id)s.%(ext)s'}\" continuou=em_execucao"
    )
    precise = True
    try:
        with YoutubeDL(com_opcoes_env(ydl_opts)) as ydl:
            ydl.download([video_url])
    except Exception as exc:
        print(
            "[download-range][falha] "
            f"timestamp={peak_timestamp}s etapa=yt-dlp_range motivo={exc} "
            "comando=yt-dlp_range_precise continuou=tentando_fallback"
        )
        precise = False
        fallback_opts = dict(ydl_opts)
        fallback_opts["force_keyframes_at_cuts"] = False
        fallback_opts.pop("paths", None)
        fallback_opts["quiet"] = False
        with YoutubeDL(com_opcoes_env(fallback_opts)) as ydl:
            ydl.download([video_url])

    return _find_downloaded_video(work_dir), precise


def _write_clip(clip: VideoFileClip, output_path: Path, preset: str = "medium") -> None:
    kwargs: dict[str, Any] = {
        "codec": "libx264",
        "fps": min(float(getattr(clip, "fps", 30) or 30), 60),
        "preset": preset,
        "threads": os.cpu_count() or 4,
        "verbose": False,
        "logger": None,
    }
    if clip.audio is not None:
        kwargs["audio_codec"] = "aac"
        kwargs["temp_audiofile"] = str(temp_dir() / f"{output_path.stem}_audio.m4a")
        kwargs["remove_temp"] = True
    else:
        kwargs["audio"] = False
    clip.write_videofile(str(output_path), **kwargs)


def _aplicar_layout_em_clip(
    clip: VideoFileClip,
    output_layout: OutputLayout,
    focus_x: float = 0.5,
    target_width: int = 1080,
    target_height: int = 1920,
) -> tuple[VideoFileClip, list]:
    """Aplica o layout sobre um clip aberto, SEM escrever arquivo.

    Retorna (clip_final, clips_auxiliares_para_fechar). E o coracao da
    passada unica: corte + layout viram um unico write_videofile no chamador.
    """
    if output_layout == "original":
        return clip, []

    if output_layout == "vertical-fit":
        source_w, source_h = clip.size
        scale = min(target_width / source_w, target_height / source_h)
        fit_w = max(2, int(source_w * scale))
        fit_h = max(2, int(source_h * scale))
        if fit_w % 2:
            fit_w -= 1
        if fit_h % 2:
            fit_h -= 1
        resized = clip.resize((fit_w, fit_h))
        background = ColorClip(size=(target_width, target_height), color=(0, 0, 0)).set_duration(clip.duration)
        fitted = CompositeVideoClip([background, resized.set_position("center")], size=(target_width, target_height))
        if clip.audio is not None:
            fitted = fitted.set_audio(clip.audio)
        return fitted, [resized, background]

    if output_layout == "vertical-crop":
        focus_x = min(1.0, max(0.0, focus_x))
        source_w, source_h = clip.size
        target_ratio = target_width / target_height
        source_ratio = source_w / source_h
        if source_ratio > target_ratio:
            crop_h = source_h
            crop_w = int(crop_h * target_ratio)
            x1 = int((source_w - crop_w) * focus_x)
            y1 = 0
        else:
            crop_w = source_w
            crop_h = int(crop_w / target_ratio)
            x1 = 0
            y1 = max(0, int((source_h - crop_h) / 2))
        x2 = min(source_w, x1 + crop_w)
        y2 = min(source_h, y1 + crop_h)
        vertical = clip.crop(x1=x1, y1=y1, x2=x2, y2=y2).resize((target_width, target_height))
        return vertical, []

    raise ValueError(f"Layout invalido: {output_layout}")


def _render_com_layout(
    clip: VideoFileClip,
    output_path: Path,
    output_layout: OutputLayout,
    focus_x: float = 0.5,
    preset: str = "medium",
) -> None:
    """Um unico encode: aplica o layout no clip aberto e escreve o arquivo."""
    final, extras = _aplicar_layout_em_clip(clip, output_layout, focus_x)
    try:
        _write_clip(final, output_path, preset=preset)
    finally:
        if final is not clip:
            final.close()
        for item in extras:
            try:
                item.close()
            except Exception:
                pass


def renderizar_layout(
    input_path: str | Path,
    output_path: str | Path,
    output_layout: OutputLayout = "original",
    focus_x: float = 0.5,
) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)
    clip = VideoFileClip(str(input_path))
    try:
        _render_com_layout(clip, output_path, output_layout, focus_x=focus_x)
    finally:
        clip.close()
    return output_path


def aplicar_vertical_fit(input_path: Path, output_path: Path, **_ignored) -> None:
    renderizar_layout(input_path, output_path, output_layout="vertical-fit")


def aplicar_crop_vertical(input_path: Path, output_path: Path, focus_x: float = 0.5, **_ignored) -> None:
    renderizar_layout(input_path, output_path, output_layout="vertical-crop", focus_x=focus_x)


def _video_has_audio(path: Path) -> bool:
    try:
        clip = VideoFileClip(str(path))
        try:
            return clip.audio is not None
        finally:
            clip.close()
    except Exception:
        return False


def _frame_is_blank_or_bad(frame: np.ndarray) -> bool:
    arr = frame.astype(np.float32)
    brightness = float(np.mean(arr))
    contrast = float(np.std(arr))
    red = float(np.mean(arr[:, :, 0]))
    green = float(np.mean(arr[:, :, 1]))
    blue = float(np.mean(arr[:, :, 2]))
    purple_dominance = red > green * 1.35 and blue > green * 1.35 and (red + blue) / 2 > 55
    return (brightness < 10 and contrast < 8) or contrast < 3 or purple_dominance


def validar_video_final(
    output_path: str | Path,
    require_audio: bool = False,
    min_duration_seconds: float = 5.0,
    min_size_bytes: int = 100_000,
) -> VideoValidationResult:
    output_path = Path(output_path)
    if not output_path.exists():
        return VideoValidationResult(False, "arquivo nao existe")

    file_size = output_path.stat().st_size
    if file_size < min_size_bytes:
        return VideoValidationResult(False, f"arquivo muito pequeno ({file_size} bytes)", file_size_bytes=file_size)

    try:
        clip = VideoFileClip(str(output_path))
    except Exception as exc:
        return VideoValidationResult(False, f"falha ao abrir video: {exc}", file_size_bytes=file_size)

    try:
        duration = float(clip.duration or 0)
        width, height = [int(value) for value in clip.size]
        has_audio = clip.audio is not None
        if duration <= min_duration_seconds:
            return VideoValidationResult(False, f"duracao menor que {min_duration_seconds}s", duration, width, height, True, has_audio, file_size)
        if width <= 0 or height <= 0:
            return VideoValidationResult(False, "resolucao invalida", duration, width, height, True, has_audio, file_size)
        if require_audio and not has_audio:
            return VideoValidationResult(False, "audio ausente no arquivo final", duration, width, height, True, has_audio, file_size)

        sample_count = min(6, max(3, int(duration // 8) + 1))
        timestamps = np.linspace(0.5, max(0.5, duration - 0.5), sample_count)
        bad_frames = 0
        for timestamp in timestamps:
            try:
                frame = clip.get_frame(float(timestamp))
            except Exception:
                bad_frames += 1
                continue
            if _frame_is_blank_or_bad(frame):
                bad_frames += 1

        if bad_frames >= max(2, int(sample_count * 0.8)):
            return VideoValidationResult(False, "video parece blank/preto/roxo", duration, width, height, True, has_audio, file_size)
        return VideoValidationResult(True, "ok", duration, width, height, True, has_audio, file_size)
    finally:
        clip.close()


def criar_corte_vertical_de_arquivo(
    input_video_path: str | Path,
    peak_timestamp: int,
    clip_id: str,
    seconds_before: int = 30,
    seconds_after: int = 30,
    focus_x: float = 0.5,
    overlay_config: Optional[Any] = None,
    output_layout: OutputLayout = "vertical-crop",
    keep_intermediate: bool = False,
) -> Path:
    preparar_pastas()
    input_video_path = Path(input_video_path)
    output_path = cortes_dir() / f"corte_{clip_id}.mp4"

    # Passada unica: subclip -> layout -> um write_videofile. O antigo arquivo
    # de segmento intermediario era um encode extra que so degradava qualidade.
    source = VideoFileClip(str(input_video_path))
    try:
        start = max(0, int(peak_timestamp) - seconds_before)
        end = min(float(source.duration), int(peak_timestamp) + seconds_after)
        if end <= start:
            raise ValueError(f"Janela invalida para corte: start={start}, end={end}")

        segment = source.subclip(start, end)
        try:
            _render_com_layout(segment, output_path, output_layout, focus_x=focus_x)
        finally:
            segment.close()
    finally:
        source.close()

    if overlay_config and getattr(overlay_config, "enabled", False):
        from overlay_editor import aplicar_overlay_no_video

        final_path = aplicar_overlay_no_video(output_path, overlay_config)
        if not keep_intermediate and final_path != output_path:
            output_path.unlink(missing_ok=True)
        return final_path
    return output_path


def criar_preview_de_arquivo(
    input_video_path: str | Path,
    peak_timestamp: int,
    preview_id: str,
    seconds_before: int = 12,
    seconds_after: int = 33,
    output_layout: OutputLayout = "original",
) -> Path:
    output_path = criar_corte_vertical_de_arquivo(
        input_video_path=input_video_path,
        peak_timestamp=peak_timestamp,
        clip_id=f"preview_{preview_id}",
        seconds_before=seconds_before,
        seconds_after=seconds_after,
        output_layout=output_layout,
        keep_intermediate=False,
    )
    live_preview_dir().mkdir(parents=True, exist_ok=True)
    target_path = live_preview_dir() / output_path.name
    if target_path.exists():
        target_path.unlink()
    output_path.replace(target_path)
    return target_path


def criar_corte_vertical(
    video_url: str,
    peak_timestamp: int,
    clip_id: str,
    seconds_before: int = 30,
    seconds_after: int = 30,
    focus_x: float = 0.5,
    overlay_config: Optional[Any] = None,
    limpar_cache_antes: bool = True,
    limpar_cache_depois: bool = True,
    output_layout: OutputLayout = "vertical-crop",
    keep_intermediate: bool = False,
    target_height: Optional[int] = None,
) -> Path:
    preparar_pastas()
    output_path = cortes_dir() / f"corte_{clip_id}.mp4"

    try:
        input_path, precise = baixar_trecho(
            video_url=video_url,
            peak_timestamp=peak_timestamp,
            clip_id=clip_id,
            seconds_before=seconds_before,
            seconds_after=seconds_after,
            limpar_cache_antes=limpar_cache_antes,
            target_height=target_height,
        )
        if output_layout == "original" and precise:
            # O trecho baixado com force_keyframes_at_cuts JA E o corte exato:
            # re-encodar aqui so degradava a imagem e dobrava o tempo.
            if output_path.exists():
                output_path.unlink()
            shutil.move(str(input_path), str(output_path))
            print(f"[render] layout original sem re-encode: trecho yt-dlp movido para {output_path.name}")
        else:
            renderizar_layout(input_path, output_path, output_layout=output_layout, focus_x=focus_x)
        if overlay_config and getattr(overlay_config, "enabled", False):
            from overlay_editor import aplicar_overlay_no_video

            final_path = aplicar_overlay_no_video(output_path, overlay_config)
            if not keep_intermediate and final_path != output_path:
                output_path.unlink(missing_ok=True)
            return final_path
        return output_path
    finally:
        if limpar_cache_depois:
            limpar_cache()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Baixa trecho e renderiza corte vertical 9:16.")
    parser.add_argument("url", help="URL do video/live.")
    parser.add_argument("timestamp", type=int, help="Timestamp do pico em segundos.")
    parser.add_argument("--id", default="teste", help="ID usado no nome final do corte.")
    args = parser.parse_args()

    path = criar_corte_vertical(args.url, args.timestamp, args.id)
    print(f"Corte finalizado: {path}")
