"""Relay de download residencial para o Kwai CUT.

Roda na máquina de casa (IP residencial, que NÃO é bloqueado pelo YouTube),
baixa os vídeos de futebol autorizados, envia o MP4 para o volume da VPS e
registra a fonte como arquivo local — o produtor na VPS corta/edita sem baixar
nada (o IP da VPS é bloqueado). Sem operação manual por vídeo.

Fluxo por vídeo:
  candidato aprovado -> yt-dlp (residencial) -> valida audio+video ->
  scp p/ volume da VPS -> registra football_sources(local_file)+discovered ->
  dispara o corte -> valida ready.

Uso:
  python relay_run.py --limit 3            # processa 3 candidatos
  python relay_run.py --limit 30 --loop    # fica repondo até 30 prontos

Requer no .env local: ROBO_SUPABASE_URL, ROBO_SUPABASE_KEY.
Requer chave SSH em ~/.ssh/id_ed25519 para o host da VPS (VPS_HOST).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

PROFILE = "kwai_cut_futebol"
VPS_HOST = os.getenv("VPS_HOST", "root@69.62.96.161")
SSH_KEY = os.path.expanduser(os.getenv("VPS_SSH_KEY", "~/.ssh/id_ed25519"))
# Caminho do volume no host da VPS que o container enxerga como /data/botlive/output.
VPS_VOLUME = os.getenv("VPS_OUTPUT_VOLUME", "/etc/easypanel/projects/botlive/botlive-app/volumes/botlive-output")
CONTAINER_PATH = "/data/botlive/output/relay"
WORK = Path(os.getenv("RELAY_WORK", os.path.expanduser("~/.botlive-relay")))


def _env() -> tuple[str, str]:
    url = os.getenv("ROBO_SUPABASE_URL"); key = os.getenv("ROBO_SUPABASE_KEY")
    if not (url and key):
        for line in (Path(".env").read_text(encoding="utf-8").splitlines() if Path(".env").exists() else []):
            if line.startswith("ROBO_SUPABASE_URL="): url = line.split("=", 1)[1].strip()
            if line.startswith("ROBO_SUPABASE_KEY="): key = line.split("=", 1)[1].strip()
    if not (url and key):
        sys.exit("Faltam ROBO_SUPABASE_URL/ROBO_SUPABASE_KEY (env ou .env).")
    return url, key


def _rest(url: str, key: str, path: str, method: str = "GET", body=None):
    req = Request(url + "/rest/v1/" + path, method=method,
                  data=(json.dumps(body).encode() if body is not None else None),
                  headers={"apikey": key, "Authorization": "Bearer " + key,
                           "Content-Type": "application/json", "Prefer": "return=representation"})
    with urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else []


def _ssh(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-i", SSH_KEY, VPS_HOST, cmd],
                          capture_output=True, text=True, timeout=120)


def _scp(local: Path, remote: str) -> bool:
    r = subprocess.run(["scp", "-o", "BatchMode=yes", "-i", SSH_KEY, str(local), f"{VPS_HOST}:{remote}"],
                       capture_output=True, text=True, timeout=1800)
    return r.returncode == 0


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Prefere H.264/AAC para render rápido; --no-check-certificates cobre o MITM local (AVG).
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-check-certificates",
           "-f", "bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=1080]/best",
           "--merge-output-format", "mp4", "-o", str(dest), url]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600).returncode == 0 and dest.exists()


def validate(path: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True)
    kinds = set(r.stdout.split())
    return "video" in kinds and "audio" in kinds and path.stat().st_size > 200_000


def ready_count(url: str, key: str) -> int:
    rows = _rest(url, key, f"publication_jobs?select=job_id&profile_id=eq.{PROFILE}&status=in.(ready,published_manual)")
    return len(rows)


def pending_candidates(url: str, key: str, limit: int):
    return _rest(url, key, f"football_source_prospects?select=prospect_id,source_url,title"
                           f"&profile_id=eq.{PROFILE}&review_status=eq.review_required&limit={limit}")


def process_one(url: str, key: str, cand: dict) -> str:
    vid_url = cand["source_url"]; title = (cand.get("title") or "Corte futebol")[:80]
    name = f"relay_{uuid.uuid4().hex[:10]}.mp4"
    local = WORK / name
    print(f"  baixando: {title[:48]} ...", flush=True)
    if not download(vid_url, local):
        return "download_falhou"
    if not validate(local):
        local.unlink(missing_ok=True); return "invalido"
    remote_host = f"{VPS_VOLUME}/relay/{name}"
    _ssh(f"mkdir -p {VPS_VOLUME}/relay")
    print("  enviando p/ VPS ...", flush=True)
    if not _scp(local, remote_host):
        return "envio_falhou"
    local.unlink(missing_ok=True)
    container_file = f"{CONTAINER_PATH}/{name}"
    src = _rest(url, key, "football_sources?on_conflict=profile_id,source_type,source_ref", "POST", {
        "profile_id": PROFILE, "name": f"Relay: {title[:40]}", "source_type": "local_file",
        "source_ref": container_file, "usage_status": "campaign_allowed", "enabled": True, "priority": 90,
        "allowed_live": False, "allowed_vod": True, "allowed_highlights": True,
    })
    source_id = src[0]["source_id"] if src else _rest(url, key,
        f"football_sources?select=source_id&profile_id=eq.{PROFILE}&source_ref=eq.{container_file}")[0]["source_id"]
    _rest(url, key, "football_discovered_videos", "POST", {
        "profile_id": PROFILE, "source_id": source_id, "discovery_key": f"relay-{name}",
        "source_url": container_file, "source_name": "Relay residencial", "title": title,
        "duration": 0, "status": "found",
    })
    # marca o candidato como permitido (registro/auditoria) e dispara o corte na VPS
    _rest(url, key, f"football_source_prospects?prospect_id=eq.{cand['prospect_id']}", "PATCH",
          {"review_status": "campaign_allowed", "reviewed_by": "relay", "owner_name": "Responsável pelo canal"})
    print("  cortando na VPS ...", flush=True)
    r = _ssh("pc=$(docker ps -q -f name=botlive_kwai-cut-producer | head -1); "
             "docker exec -e KWAI_API_ENABLED=0 \"$pc\" python -c "
             "'from database import _get_client; from kwai_real_pipeline import KwaiRealPipeline; "
             "print(KwaiRealPipeline(_get_client()).process_next())'")
    return "ready" if "ready_review" in (r.stdout + r.stderr) else f"corte:{(r.stdout + r.stderr)[-80:]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--target", type=int, default=30)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    url, key = _env(); WORK.mkdir(parents=True, exist_ok=True)
    done = 0
    while True:
        have = ready_count(url, key)
        print(f"[relay] prontos na VPS: {have} | meta: {args.target}")
        if have >= args.target and args.loop:
            print("[relay] estoque cheio; aguardando."); time.sleep(300); continue
        cands = pending_candidates(url, key, min(args.limit, max(1, args.target - have)))
        if not cands:
            print("[relay] sem candidatos em review_required."); break
        for c in cands:
            print(f"[relay] {done+1}: {c['source_url']}")
            r = process_one(url, key, c)
            print(f"[relay] -> {r}")
            if r == "ready": done += 1
        if not args.loop:
            break
    print(f"[relay] concluído. novos cortes prontos nesta execução: {done}")


if __name__ == "__main__":
    main()
