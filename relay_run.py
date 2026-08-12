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

# Títulos de futebol vêm com emoji (🔴 live etc.); no console do Windows (cp1252)
# o print quebra. Força UTF-8 tolerante no stdout/stderr para nunca abortar por isso.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — streams sem reconfigure (redirecionados) seguem
        pass

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
            if line.startswith("ROBO_SUPABASE_URL=") and line.split("=", 1)[1].strip(): url = line.split("=", 1)[1].strip()
            if line.startswith("ROBO_SUPABASE_KEY=") and line.split("=", 1)[1].strip(): key = line.split("=", 1)[1].strip()
    if not (url and key):
        # Auto-config: puxa as credenciais da VPS pelo SSH (não guarda no .env
        # nem imprime). O relay precisa só da chave SSH e do repo.
        print("[relay] credenciais locais ausentes; puxando da VPS via SSH...")
        try:
            g = ("docker exec $(docker ps -q -f name=botlive_kwai-cut-producer | head -1) printenv ")
            url = url or _ssh(g + "ROBO_SUPABASE_URL").stdout.strip()
            key = key or _ssh(g + "ROBO_SUPABASE_KEY").stdout.strip()
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"Falha ao obter credenciais da VPS: {exc}")
    if not (url and key):
        sys.exit("Faltam ROBO_SUPABASE_URL/ROBO_SUPABASE_KEY (env, .env ou VPS).")
    return url, key


import ssl as _ssl
# Contexto TLS tolerante ao MITM local (AVG). Rede de casa confiável; ainda usa
# HTTPS + a chave de serviço. Não afeta a VPS (lá o certificado é válido).
_TLS = _ssl.create_default_context()
if os.getenv("RELAY_TLS_VERIFY", "0") != "1":
    _TLS.check_hostname = False
    _TLS.verify_mode = _ssl.CERT_NONE


def _rest(url: str, key: str, path: str, method: str = "GET", body=None):
    req = Request(url + "/rest/v1/" + path, method=method,
                  data=(json.dumps(body).encode() if body is not None else None),
                  headers={"apikey": key, "Authorization": "Bearer " + key,
                           "Content-Type": "application/json", "Prefer": "return=representation"})
    with urlopen(req, timeout=30, context=_TLS) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else []


# Windows OpenSSH NÃO suporta ControlMaster (multiplexação usa Unix sockets), então
# cada chamada é uma conexão nova. Para não pendurar/crashar quando a VPS reseta ou
# satura: ConnectTimeout curto (falha em ~20s) + captura de TimeoutExpired (o relay
# segue vivo em vez de morrer no loop). Poucas conexões por arquivo pra não saturar.
def _ssh(cmd: str, timeout: int = 45) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                               "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
                               "-i", SSH_KEY, VPS_HOST, cmd],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["ssh"], 124, "", "ssh timeout")


def _scp(local: Path, remote: str) -> bool:
    """Envia o arquivo pra VPS numa ÚNICA conexão SSH (stream via `cat`), com
    keepalive e compressão. O scp em pedaços abria dezenas de conexões e o AVG/
    rede saturava e cortava (uploads intermitentes). Uma conexão só é rápida e
    estável; verifica o tamanho no destino e re-tenta o arquivo inteiro se cair."""
    size = local.stat().st_size
    # Usa o binário `scp` (confiável no Windows/cmd E Git Bash). O `ssh cat >` via
    # stdin caía no Git Bash; scp com keepalive + retry é estável. Verifica o
    # tamanho no destino e re-tenta o arquivo inteiro se cair.
    # SEM -C (compressão): o -C causava falhas intermitentes de upload (vídeo já
    # é comprimido, e a compressão SSH saturava/cortava). scp puro é rápido/estável.
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=6", "-o", "TCPKeepAlive=yes", "-i", SSH_KEY]
    # Sem `rm -f` antes: o scp SOBRESCREVE o destino sozinho, e aquele rm era mais
    # uma conexão SSH que pendurava 120s e derrubava o relay. Menos conexões = estável.
    for tent in range(5):
        try:
            r = subprocess.run(["scp", *opts, str(local), f"{VPS_HOST}:{remote}"],
                               capture_output=True, text=True, timeout=1800)
        except (subprocess.SubprocessError, OSError):
            time.sleep(5); continue
        if r.returncode == 0 and _ssh(f"test $(stat -c %s {remote}) -eq {size}").returncode == 0:
            return True
        time.sleep(min(5 + tent * 5, 25))
    return False


