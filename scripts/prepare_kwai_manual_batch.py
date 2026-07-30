"""Prepara um lote pequeno de futebol real licenciado para postagem manual.

Baixa somente arquivos listados no manifesto interno, registra atribuição e
licença, renderiza 9:16 H.264/AAC e cria jobs `ready`. Nunca publica no Kwai.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

PROFILE = "kwai_cut_futebol"
OUTPUT_ROOT = Path(os.getenv("BOTLIVE_OUTPUT_ROOT", "/data/botlive/output"))
RUN_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")
READY_ROOT = OUTPUT_ROOT / "kwai_cut" / "ready" / RUN_DATE
SOURCE_ROOT = OUTPUT_ROOT / "kwai_cut" / "licensed_sources"
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

SOURCES: list[dict[str, Any]] = [
    {
        "key": "this-is-soccer",
        "name": "This is soccer",
        "page": "https://commons.wikimedia.org/wiki/File:This_is_soccer.webm",
        "download": "https://upload.wikimedia.org/wikipedia/commons/9/9a/This_is_soccer.webm",
        "license": "CC BY-SA 3.0",
        "author": "Evworo",
        "start": 0,
        "duration": 30,
        "event": "jogo-coletivo",
        "title": "A essência do futebol em cada toque",
    },
    {
        "key": "o-jogo-bonito",
        "name": "O Jogo Bonito",
        "page": "https://commons.wikimedia.org/wiki/File:O_Jogo_Bonito_(The_Beautiful_Game).webm",
        "download": "https://upload.wikimedia.org/wikipedia/commons/3/30/O_Jogo_Bonito_%28The_Beautiful_Game%29.webm",
        "license": "CC BY-SA 4.0",
        "author": "Sarah Samaha",
        "start": 20,
        "duration": 35,
        "event": "cultura-do-futebol",
        "title": "Por que chamam de jogo bonito?",
    },
    {
        "key": "primeiro-jogo-filmado",
        "name": "The world's first filmed soccer match",
        "page": "https://commons.wikimedia.org/wiki/File:The_world%E2%80%99s_first_filmed_soccer_match_with_corrected_speed-_Glentoran....webm",
        "download": "https://commons.wikimedia.org/wiki/Special:Redirect/file/The_world%E2%80%99s_first_filmed_soccer_match_with_corrected_speed-_Glentoran....webm",
        "license": "Public Domain Mark 1.0",
        "author": "obra histórica de 1897",
        "start": 0,
        "duration": 30,
        "event": "historia-do-futebol",
        "title": "O futebol filmado há mais de um século",
    },
]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def download(source: dict[str, Any]) -> Path:
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    target = SOURCE_ROOT / f"{source['key']}.webm"
    if not target.exists() or target.stat().st_size == 0:
        request = urllib.request.Request(source["download"], headers={"User-Agent": "BotLive/1.0 (licensed media preparation)"})
        with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    return target


def render(source_path: Path, target: Path, source: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[blur];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
        "[blur][front]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
    )
    run(
        "ffmpeg", "-y", "-ss", str(source["start"]), "-i", str(source_path),
        "-t", str(source["duration"]), "-filter_complex", filter_graph, "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(target),
    )


def cover(video: Path, target: Path, title: str) -> None:
    frame = target.with_suffix(".frame.jpg")
    run("ffmpeg", "-y", "-ss", "00:00:02", "-i", str(video), "-frames:v", "1", "-update", "1", str(frame))
    image = Image.open(frame).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((50, 80, 1030, 430), radius=30, fill=(0, 0, 0, 190))
    font = ImageFont.truetype(str(FONT), 68)
    words, lines, line = title.upper().split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) > 880 and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    y = 115
    for text in lines[:3]:
        draw.text((90, y), text, font=font, fill="white", stroke_width=2, stroke_fill="black")
        y += 88
    image.save(target, quality=92)
    frame.unlink(missing_ok=True)


def probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-show_entries", "stream=codec_name,width,height", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(completed.stdout)
    video = next(stream for stream in data["streams"] if stream.get("width"))
    audio = next((stream for stream in data["streams"] if not stream.get("width")), {})
    return {
        "duration": float(data["format"]["duration"]),
        "filesize": int(data["format"]["size"]),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
    }


def one(rows: Any) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("Registro obrigatório não encontrado")
    return rows[0]


def main() -> None:
    if os.getenv("KWAI_API_ENABLED", "0") != "0":
        raise RuntimeError("KWAI_API_ENABLED deve permanecer 0")
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    destination = one(client.table("profile_destinations").select("id,account_id").eq("profile_id", PROFILE).eq("platform", "kwai").execute().data)

    for index, source in enumerate(SOURCES, start=1):
        source_path = download(source)
        filename = f"kwai-futebol-{source['event']}-{RUN_DATE}-{index:03d}.mp4"
        video = READY_ROOT / filename
        cover_path = READY_ROOT / filename.replace(".mp4", "-capa.jpg")
        if not video.exists():
            render(source_path, video, source)
        if not cover_path.exists():
            cover(video, cover_path, source["title"])
        info = probe(video)
        errors = []
        if (info["width"], info["height"]) != (1080, 1920):
            errors.append("resolution")
        if info["codec"] != "h264" or info["audio_codec"] != "aac":
            errors.append("codec")
        if not 5 <= info["duration"] <= 60:
            errors.append("duration")
        sha256 = hashlib.sha256(video.read_bytes()).hexdigest()

        client.table("football_sources").upsert({
            "profile_id": PROFILE, "name": source["name"], "source_type": "authorized_feed",
            "source_ref": source["page"], "usage_status": "licensed", "enabled": True,
            "priority": 90 - index, "status": "ready", "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None, "metrics": {"license": source["license"], "author": source["author"], "source": "Wikimedia Commons"},
        }, on_conflict="profile_id,source_type,source_ref").execute()

        event = one(client.table("content_events").upsert({
            "profile_id": PROFILE, "source_event_key": f"manual-mobile:{source['key']}:{RUN_DATE}",
            "source_ref": source["page"], "timestamp_seconds": float(source["start"]),
            "event_type": source["event"], "metadata": {
                "confidence": 1.0, "viral_score": 0.5, "football_real": True,
                "license": source["license"], "author": source["author"], "modified": True,
            },
        }, on_conflict="profile_id,source_event_key").execute().data)
        variant = one(client.table("editorial_variants").upsert({
            "event_id": event["event_id"], "profile_id": PROFILE, "strategy": "cut",
            "variant_signature": f"manual-mobile-v1:{source['key']}",
            "editorial_metadata": {"format": "9:16", "headline": source["title"], "license": source["license"]},
        }, on_conflict="profile_id,event_id,variant_signature").execute().data)
        asset = one(client.table("media_assets").upsert({
            "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "path": str(video), "sha256": sha256, "duration": info["duration"], "width": info["width"],
            "height": info["height"], "aspect_ratio": "9:16", "codec": info["codec"],
            "audio_codec": info["audio_codec"], "filesize": info["filesize"],
            "validation_status": "invalid" if errors else "valid", "validation_errors": errors,
        }, on_conflict="profile_id,variant_id,sha256").execute().data)
        caption = (
            f"{source['title']}\n\n"
            f"Fonte: {source['author']} · Wikimedia Commons · {source['license']}. "
            "Conteúdo adaptado para formato vertical."
        )
        client.table("publication_jobs").upsert({
            "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "asset_id": asset["asset_id"], "destination_id": destination["id"], "platform": "kwai",
            "account_id": destination["account_id"], "status": "ready" if not errors else "rejected",
            "publication_key": f"kwai:{sha256}", "title": source["title"], "caption": caption,
            "cover_path": str(cover_path), "metadata": {
                "publication_mode": "prepare_only", "publication_method": "manual_mobile",
                "download_filename": filename, "license": source["license"], "source_url": source["page"],
            },
        }, on_conflict="publication_key").execute()
        print(json.dumps({"file": str(video), "status": "ready" if not errors else "rejected", **info}, ensure_ascii=False))


if __name__ == "__main__":
    main()

