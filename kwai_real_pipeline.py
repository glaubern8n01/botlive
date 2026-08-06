from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import imageio_ffmpeg
from PIL import Image
from moviepy.editor import VideoFileClip

from clipper import criar_corte_vertical_de_arquivo, validar_video_final
from highlight_detector import detectar_melhores_momentos
from media_domain import inspect_media_asset
from runtime_paths import get_output_root
from source_downloader import resolver_fonte_video
from vertical_meme import MemeTextConfig, legenda_contextual, renderizar_vertical_meme, subtexto_aleatorio


PROFILE = "kwai_cut_futebol"
ACTION_LABELS = (
    ("penal", "Pênalti decisivo", "penalti"),
    ("gol", "Gol em destaque", "gol"),
    ("defesa", "Grande defesa", "defesa"),
    ("save", "Grande defesa", "defesa"),
    ("drible", "Drible em destaque", "drible"),
    ("expuls", "Expulsão na partida", "expulsao"),
    ("red card", "Cartão vermelho", "expulsao"),
    ("falta", "Lance de falta", "falta"),
    ("virada", "Virada em destaque", "virada"),
    ("comemor", "Comemoração marcante", "comemoracao"),
    ("chance", "Grande chance", "grande-chance"),
)


def audio_fingerprint(path: Path) -> str | None:
    """Hash do PCM normalizado; nomes/containers diferentes não burlam a deduplicação."""
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120, check=True)
    except (subprocess.SubprocessError, OSError):
        return None
    return hashlib.sha256(result.stdout).hexdigest() if result.stdout else None


def action_metadata(title: str) -> tuple[str, str, str]:
    clean = " ".join(title.split()).strip()
    lowered = clean.casefold()
    label, slug = "Lance decisivo", "lance"
    for term, candidate, candidate_slug in ACTION_LABELS:
        if term in lowered:
            label, slug = candidate, candidate_slug
            break
    description = clean[:180] if clean else label
    hashtags = f"#futebol #{slug} #melhoresmomentos #kwai"
    return label, description, hashtags


def unique_cover(video: Path, target: Path, timestamp_ratio: float = 0.45) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    clip = VideoFileClip(str(video), audio=False)
    try:
        point = min(max(0.1, float(clip.duration or 0) * timestamp_ratio), max(0.1, float(clip.duration or 0) - 0.1))
        Image.fromarray(clip.get_frame(point)).convert("RGB").save(target, "JPEG", quality=92)
    finally:
        clip.close()
    return target


@dataclass(frozen=True)
class ProcessResult:
    discovered_id: str
    status: str
    reason: str | None = None
    job_id: str | None = None
    sha256: str | None = None
    perceptual_hash: str | None = None
    audio_fingerprint: str | None = None


