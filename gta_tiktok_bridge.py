"""Ponte GTA -> rascunho TikTok.

O fluxo legado GTA publica no YouTube e no Instagram direto (sem passar pela
fila nova) e o TikTok Standard vive na fila `publication_jobs`. Os dois estavam
desacoplados, então um vídeo ia para YouTube/Instagram e nunca ganhava job de
TikTok. Esta ponte pega o MASTER ORIGINAL vertical já gerado (não baixa do
YouTube nem do Instagram), registra o media_asset do perfil GTA e enfileira
SOMENTE o destino TikTok que faltava, em modo upload_draft.

Seguro por construção:
- só age quando GTA_TIKTOK_AUTO_DRAFT_ENABLED=1 (rollback = desligar a flag);
- nunca cria job de YouTube ou Instagram;
- idempotente por asset + destino + perfil (não duplica);
- usa sempre o master original vertical (9:16);
- não publica publicamente (a fila entrega como rascunho; publicação é manual).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

PROFILE = "default"          # perfil GTA (validar em produção; ver profile_destinations)
PLATFORM = "tiktok_standard"
FLAG = "GTA_TIKTOK_AUTO_DRAFT_ENABLED"

# Estados que já contam como job existente: não recriar. Só 'failed'/'rejected'/
# 'cancelled' liberam nova tentativa.
BLOCKING_JOB_STATES = frozenset({
    "pending", "validating", "ready", "uploading", "processing",
    "published", "retry_wait", "published_manual",
})

GTA_HASHTAGS = ("#gta6", "#gtabrasil", "#gta6brasil", "#gtavi", "#gtart", "#gaming")
GTA_HOOKS = (
    "Você viu esse momento?",
    "Isso é GTA?!",
    "Momento insano no GTA!",
    "Clipe que você precisa ver",
    "Aconteceu no GTA 6 Brasil",
)


def bridge_enabled() -> bool:
    return os.getenv(FLAG, "0") == "1"


def normalize_hashtags(tags: Any) -> str:
    """Sem vírgulas, sem ##, sem duplicadas (case-insensitive), sem vazias."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags or ():
        for token in re.split(r"[\s,;]+", str(raw)):
            cleaned = re.sub(r"^#+", "", token)
            cleaned = re.sub(r"[^\w]", "", cleaned, flags=re.UNICODE).strip()
            if not cleaned:
                continue
            low = cleaned.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append("#" + cleaned)
    return " ".join(out)


def gta_tiktok_text(title: Optional[str], keywords: Any, seed: int) -> tuple[str, str, str]:
    """Descrição/créditos/hashtags próprios do TikTok (variados por seed)."""
    hook = GTA_HOOKS[seed % len(GTA_HOOKS)]
    base = (title or "Corte GTA").strip()
    description = f"{hook} {base}".strip()
    credits = "Créditos: @gta6brasilcortes"
    hashtags = normalize_hashtags(list(keywords or []) + list(GTA_HASHTAGS))
    return description, credits, hashtags


def _publication_key(sha256: str) -> str:
    # Inclui a plataforma -> dedup por asset + destino + perfil (YouTube/Instagram
    # do mesmo asset teriam chaves diferentes e não bloqueiam o TikTok).
    return f"gta-tiktok:{PROFILE}:{PLATFORM}:{sha256}"


