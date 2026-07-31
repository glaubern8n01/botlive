"""Gera lote v2 licenciado com áudio audível, headline e legendas queimadas."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kwai_media_validation import analyze_audio, required_text_gates

PROFILE = "kwai_cut_futebol"
OUTPUT_ROOT = Path(os.getenv("BOTLIVE_OUTPUT_ROOT", "/data/botlive/output"))
RUN_DATE = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d")
READY_ROOT = OUTPUT_ROOT / "kwai_cut" / "ready" / RUN_DATE
SOURCE_ROOT = OUTPUT_ROOT / "kwai_cut" / "licensed_sources"
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

SOURCES: list[dict[str, Any]] = [
    {
        "key": "this-is-soccer", "name": "This is soccer",
        "page": "https://commons.wikimedia.org/wiki/File:This_is_soccer.webm",
        "download": "https://upload.wikimedia.org/wikipedia/commons/9/9a/This_is_soccer.webm",
        "license": "CC BY-SA 3.0", "author": "Evworo", "start": 0, "duration": 30,
        "event": "jogo-coletivo", "title": "A ESSÊNCIA DO\nFUTEBOL EM CADA TOQUE",
        "display_title": "A essência do futebol em cada toque",
        "script": [
            "O futebol nasce do passe, do movimento e da leitura coletiva.",
            "Cada toque prepara o próximo lance e aproxima o time do gol.",
            "É essa conexão entre jogadores que transforma o jogo em espetáculo.",
        ],
    },
    {
        "key": "o-jogo-bonito", "name": "O Jogo Bonito",
        "page": "https://commons.wikimedia.org/wiki/File:O_Jogo_Bonito_(The_Beautiful_Game).webm",
        "download": "https://upload.wikimedia.org/wikipedia/commons/3/30/O_Jogo_Bonito_%28The_Beautiful_Game%29.webm",
        "license": "CC BY-SA 4.0", "author": "Sarah Samaha", "start": 20, "duration": 35,
        "event": "cultura-do-futebol", "title": "POR QUE CHAMAM DE\nJOGO BONITO?",
        "display_title": "Por que chamam de jogo bonito?",
        "script": [
            "Chamam de jogo bonito porque o futebol mistura técnica, improviso e emoção.",
            "Um drible muda o ritmo, um passe encontra espaço e uma jogada simples vira memória.",
            "A beleza está no que acontece entre a intenção e o toque na bola.",
        ],
    },
    {
        "key": "primeiro-jogo-filmado", "name": "The world's first filmed soccer match",
        "page": "https://commons.wikimedia.org/wiki/File:The_world%E2%80%99s_first_filmed_soccer_match_with_corrected_speed-_Glentoran....webm",
        "download": "https://commons.wikimedia.org/wiki/Special:Redirect/file/The_world%E2%80%99s_first_filmed_soccer_match_with_corrected_speed-_Glentoran....webm",
        "license": "Public Domain Mark 1.0", "author": "obra histórica de 1897",
        "start": 0, "duration": 30, "event": "historia-do-futebol",
        "crop_top": 0.24,
        "title": "O PRIMEIRO JOGO DE\nFUTEBOL FILMADO",
        "display_title": "O futebol filmado há mais de um século",
        "script": [
            "Estas imagens estão entre os primeiros registros filmados de uma partida de futebol.",
            "O jogo era mais direto, os uniformes eram pesados e as câmeras ainda davam seus primeiros passos.",
            "Mais de um século depois, a paixão pela bola continua reconhecível.",
        ],
    },
]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def one(rows: Any) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("Registro obrigatório não encontrado")
    return rows[0]


def download(source: dict[str, Any]) -> Path:
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    target = SOURCE_ROOT / f"{source['key']}.webm"
    if not target.exists() or target.stat().st_size == 0:
        request = urllib.request.Request(source["download"], headers={"User-Agent": "BotLive/2.0 licensed-media"})
        with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    return target


def ass_time(seconds: float) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def create_tts_and_ass(source: dict[str, Any], stem: Path) -> tuple[Path, Path, float]:
    stem.parent.mkdir(parents=True, exist_ok=True)
    voice = stem.with_suffix(".tts.wav")
    ass = stem.with_suffix(".ass")
    narration = " ".join(source["script"])
    run("espeak-ng", "-v", "pt-br", "-s", os.getenv("KWAI_TTS_RATE", "145"), "-w", str(voice), narration)
    voice_duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(voice)],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    target_voice_duration = max(5.0, float(source["duration"]) - 1.0)
    tempo = max(0.5, min(2.0, voice_duration / target_voice_duration))
    segment = target_voice_duration / len(source["script"])
    events = []
    for index, text in enumerate(source["script"]):
        lines = textwrap.wrap(text, width=34, break_long_words=False)
        if len(lines) > 2:
            midpoint = max(1, len(lines) // 2)
            lines = [" ".join(lines[:midpoint]), " ".join(lines[midpoint:])]
        caption = r"\N".join(lines)
        events.append(
            f"Dialogue: 1,{ass_time(index * segment)},{ass_time(min((index + 1) * segment, source['duration']))},Caption,,0,0,0,,{caption}"
        )
    headline = source["title"].replace("\n", r"\N")
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n"
        "\n[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Headline,DejaVu Sans,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,"
        "-1,0,0,0,100,100,0,0,3,3,1,8,90,90,100,1\n"
        "Style: Caption,DejaVu Sans,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,"
        "-1,0,0,0,100,100,0,0,3,3,1,2,110,110,150,1\n"
        "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
        f"Dialogue: 2,0:00:00.00,{ass_time(source['duration'])},Headline,,0,0,0,,{headline}\n"
        + "\n".join(events) + "\n",
        encoding="utf-8",
    )
    return voice, ass, tempo


def source_has_audible_audio(path: Path) -> bool:
    return analyze_audio(path).status == "valid"


def render(source_path: Path, target: Path, source: dict[str, Any], voice: Path, ass: Path, tempo: float) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    crop_top = float(source.get("crop_top", 0))
    crop = f"crop=iw:ih*{1-crop_top:.4f}:0:ih*{crop_top:.4f}," if crop_top else ""
    base_video = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=24:12,eq=brightness=-0.18[blur];"
        f"[fg]{crop}scale=1080:1120:force_original_aspect_ratio=decrease[front];"
        "[blur][front]overlay=(W-w)/2:430+(1120-h)/2[base];"
        f"[base]subtitles='{str(ass).replace(chr(92), '/')}':fontsdir='/usr/share/fonts/truetype/dejavu'[out]"
    )
    audible_original = source_has_audible_audio(source_path)
    args = ["ffmpeg", "-y", "-ss", str(source["start"]), "-i", str(source_path), "-i", str(voice)]
    if audible_original:
        audio_filter = f"[0:a]loudnorm=I=-24:LRA=7:TP=-2,volume=0.35[original];[1:a]atempo={tempo:.5f},loudnorm=I=-16:LRA=7:TP=-1.5[voice];[original][voice]amix=inputs=2:duration=longest:dropout_transition=2[audio]"
        narration = "original+TTS"
    else:
        audio_filter = f"[1:a]atempo={tempo:.5f},loudnorm=I=-16:LRA=7:TP=-1.5,apad[audio]"
        narration = "TTS"
    run(*args, "-t", str(source["duration"]), "-filter_complex", f"{base_video};{audio_filter}",
        "-map", "[out]", "-map", "[audio]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest",
        "-movflags", "+faststart", str(target))
    return narration


def probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-show_entries", "stream=codec_name,width,height", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(completed.stdout)
    video = next(stream for stream in data["streams"] if stream.get("width"))
    audio = next((stream for stream in data["streams"] if not stream.get("width")), {})
    return {"duration": float(data["format"]["duration"]), "filesize": int(data["format"]["size"]),
            "width": int(video["width"]), "height": int(video["height"]),
            "codec": video.get("codec_name"), "audio_codec": audio.get("codec_name")}


def validation_frames(video: Path, source: dict[str, Any]) -> list[Path]:
    duration = float(source["duration"])
    times = [2, duration * .25, duration * .5, duration * .75, max(2, duration - 1)]
    paths = []
    for index, point in enumerate(times, start=1):
        frame = video.with_name(f"{video.stem}-validacao-{index}.jpg")
        run("ffmpeg", "-y", "-ss", f"{point:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(frame))
        paths.append(frame)
    return paths


def visual_gate(frames: list[Path]) -> bool:
    headline_ok = True
    caption_frames = 0
    for frame in frames:
        image = Image.open(frame).convert("L")
        top = image.crop((80, 70, 1000, 400))
        bottom = image.crop((80, 1450, 1000, 1810))
        headline_ok = headline_ok and top.getextrema()[1] - top.getextrema()[0] >= 45
        if bottom.getextrema()[1] - bottom.getextrema()[0] >= 35:
            caption_frames += 1
    return headline_ok and caption_frames >= 3


def cover(video: Path, target: Path) -> None:
    run("ffmpeg", "-y", "-ss", "2", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(target))


def main() -> None:
    if os.getenv("KWAI_API_ENABLED", "0") != "0":
        raise RuntimeError("KWAI_API_ENABLED deve permanecer 0")
    client = create_client(os.environ["ROBO_SUPABASE_URL"], os.environ["ROBO_SUPABASE_KEY"])
    destination = one(client.table("profile_destinations").select("id,account_id").eq("profile_id", PROFILE).eq("platform", "kwai").execute().data)

    for index, source in enumerate(SOURCES, start=1):
        source_path = download(source)
        filename = f"kwai-futebol-{source['event']}-{RUN_DATE}-{index:03d}-v2-final.mp4"
        video = READY_ROOT / filename
        cover_path = READY_ROOT / filename.replace(".mp4", "-capa.jpg")
        voice, ass, tempo = create_tts_and_ass(source, video)
        if video.exists():
            narration = "original+TTS" if source_has_audible_audio(source_path) else "TTS"
        else:
            narration = render(source_path, video, source, voice, ass, tempo)
        cover(video, cover_path)
        frames = validation_frames(video, source)
        info = probe(video)
        audio = analyze_audio(video)
        errors = []
        if (info["width"], info["height"]) != (1080, 1920): errors.append("rejected_resolution")
        if info["codec"] != "h264" or info["audio_codec"] != "aac": errors.append("rejected_codec")
        if audio.status != "valid": errors.append(audio.status)
        errors += required_text_gates(source["title"], ass, frames)
        if not visual_gate(frames): errors.append("rejected_visual_text_gate")
        errors = sorted(set(errors))
        gates = {
            "audible_audio": audio.status == "valid", "mean_volume_db": audio.mean_db,
            "max_volume_db": audio.peak_db, "audio_duration": audio.audio_duration,
            "headline_rendered": "rejected_missing_headline" not in errors,
            "captions_rendered": "rejected_missing_captions" not in errors,
            "narration": narration, "music": "none", "safe_area": "approved" if not errors else "rejected",
            "visual_validation": "approved" if not errors else "rejected",
            "validation_frames": [str(frame) for frame in frames],
            "headline_frame": str(frames[0]), "caption_frame": str(frames[1]),
        }
        sha256 = hashlib.sha256(video.read_bytes()).hexdigest()

        client.table("football_sources").upsert({
            "profile_id": PROFILE, "name": source["name"], "source_type": "authorized_feed",
            "source_ref": source["page"], "usage_status": "licensed", "enabled": True,
            "priority": 90-index, "status": "ready", "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None, "metrics": {"license": source["license"], "author": source["author"], "source": "Wikimedia Commons"},
        }, on_conflict="profile_id,source_type,source_ref").execute()
        event = one(client.table("content_events").upsert({
            "profile_id": PROFILE, "source_event_key": f"manual-mobile-v2-final:{source['key']}:{RUN_DATE}",
            "source_ref": source["page"], "timestamp_seconds": float(source["start"]),
            "event_type": source["event"], "metadata": {"confidence": 1.0, "football_real": True, "version": 2},
        }, on_conflict="profile_id,source_event_key").execute().data)
        variant = one(client.table("editorial_variants").upsert({
            "event_id": event["event_id"], "profile_id": PROFILE, "strategy": "cut",
            "variant_signature": f"manual-mobile-v2-final:{source['key']}",
            "editorial_metadata": {"format": "9:16", "headline": source["title"], "captions": source["script"], "version": 2},
        }, on_conflict="profile_id,event_id,variant_signature").execute().data)
        asset = one(client.table("media_assets").upsert({
            "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "path": str(video), "sha256": sha256, "duration": info["duration"], "width": info["width"],
            "height": info["height"], "aspect_ratio": "9:16", "codec": info["codec"],
            "audio_codec": info["audio_codec"], "filesize": info["filesize"],
            "validation_status": "invalid" if errors else "valid", "validation_errors": errors,
        }, on_conflict="profile_id,variant_id,sha256").execute().data)
        caption = f"{source['display_title']}\n\nFonte: {source['author']} · Wikimedia Commons · {source['license']}. Conteúdo adaptado."
        client.table("publication_jobs").upsert({
            "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "asset_id": asset["asset_id"], "destination_id": destination["id"], "platform": "kwai",
            "account_id": destination["account_id"], "status": "ready" if not errors else "rejected",
            "publication_key": f"kwai-v2-final:{sha256}", "title": source["display_title"], "caption": caption,
            "cover_path": str(cover_path), "metadata": {
                "publication_mode": "prepare_only", "publication_method": "manual_mobile",
                "download_filename": filename, "license": source["license"], "source_url": source["page"],
                "version": 2, "gates": gates,
            },
        }, on_conflict="publication_key").execute()
        print(json.dumps({"file": str(video), "status": "ready" if not errors else "rejected",
                          "errors": errors, "audio": audio.__dict__, "gates": gates}, ensure_ascii=False))


if __name__ == "__main__":
    main()