class KwaiRealPipeline:
    """Transforma um candidato real descoberto em um corte prepare-only revisável."""

    def __init__(self, client: Any, output_root: Path | None = None) -> None:
        self.client = client
        self.output_root = output_root or get_output_root()

    def _update(self, discovered_id: str, **values: Any) -> None:
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.client.table("football_discovered_videos").update(values).eq("discovered_id", discovered_id).execute()

    def _reject(self, row: Mapping[str, Any], reason: str) -> ProcessResult:
        self._update(str(row["discovered_id"]), status="rejected", discard_reason=reason)
        return ProcessResult(str(row["discovered_id"]), "rejected", reason)

    def _already_exists(self, field: str, value: str | None) -> bool:
        if not value:
            return False
        rows = self.client.table("media_assets").select("asset_id").eq("profile_id", PROFILE).eq(field, value).limit(1).execute().data
        return bool(rows)

    def process(self, row: Mapping[str, Any]) -> ProcessResult:
        discovered_id = str(row["discovered_id"])
        self._update(discovered_id, status="processing", discard_reason=None)
        try:
            source = Path(resolver_fonte_video(str(row["source_url"])))
        except Exception as exc:
            self._update(discovered_id, status="error", discard_reason=f"download_failed:{type(exc).__name__}")
            return ProcessResult(discovered_id, "error", "download_failed")

        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        duplicate_source = self.client.table("football_discovered_videos").select("discovered_id").eq(
            "profile_id", PROFILE).eq("source_sha256", source_sha).neq("discovered_id", discovered_id).limit(1).execute().data
        if duplicate_source:
            return self._reject(row, "duplicate_source_sha256")

        self._update(discovered_id, source_sha256=source_sha, status="processing")
        candidates = detectar_melhores_momentos(
            source, max_cortes=max(1, min(int(row.get("max_cuts") or 3), 8)),
            min_gap_seconds=35, ignore_first_seconds=8, min_score=0.12,
        )
        if not candidates:
            return self._reject(row, "no_relevant_action_detected")

        candidate = max(candidates, key=lambda item: item.score)
        self._update(discovered_id, status="cut_identified", metadata={
            **dict(row.get("metadata") or {}), "selection_reason": candidate.reason,
            "selection_score": candidate.score, "peak_seconds": candidate.timestamp_seconds,
        })
        run_dir = self.output_root / "kwai_cut" / "ready" / datetime.now().strftime("%Y%m%d")
        run_dir.mkdir(parents=True, exist_ok=True)
        token = re.sub(r"[^a-zA-Z0-9]+", "-", discovered_id)[:16]
        self._update(discovered_id, status="rendering")
        # "original" mantém o corte 16:9; o renderizar_vertical_meme faz o
        # crop-to-fill 9:16 (tela toda) + banners. (vertical-fit letterboxava e
        # deixava o vídeo pequeno.)
        raw = criar_corte_vertical_de_arquivo(
            source, candidate.timestamp_seconds, f"kwai-real-{token}",
            seconds_before=12, seconds_after=23, output_layout="original",
        )
        title, description, hashtags = action_metadata(str(row.get("title") or ""))
        final = run_dir / f"kwai-real-{token}-aprovado.mp4"
        credits = f"Fonte: {row.get('source_name') or 'canal cadastrado'} · {row.get('source_url')}"
        seed = abs(hash((str(row.get("title") or ""), candidate.timestamp_seconds))) % (2 ** 31)
        renderizar_vertical_meme(raw, final, MemeTextConfig(
            # hook do topo usa o CONTEXTO REAL do título (competição/craque/clássico)
            # quando existe; senão, pool variado por tipo de lance.
            legenda=legenda_contextual(str(row.get("title") or ""), title, seed=seed),
            subtexto=subtexto_aleatorio(title, seed=seed),      # subtexto do vídeo no rodapé (sem canal)
        ))
        validation = validar_video_final(final, require_audio=True, min_duration_seconds=10, min_size_bytes=100_000)
        if not validation.valid:
            return self._reject(row, f"invalid_render:{validation.reason}")

        asset = inspect_media_asset(final, PROFILE)
        audio_hash = audio_fingerprint(final)
        if self._already_exists("sha256", asset.sha256):
            return self._reject(row, "duplicate_final_sha256")
        if self._already_exists("perceptual_hash", asset.perceptual_hash):
            return self._reject(row, "duplicate_visual_hash")
        if self._already_exists("audio_fingerprint", audio_hash):
            return self._reject(row, "duplicate_audio_fingerprint")

        event = self.client.table("content_events").insert({
            "profile_id": PROFILE, "source_event_key": f"kwai-real:{discovered_id}:{candidate.timestamp_seconds}",
            "source_ref": str(row["source_url"]), "timestamp_seconds": candidate.timestamp_seconds,
            "event_type": title, "metadata": {"confidence": candidate.score, "selection_reason": candidate.reason,
                "source_name": row.get("source_name"), "source_published_at": row.get("source_published_at")},
        }).execute().data[0]
        variant = self.client.table("editorial_variants").insert({
            "event_id": event["event_id"], "profile_id": PROFILE, "strategy": "cut",
            "variant_signature": hashlib.sha256(f"{discovered_id}:{candidate.timestamp_seconds}:12:23".encode()).hexdigest(),
            "editorial_metadata": {"start_seconds": max(0, candidate.timestamp_seconds - 12),
                "end_seconds": candidate.timestamp_seconds + 23, "audio_policy": "preserve_original",
                "burned_text": title, "source_discovered_id": discovered_id},
        }).execute().data[0]
        asset_id = str(uuid4())
        self.client.table("media_assets").insert({
            "asset_id": asset_id, "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "path": str(final), "sha256": asset.sha256, "perceptual_hash": asset.perceptual_hash,
            "audio_fingerprint": audio_hash, "duration": asset.duration, "width": asset.width, "height": asset.height,
            "aspect_ratio": asset.aspect_ratio, "codec": asset.codec, "audio_codec": asset.audio_codec,
            "filesize": asset.filesize, "validation_status": "valid", "validation_errors": [],
        }).execute()
        destination = self.client.table("profile_destinations").select("id,account_id").eq(
            "profile_id", PROFILE).eq("platform", "kwai").single().execute().data
        cover = unique_cover(final, final.with_name(final.stem + "-capa.jpg"))
        job_id = str(uuid4())
        self.client.table("publication_jobs").insert({
            "job_id": job_id, "profile_id": PROFILE, "event_id": event["event_id"], "variant_id": variant["variant_id"],
            "asset_id": asset_id, "destination_id": destination["id"], "platform": "kwai",
            "account_id": destination["account_id"], "status": "ready", "publication_key": f"kwai-real:{asset.sha256}",
            "title": title, "caption": f"{description}\n\n{hashtags}\n\n{credits}", "cover_path": str(cover),
            "metadata": {"publication_mode": "prepare_only", "description": description, "hashtags": hashtags,
                "credits": credits, "source_url": row["source_url"], "source_name": row.get("source_name"),
                "source_published_at": row.get("source_published_at"), "start_seconds": max(0, candidate.timestamp_seconds - 12),
                "end_seconds": candidate.timestamp_seconds + 23, "selection_reason": candidate.reason,
                "audio_policy": "preserve_original", "audio_fingerprint": audio_hash,
                "download_filename": final.name, "duplicate_status": "unique"},
        }).execute()
        self._update(discovered_id, status="ready_review", media_asset_id=asset_id, publication_job_id=job_id)
        return ProcessResult(discovered_id, "ready_review", job_id=job_id, sha256=asset.sha256,
                             perceptual_hash=asset.perceptual_hash, audio_fingerprint=audio_hash)

    def process_next(self) -> ProcessResult | None:
        rows = self.client.table("football_discovered_videos").select("*").eq("profile_id", PROFILE).in_(
            "status", ["found", "waiting_processing"]).order("created_at").limit(1).execute().data or []
        return self.process(rows[0]) if rows else None