class GtaTikTokBridge:
    def __init__(
        self,
        client: Any,
        inspector: Optional[Callable[..., Any]] = None,
        fingerprinter: Optional[Callable[..., Optional[str]]] = None,
    ) -> None:
        self.client = client
        self._inspector = inspector
        self._fingerprinter = fingerprinter

    def _inspect(self, path: Path) -> Any:
        inspector = self._inspector
        if inspector is None:
            from media_domain import inspect_media_asset  # import tardio: evita ffmpeg nos testes
            inspector = inspect_media_asset
        return inspector(str(path), PROFILE)

    def _audio_fingerprint(self, path: Path) -> Optional[str]:
        fingerprinter = self._fingerprinter
        if fingerprinter is None:
            from kwai_real_pipeline import audio_fingerprint
            fingerprinter = audio_fingerprint
        try:
            return fingerprinter(path)
        except Exception:
            return None

    def _existing_asset_id(self, sha256: str) -> Optional[str]:
        rows = (self.client.table("media_assets").select("asset_id")
                .eq("profile_id", PROFILE).eq("sha256", sha256).execute().data or [])
        return str(rows[0]["asset_id"]) if rows else None

    def _has_blocking_job(self, asset_id: str) -> bool:
        rows = (self.client.table("publication_jobs").select("status")
                .eq("asset_id", asset_id).eq("platform", PLATFORM).execute().data or [])
        return any(str(r.get("status")) in BLOCKING_JOB_STATES for r in rows)

    def _destination(self) -> dict[str, Any]:
        return (self.client.table("profile_destinations").select("id,account_id,enabled")
                .eq("profile_id", PROFILE).eq("platform", PLATFORM).single().execute().data)

    def bridge(
        self,
        master_path: str | Path,
        title: Optional[str] = None,
        keywords: Any = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        path = Path(master_path)
        if not path.is_file():
            return {"status": "error", "reason": "master_inexistente", "path": str(path)}
        asset = self._inspect(path)
        # Só verticais 9:16 vão ao TikTok (usa sempre o master original).
        if getattr(asset, "aspect_ratio", None) != "9:16":
            return {"status": "skipped", "reason": f"nao_vertical:{asset.width}x{asset.height}"}

        existing = self._existing_asset_id(asset.sha256)
        if existing and self._has_blocking_job(existing):
            return {"status": "skipped", "reason": "tiktok_job_ja_existe", "asset_id": existing}

        seed = int(asset.sha256[:8], 16)
        description, credits, hashtags = gta_tiktok_text(title, keywords, seed)
        if dry_run:
            return {"status": "dry_run", "sha256": asset.sha256, "aspect_ratio": asset.aspect_ratio,
                    "description": description, "credits": credits, "hashtags": hashtags}

        destination = self._destination()
        if not destination or not destination.get("enabled"):
            return {"status": "skipped", "reason": "destino_tiktok_desabilitado"}

        audio_hash = self._audio_fingerprint(path)
        asset_id = existing or str(uuid4())
        if not existing:
            event = self.client.table("content_events").insert({
                "profile_id": PROFILE, "source_event_key": f"gta-tiktok:{asset.sha256}",
                "source_ref": str(path), "timestamp_seconds": 0,
                "event_type": title or "Corte GTA", "metadata": {"origin": "gta_tiktok_bridge"},
            }).execute().data[0]
            variant = self.client.table("editorial_variants").insert({
                "event_id": event["event_id"], "profile_id": PROFILE, "strategy": "cut",
                "variant_signature": f"gta-tiktok:{asset.sha256}",
                "editorial_metadata": {"platform": PLATFORM, "audio_policy": "preserve_original"},
            }).execute().data[0]
            self.client.table("media_assets").insert({
                "asset_id": asset_id, "profile_id": PROFILE, "event_id": event["event_id"],
                "variant_id": variant["variant_id"], "path": str(path), "sha256": asset.sha256,
                "perceptual_hash": asset.perceptual_hash, "audio_fingerprint": audio_hash,
                "duration": asset.duration, "width": asset.width, "height": asset.height,
                "aspect_ratio": asset.aspect_ratio, "codec": asset.codec, "audio_codec": asset.audio_codec,
                "filesize": asset.filesize, "validation_status": "valid", "validation_errors": [],
            }).execute()
            event_id, variant_id = event["event_id"], variant["variant_id"]
        else:
            event_id = variant_id = None

        job_id = str(uuid4())
        self.client.table("publication_jobs").insert({
            "job_id": job_id, "profile_id": PROFILE, "event_id": event_id, "variant_id": variant_id,
            "asset_id": asset_id, "destination_id": destination["id"], "platform": PLATFORM,
            "account_id": destination.get("account_id"), "status": "ready",
            "publication_key": _publication_key(asset.sha256),
            "title": title or "Corte GTA", "caption": f"{description}\n\n{credits}\n\n{hashtags}",
            "metadata": {"publication_mode": "upload_draft", "description": description,
                         "credits": credits, "hashtags": hashtags, "origin": "gta_tiktok_bridge",
                         "download_filename": path.name},
        }).execute()
        return {"status": "created", "asset_id": asset_id, "job_id": job_id,
                "publication_key": _publication_key(asset.sha256)}


def bridge_clip(client: Any, clip_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Repara um corte legado específico (dark_gta_clips) pelo id — correspondência
    segura escolhida por humano, não por heurística."""
    row = (client.table("dark_gta_clips").select("output_path,metadata")
           .eq("id", clip_id).single().execute().data)
    if not row or not row.get("output_path"):
        return {"status": "error", "reason": "clip_sem_output_path", "clip_id": clip_id}
    md = row.get("metadata") or {}
    return GtaTikTokBridge(client).bridge(
        row["output_path"], title=md.get("title"), keywords=md.get("keywords"), dry_run=dry_run)


def _main() -> None:
    import argparse
    from database import _get_client
    parser = argparse.ArgumentParser(description="Enfileira SOMENTE o rascunho TikTok de um corte GTA.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--path", help="Caminho do master vertical GTA")
    group.add_argument("--clip", help="id em dark_gta_clips")
    parser.add_argument("--title")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="ignora a feature flag (uso manual pontual)")
    args = parser.parse_args()
    if not bridge_enabled() and not args.force and not args.dry_run:
        raise SystemExit(f"{FLAG}!=1 — use --force para reparo manual pontual ou --dry-run.")
    client = _get_client()
    if args.clip:
        result = bridge_clip(client, args.clip, dry_run=args.dry_run)
    else:
        result = GtaTikTokBridge(client).bridge(args.path, title=args.title, dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    _main()
