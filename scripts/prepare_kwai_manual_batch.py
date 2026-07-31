"""Gera lote v2 licenciado com áudio audível, headline e legendas queimadas."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kwai_media_validation import analyze_audio, required_text_gates
from kwai_cut_producer import resource_block_reason

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

SOURCES_V3: list[dict[str, Any]] = [
    {
        **SOURCES[0], "start": 7, "duration": 28, "event": "movimentacao-sem-bola",
        "title": "O JOGO MUDA\nANTES DO PASSE",
        "display_title": "O detalhe que acontece antes do passe",
        "script": [
            "Antes da bola chegar, o jogador atento já observou o espaço ao redor.",
            "A movimentação sem bola abre linhas de passe e muda toda a jogada.",
            "No futebol coletivo, a decisão começa antes do primeiro toque.",
        ],
    },
    {
        **SOURCES[1], "start": 58, "duration": 32, "event": "controle-e-criatividade",
        "title": "CONTROLE OU IMPROVISO?\nOS DOIS DECIDEM",
        "display_title": "Quando controle e improviso se encontram",
        "script": [
            "O controle orientado permite receber a bola já preparando a próxima ação.",
            "Mas o improviso aparece quando o espaço fecha e o plano precisa mudar.",
            "Os grandes lances nascem do equilíbrio entre técnica, leitura e coragem.",
        ],
    },
    {
        **SOURCES[2], "start": 11, "duration": 28, "event": "evolucao-do-jogo",
        "title": "O FUTEBOL MUDOU\nMAS A DISPUTA NÃO",
        "display_title": "O que mudou no futebol em mais de um século",
        "script": [
            "As imagens antigas mostram um jogo direto, disputado e cercado pela torcida.",
            "Equipamentos, regras e preparação evoluíram ao longo de mais de um século.",
            "Mesmo assim, a vontade de ganhar cada bola continua exatamente reconhecível.",
        ],
    },
]

TOPICS = [
    ("leitura-de-jogo", "LER O JOGO\nMUDA TUDO", "Como a leitura de jogo antecipa o próximo lance?"),
    ("apoio-e-triangulacao", "APOIO CRIA\nNOVOS CAMINHOS", "Por que os apoios curtos abrem espaços?"),
    ("ritmo-da-partida", "QUEM CONTROLA O RITMO\nCONTROLA O JOGO", "O detalhe que muda o ritmo de uma partida"),
    ("ocupacao-de-espacos", "ESPAÇO TAMBÉM\nÉ JOGADA", "O valor de ocupar o espaço certo"),
    ("decisao-rapida", "DECIDIR RÁPIDO\nFAZ DIFERENÇA", "Por que a decisão vem antes do toque?"),
    ("futebol-de-outras-epocas", "O JOGO DE ONTEM\nEXPLICA O DE HOJE", "O que o futebol antigo ainda ensina?"),
    ("comportamento-coletivo", "ONZE JOGADORES\nUMA SÓ IDEIA", "Como o comportamento coletivo organiza o time?"),
    ("tecnica-e-contexto", "TÉCNICA SEM LEITURA\nNÃO BASTA", "Técnica e contexto precisam andar juntos"),
    ("historia-das-regras", "AS REGRAS MUDARAM\nO JOGO TAMBÉM", "Como as regras ajudaram o futebol a evoluir?"),
]

HOOK_STYLES = (
    "curiosity_gap", "surprising_detail", "direct_question", "before_after", "myth_vs_reality"
)


def automatic_sources() -> list[dict[str, Any]]:
    """Catálogo determinístico de trechos e roteiros materialmente distintos."""
    # SOURCES_V3 já foi produzido; o modo automático começa apenas em pautas novas.
    result: list[dict[str, Any]] = []
    for index, (event, headline, display) in enumerate(TOPICS):
        base = SOURCES[index % len(SOURCES)]
        start = 4 + (index // len(SOURCES)) * 18 + (index % len(SOURCES)) * 7
        result.append({
            **base, "start": start, "duration": 26 + (index % 4) * 2,
            "event": event, "title": headline, "display_title": display,
            "hook_style": HOOK_STYLES[index % len(HOOK_STYLES)],
            "script": [
                f"Neste trecho, o foco está em {display.lower().rstrip('?')}.",
                "Observe como posição, tempo e escolha mudam o desenvolvimento da jogada.",
                "O futebol fica mais claro quando entendemos o que acontece antes da bola chegar.",
            ],
        })
    return result


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
        words = text.split()
        split_at = min(
            range(1, len(words)),
            key=lambda point: abs(len(" ".join(words[:point])) - len(" ".join(words[point:]))),
        )
        lines = [" ".join(words[:split_at]), " ".join(words[split_at:])]
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
        "Style: Caption,DejaVu Sans,38,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,"
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", choices=("v2", "v3"), default="v2")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if os.getenv("KWAI_API_ENABLED", "0") != "0":
        raise RuntimeError("KWAI_API_ENABLED deve permanecer 0")
    client = create_client(os.environ["ROBO_SUPABASE_URL"], os.environ["ROBO_SUPABASE_KEY"])
    destination = one(client.table("profile_destinations").select("id,account_id").eq("profile_id", PROFILE).eq("platform", "kwai").execute().data)

    sources = automatic_sources() if args.auto else (SOURCES_V3 if args.batch == "v3" else SOURCES)
    version = 4 if args.auto else (3 if args.batch == "v3" else 2)
    if args.auto:
        existing = client.table("publication_jobs").select("metadata").eq("profile_id", PROFILE).execute().data or []
        produced = {str(row.get("metadata", {}).get("source_segment_key")) for row in existing}
        sources = [s for s in sources if f"{s['key']}:{s['start']}:{s['event']}" not in produced]
    if args.limit > 0:
        sources = sources[:args.limit]
    for index, source in enumerate(sources, start=1):
        block = resource_block_reason()
        if block:
            raise RuntimeError(f"Render paused by resource guard: {block}")
        source_path = download(source)
        filename = f"kwai-futebol-{source['event']}-{RUN_DATE}-{index:03d}-v{version}-aprovado.mp4"
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
            "profile_id": PROFILE, "source_event_key": f"manual-mobile-v{version}-approved:{source['key']}:{RUN_DATE}",
            "source_ref": source["page"], "timestamp_seconds": float(source["start"]),
            "event_type": source["event"], "metadata": {"confidence": 1.0, "football_real": True, "version": version},
        }, on_conflict="profile_id,source_event_key").execute().data)
        variant = one(client.table("editorial_variants").upsert({
            "event_id": event["event_id"], "profile_id": PROFILE, "strategy": "cut",
            "variant_signature": f"manual-mobile-v{version}-approved:{source['key']}:{source['start']}",
            "editorial_metadata": {"format": "9:16", "headline": source["title"], "captions": source["script"], "version": version},
        }, on_conflict="profile_id,event_id,variant_signature").execute().data)
        asset = one(client.table("media_assets").upsert({
            "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "path": str(video), "sha256": sha256, "duration": info["duration"], "width": info["width"],
            "height": info["height"], "aspect_ratio": "9:16", "codec": info["codec"],
            "audio_codec": info["audio_codec"], "filesize": info["filesize"],
            "validation_status": "invalid" if errors else "valid", "validation_errors": errors,
        }, on_conflict="profile_id,variant_id,sha256").execute().data)
        hashtag_sets = [
            "#futebol #leituradejogo #tática #kwai #futebolrespira",
            "#futebol #jogocoletivo #futebolbrasileiro #kwai #bolanopé",
            "#históriadofutebol #futebolraiz #futebolmundial #kwai #futebolrespira",
        ]
        description = f"{source['display_title']} Um detalhe para observar no próximo jogo."
        credits = f"Fonte e créditos: {source['author']} · Wikimedia Commons · {source['license']}."
        hashtags = hashtag_sets[(index - 1) % len(hashtag_sets)]
        caption = f"{description}\n\n{credits}\n\n{hashtags}"
        segment_key = f"{source['key']}:{source['start']}:{source['event']}"
        client.table("publication_jobs").upsert({
            "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "asset_id": asset["asset_id"], "destination_id": destination["id"], "platform": "kwai",
            "account_id": destination["account_id"], "status": "ready" if not errors else "rejected",
            "publication_key": f"kwai-v{version}-approved:{sha256}", "title": source["display_title"], "caption": caption,
            "cover_path": str(cover_path), "metadata": {
                "publication_mode": "prepare_only", "publication_method": "manual_mobile",
                "download_filename": filename, "license": source["license"], "source_url": source["page"],
                "source_author": source["author"], "source_segment_key": segment_key,
                "hook_style": source.get("hook_style", "contextual_question"),
                "layout": {"headline": "top", "captions": "bottom", "watermark_added": False},
                "description": description, "hashtags": hashtags, "credits": credits,
                "cta": "Qual detalhe você percebeu?", "text_approved": False,
                "text_edited_manually": False, "version": version, "gates": gates,
            },
        }, on_conflict="publication_key").execute()
        print(json.dumps({"file": str(video), "status": "ready" if not errors else "rejected",
                          "errors": errors, "audio": audio.__dict__, "gates": gates}, ensure_ascii=False))


if __name__ == "__main__":
    main()