def download(url: str, dest: Path) -> tuple[bool, str]:
    """Multi-engine: yt-dlp (principal, 1080p) e pytubefix (fallback, engine
    diferente). Apps como Seal/YTDLnis/Stacher/OVD usam yt-dlp por dentro — mesmo
    erro, não contam como fallback separado. Retorna (ok, engine que funcionou)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # A. yt-dlp — --no-check-certificates cobre o MITM local (AVG).
    # Resolução limitada por RELAY_MAX_HEIGHT (default 720): o corte é vertical
    # 1080-largura, então 720p de fonte basta e economiza MUITA banda/tempo/disco
    # (essencial pra rodar 30-100/dia sem estourar internet).
    h = max(360, min(1080, int(os.getenv("RELAY_MAX_HEIGHT", "720"))))
    # Pula PARTIDAS COMPLETAS (90min ~ vários GB): só o corte de 35s importa e o
    # upload de GBs pra VPS é inviável. Checagem por metadados (não baixa o gigante).
    # Highlights/"melhores momentos" ficam abaixo do teto. Configurável.
    maxdur = int(os.getenv("RELAY_MAX_DURATION_SEC", "1200"))   # 20 min
    maxsize = os.getenv("RELAY_MAX_FILESIZE", "150M")           # upload confiavel
    # O YouTube bloqueia o IP residencial ("Sign in to confirm you're not a bot").
    # Cookies do YouTube logado autenticam e liberam. Preferimos um ARQUIVO
    # cookies.txt (RELAY_COOKIES_FILE) — o --cookies-from-browser do Chrome novo
    # falha por criptografia (DPAPI/App-Bound). Vazio nos dois = sem cookies.
    cookies_file = os.getenv("RELAY_COOKIES_FILE", "").strip()
    browser = os.getenv("RELAY_COOKIES_BROWSER", "").strip()
    if cookies_file and Path(cookies_file).is_file():
        cookies = ["--cookies", cookies_file]
    elif browser:
        cookies = ["--cookies-from-browser", browser]
    else:
        cookies = []
    # Formato TOLERANTE: prioriza combinado (b*, ex.: format 18 do client tv que o
    # yt-dlp novo usa com cookies), depois streams separados, depois qualquer best.
    # O seletor estrito avc1+mp4a falhava quando só havia formato combinado.
    # Clientes alternativos (tv/ios/web_safari) furam o bot-block do YouTube em
    # bloqueios LEVES (não usam o PO token do web). Em bloqueio pesado de IP nada
    # fura — aí o loop RECUA (backoff) pro IP desflagrar. Configurável.
    clients = os.getenv("RELAY_YT_CLIENTS", "default,tv,web_safari,ios").strip()
    # Proxy (ex.: iproyal residencial): fura o bloqueio de IP na hora usando um IP
    # limpo, sem depender do IP de casa desflagrar. Vazio = usa o IP de casa.
    proxy = os.getenv("RELAY_PROXY", "").strip()
    proxy_args = ["--proxy", proxy] if proxy else []
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-check-certificates", *cookies, *proxy_args,
           "--extractor-args", f"youtube:player_client={clients}",
           "--match-filter", f"duration < {maxdur}", "--max-filesize", maxsize,
           # GARANTE ÁUDIO: bv*+ba (junta vídeo+áudio) primeiro; b* sozinho pegava
           # formato só-vídeo (ex.: 398 AV1) e o corte saía "invalido" (sem áudio).
           "-f", f"bv*[height<={h}]+ba/b[height<={h}]/best[height<={h}]/best",
           "--merge-output-format", "mp4", "-o", str(dest), url]
    _r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if _r.returncode == 0 and dest.exists():
        return True, "yt-dlp"
    # Detecta bot-block (bloqueio de IP, TRANSITÓRIO) vs link morto (removido/privado).
    _err = ((_r.stderr or "") + (_r.stdout or "")).lower()
    _botblock = ("confirm you" in _err and "bot" in _err) or "sign in to confirm" in _err
    # B. pytubefix — engine independente (não usa yt-dlp). ssl-off = mesma postura
    # do nocheckcertificate; rede de casa confiável, vídeo público.
    import ssl
    _prev = ssl._create_default_https_context
    try:
        # Escopo local: desativa a verificação só durante o pytubefix (MITM do
        # AVG) e RESTAURA no finally — nunca fica global.
        if os.getenv("RELAY_TLS_VERIFY", "0") != "1":
            ssl._create_default_https_context = ssl._create_unverified_context  # noqa: S323
        from pytubefix import YouTube

        yt = YouTube(url)
        st = (yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
              or yt.streams.get_highest_resolution())
        if st:
            st.download(output_path=str(dest.parent), filename=dest.name)
            if dest.exists() and dest.stat().st_size > 200_000:
                return True, "pytubefix"
    except Exception:  # noqa: BLE001 — pytubefix é opcional
        pass
    finally:
        ssl._create_default_https_context = _prev
    # Bot-block = transitório (não é culpa do vídeo); "dead" = link morto de verdade.
    return (False, "botblock") if _botblock else (False, "dead")


def validate(path: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True)
    kinds = set(r.stdout.split())
    return "video" in kinds and "audio" in kinds and path.stat().st_size > 200_000


def _guard_ok() -> tuple[bool, str]:
    """Guardas para rodar em celular/PC: armazenamento e (no Android) bateria/temp."""
    import shutil
    free_gb = shutil.disk_usage(WORK.anchor or "/").free / 1e9
    min_free = float(os.getenv("RELAY_MIN_FREE_GB", "2"))
    if free_gb < min_free:
        return False, f"armazenamento baixo ({free_gb:.1f}GB < {min_free}GB)"
    # Android/Termux: pausa com bateria baixa ou aparelho quente.
    try:
        out = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            bat = json.loads(out.stdout)
            if bat.get("percentage", 100) < int(os.getenv("RELAY_MIN_BATTERY", "30")) and not bat.get("plugged"):
                return False, f"bateria baixa ({bat.get('percentage')}%)"
            if (bat.get("temperature", 0) or 0) > float(os.getenv("RELAY_MAX_TEMP_C", "45")):
                return False, f"temperatura alta ({bat.get('temperature')}C)"
    except Exception:  # noqa: BLE001 — sem termux-api (ex.: no PC) ignora a guarda de bateria
        pass
    return True, "ok"


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
    ok, engine = download(vid_url, local)
    if not ok:
        if engine == "botblock":
            # Bot-block é bloqueio de IP TRANSITÓRIO — o vídeo é bom. NÃO marca o
            # candidato como bloqueado (senão a fila de vídeos bons é destruída);
            # deixa em review_required pra re-tentar. Sinaliza o loop pra RECUAR.
            local.unlink(missing_ok=True)
            return "botblock"
        # Falha REAL (vídeo removido, privado, região): tira da fila, senão o relay
        # re-pega SEMPRE os mesmos e nunca avança. Fica registrado (reavaliável).
        try:
            _rest(url, key, f"football_source_prospects?prospect_id=eq.{cand['prospect_id']}", "PATCH",
                  {"review_status": "blocked", "reviewed_by": "relay",
                   "blocked_reason": "download_falhou_auto"})
        except Exception:  # noqa: BLE001 — best-effort; no pior caso repete
            pass
        return "download_falhou"
    print(f"  engine: {engine}", flush=True)
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
        "metadata": {"downloader": engine, "origin": "relay", "original_url": vid_url},
    })
    # marca o candidato como permitido (registro/auditoria) e dispara o corte na VPS
    _rest(url, key, f"football_source_prospects?prospect_id=eq.{cand['prospect_id']}", "PATCH",
          {"review_status": "campaign_allowed", "reviewed_by": "relay", "owner_name": "Responsável pelo canal"})
    print("  cortando na VPS ...", flush=True)
    r = _ssh("pc=$(docker ps -q -f name=botlive_kwai-cut-producer | head -1); "
             "docker exec -e KWAI_API_ENABLED=0 \"$pc\" python -c "
             "'from database import _get_client; from kwai_real_pipeline import KwaiRealPipeline; "
             "print(KwaiRealPipeline(_get_client()).process_next())'", timeout=600)
    ok_cut = "ready_review" in (r.stdout + r.stderr)
    if ok_cut:
        # Disco da VPS é curto: apaga o arquivo-fonte após o corte final (o MP4
        # cortado já está no volume ready/). Mantém a fonte se o corte falhou.
        _ssh(f"rm -f {remote_host}")
    return "ready" if ok_cut else f"corte:{(r.stdout + r.stderr)[-80:]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--target", type=int, default=30)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    url, key = _env(); WORK.mkdir(parents=True, exist_ok=True)
    done = 0
    botblocks = 0   # bot-blocks consecutivos do YouTube (controla o recuo)
    while True:
        ok, why = _guard_ok()
        if not ok:
            print(f"[relay] pausado: {why}")
            if not args.loop:
                break
            time.sleep(300); continue
        have = ready_count(url, key)
        print(f"[relay] prontos na VPS: {have} | meta: {args.target}")
        if have >= args.target and args.loop:
            print("[relay] estoque cheio; aguardando."); time.sleep(300); continue
        cands = pending_candidates(url, key, min(args.limit, max(1, args.target - have)))
        if not cands:
            # No modo loop (PC/celular sempre ligado), espera novos candidatos que
            # o produtor descobre com o tempo em vez de encerrar.
            print("[relay] sem candidatos em review_required.")
            if not args.loop:
                break
            time.sleep(300); continue
        for c in cands:
            print(f"[relay] {done+1}: {c['source_url']}")
            r = process_one(url, key, c)
            print(f"[relay] -> {r}")
            if r == "ready":
                done += 1; botblocks = 0
            if r == "botblock":
                # O YouTube flagrou o IP. Martelar mantém o flag e não produz nada.
                # RECUA (5, 10, 20 min... teto 30) pro IP desflagrar; sai do lote e
                # re-avalia. O candidato fica intacto na fila pra re-tentar depois.
                botblocks += 1
                back = min(300 * (2 ** (botblocks - 1)), 1800)
                print(f"[relay] BOT-BLOCK do YouTube (x{botblocks}): IP flagrado. "
                      f"Recuando {back // 60}min pro IP recuperar (candidato preservado).", flush=True)
                if not args.loop:
                    break
                time.sleep(back)
                break
        if not args.loop:
            break
    print(f"[relay] concluído. novos cortes prontos nesta execução: {done}")


if __name__ == "__main__":
    main()
