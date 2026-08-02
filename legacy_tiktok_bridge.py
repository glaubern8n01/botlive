from __future__ import annotations

"""Ponte do fluxo legado BotLive/Reels para o worker separado tiktok-public.

Depois que o Reel e aceito, registra o mesmo MP4 vertical na fila Supabase
(`publication_jobs`) como `tiktok_standard` / `upload_draft`. As credenciais
continuam exclusivas do container tiktok-public; este modulo nunca chama a API
do TikTok nem le tokens.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from database import _get_client

ACTIVE = {"pending", "validating", "ready", "uploading", "processing", "retry_wait"}


def _one(rows: list[dict[str, Any]] | None, label: str) -> dict[str, Any]:
    if not rows:
        raise RuntimeError(f"{label} nao configurado no Supabase")
    return rows[0]


def _probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    if not video:
        raise RuntimeError("MP4 vertical sem stream de video")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0 or height <= width:
        raise RuntimeError(f"TikTok exige master vertical; recebido {width}x{height}")
    return {
        "duration": float((data.get("format") or {}).get("duration") or 0),
        "filesize": int((data.get("format") or {}).get("size") or path.stat().st_size),
        "width": width,
        "height": height,
        "codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
    }


def _caption(registro: dict[str, Any]) -> str:
    texto = str(registro.get("legenda") or registro.get("titulo") or "").strip()
    hashtags = registro.get("hashtags") or []
    tags = " ".join(str(tag) if str(tag).startswith("#") else f"#{tag}" for tag in hashtags)
    return "\n\n".join(parte for parte in (texto, tags) if parte)


def _destination(client, nicho: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = (
        client.table("profile_destinations")
        .select("id,profile_id,account_id,enabled,publication_mode,max_attempts,settings")
        .eq("platform", "tiktok_standard")
        .eq("enabled", True)
        .execute()
        .data
        or []
    )
    if nicho == "gta":
        rows.sort(key=lambda row: 0 if "gta" in str(row.get("profile_id", "")).lower() else 1)
    destination = _one(rows, "destino tiktok_standard habilitado")
    mode = str(destination.get("publication_mode") or (destination.get("settings") or {}).get("mode") or "")
    if mode != "upload_draft":
        raise RuntimeError(f"destino TikTok esta em {mode or 'sem modo'}, esperado upload_draft")
    account = _one(
        client.table("platform_accounts")
        .select("id,account_key,secret_ref,status,metadata")
        .eq("id", destination["account_id"])
        .execute()
        .data,
        "conta tiktok_standard",
    )
    return destination, account


def enfileirar_rascunho_tiktok(registro: dict[str, Any]) -> dict[str, Any]:
    client = _get_client()
    if client is None:
        raise RuntimeError("ROBO_SUPABASE_URL/KEY ausentes; ponte TikTok sem fila")

    vertical = Path(str(registro.get("vertical") or ""))
    if not vertical.is_file():
        raise RuntimeError(f"master vertical ausente: {vertical}")

    destination, account = _destination(client, registro.get("nicho"))
    info = _probe(vertical)
    digest = hashlib.sha256(vertical.read_bytes()).hexdigest()
    profile_id = str(destination["profile_id"])
    source_key = f"legacy-reels:{digest}"
    now = datetime.now(timezone.utc).isoformat()

    event = _one(
        client.table("content_events").upsert(
            {
                "profile_id": profile_id,
                "source_event_key": source_key,
                "source_ref": str(vertical),
                "timestamp_seconds": 0,
                "event_type": "highlight",
                "metadata": {"origin": "botlive_reels", "youtube": (registro.get("postagens") or {}).get("youtube")},
            },
            on_conflict="profile_id,source_event_key",
        ).execute().data,
        "evento da ponte TikTok",
    )
    variant = _one(
        client.table("editorial_variants").upsert(
            {
                "event_id": event["event_id"],
                "profile_id": profile_id,
                "strategy": "reuse_vertical_master",
                "variant_signature": f"tiktok-upload-draft:{digest}",
                "editorial_metadata": {"format": "9:16", "origin": "instagram_success"},
            },
            on_conflict="profile_id,event_id,variant_signature",
        ).execute().data,
        "variante da ponte TikTok",
    )
    asset = _one(
        client.table("media_assets").upsert(
            {
                "profile_id": profile_id,
                "event_id": event["event_id"],
                "variant_id": variant["variant_id"],
                "path": str(vertical),
                "sha256": digest,
                "duration": info["duration"],
                "width": info["width"],
                "height": info["height"],
                "aspect_ratio": "9:16",
                "codec": info["codec"],
                "audio_codec": info["audio_codec"],
                "filesize": info["filesize"],
                "validation_status": "valid",
                "validation_errors": [],
            },
            on_conflict="profile_id,variant_id,sha256",
        ).execute().data,
        "asset da ponte TikTok",
    )

    publication_key = f"reels-to-tiktok-standard:{account['id']}:{digest}"
    existing = (
        client.table("publication_jobs")
        .select("job_id,status,external_id,last_error")
        .eq("publication_key", publication_key)
        .execute()
        .data
        or []
    )
    metadata = {
        "asset_path": str(vertical),
        "account_key": account.get("account_key"),
        "secret_ref": account.get("secret_ref"),
        "publish_mode": "upload_draft",
        "publication_mode": "upload_draft",
        "publisher_options": {**(destination.get("settings") or {}), "mode": "upload_draft"},
        "destination_id": destination["id"],
        "origin": "botlive_instagram_promoter",
        "instagram": (registro.get("postagens") or {}).get("instagram"),
    }
    payload = {
        "profile_id": profile_id,
        "event_id": event["event_id"],
        "variant_id": variant["variant_id"],
        "asset_id": asset["asset_id"],
        "destination_id": destination["id"],
        "platform": "tiktok_standard",
        "account_id": account["id"],
        "status": "ready",
        "publication_key": publication_key,
        "title": str(registro.get("titulo") or registro.get("legenda") or "BotLive")[:150],
        "caption": _caption(registro),
        "max_attempts": int(destination.get("max_attempts") or 3),
        "metadata": metadata,
        "updated_at": now,
    }

    if existing:
        row = existing[0]
        if row.get("status") == "published" or row.get("status") in ACTIVE:
            return {"tipo": "fila_tiktok_public", "job_id": row["job_id"], "status": row["status"], "duplicado": True, "erro": None}
        payload.update({"attempts": 0, "next_attempt_at": None, "worker_id": None, "locked_at": None, "lock_expires_at": None, "last_error": None})
        updated = client.table("publication_jobs").update(payload).eq("job_id", row["job_id"]).execute().data
        job = _one(updated, "retry do job TikTok")
    else:
        payload.update({"job_id": str(uuid4()), "created_at": now})
        job = _one(client.table("publication_jobs").insert(payload).execute().data, "job TikTok")

    return {"tipo": "fila_tiktok_public", "job_id": job["job_id"], "status": job["status"], "duplicado": False, "erro": None}
