"""Downloader de fontes com fallback em cascata.

Ordem de tentativa (para e retorna no primeiro sucesso), registrando qual método
funcionou para o painel:

1. Fonte direta MP4/HLS -> ffmpeg/stream, sem yt-dlp.
2. yt-dlp com vários player_client (tv, ios, android, mweb, web_safari, web).
3. yt-dlp com cookies (BOTLIVE_COOKIES_FILE) + PO token (YTDLP_PO_TOKEN/visitor_data).
4. Relay de download configurável (DOWNLOAD_RELAY_URL): um serviço em rede não
   bloqueada baixa o arquivo e devolve o MP4 para o volume da VPS.

O erro "Sign in to confirm you're not a bot" é detectado especificamente e
encaminha o job para o próximo método (cookies/PO token/relay), sem operação
manual por vídeo. A API oficial do YouTube serve só para descoberta/metadados —
ela não entrega o MP4, então não é usada aqui.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

BOT_BLOCK = re.compile(r"confirm you'?re not a bot|sign in to confirm", re.I)
DEFAULT_CLIENTS = ("tv", "ios", "android", "mweb", "web_safari", "web")


@dataclass
class DownloadResult:
    ok: bool
    path: Optional[str] = None
    method: Optional[str] = None       # 'direct' | 'ytdlp:<client>' | 'ytdlp:cookies' | 'relay'
    error: Optional[str] = None
    bot_blocked: bool = False
    attempts: list[str] = field(default_factory=list)


def is_direct_media(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith((".mp4", ".mov", ".m4v", ".m3u8", ".ts", ".webm"))


def _clients() -> tuple[str, ...]:
    raw = os.getenv("YTDLP_PLAYER_CLIENTS", "")
    return tuple(c.strip() for c in raw.split(",") if c.strip()) or DEFAULT_CLIENTS


class RobustDownloader:
    def __init__(
        self,
        runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        relay_fetch: Callable[[str, Path], bool] | None = None,
    ) -> None:
        # Injetáveis para teste offline (sem rede/ffmpeg reais).
        self._run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=1800))
        self._relay_fetch = relay_fetch

    def _ytdlp(self, url: str, out: Path, extra: list[str], label: str, result: DownloadResult) -> bool:
        cmd = ["yt-dlp", "--no-warnings", "-f", "bv*+ba/b", "--merge-output-format", "mp4",
               "-o", str(out), *extra, url]
        result.attempts.append(label)
        proc = self._run(cmd)
        text = f"{getattr(proc,'stdout','') or ''}\n{getattr(proc,'stderr','') or ''}"
        if BOT_BLOCK.search(text):
            result.bot_blocked = True
            return False
        if getattr(proc, "returncode", 1) == 0 and out.exists():
            result.ok, result.path, result.method = True, str(out), label
            return True
        result.error = (getattr(proc, "stderr", "") or "download falhou")[:200]
        return False

    def download(self, url: str, dest_dir: str | Path, filename: str = "source.mp4") -> DownloadResult:
        dest = Path(dest_dir); dest.mkdir(parents=True, exist_ok=True)
        out = dest / filename
        result = DownloadResult(ok=False)

        # 1. Fonte direta (não-YouTube): baixa via ffmpeg, sem yt-dlp.
        if is_direct_media(url):
            result.attempts.append("direct")
            proc = self._run(["ffmpeg", "-y", "-i", url, "-c", "copy", str(out)])
            if getattr(proc, "returncode", 1) == 0 and out.exists():
                result.ok, result.path, result.method = True, str(out), "direct"
                return result

        # 2. yt-dlp com múltiplos player_client.
        for client in _clients():
            if self._ytdlp(url, out, ["--extractor-args", f"youtube:player_client={client}"],
                           f"ytdlp:{client}", result):
                return result

        # 3. yt-dlp com cookies + PO token, se configurados.
        cookies = os.getenv("BOTLIVE_COOKIES_FILE")
        po = os.getenv("YTDLP_PO_TOKEN"); visitor = os.getenv("YTDLP_VISITOR_DATA")
        if cookies and Path(cookies).is_file():
            extra = ["--cookies", cookies]
            if po and visitor:
                extra += ["--extractor-args", f"youtube:po_token={po},visitor_data={visitor}"]
            if self._ytdlp(url, out, extra, "ytdlp:cookies", result):
                return result

        # 4. Relay configurável: baixa em rede não bloqueada e devolve o MP4.
        relay = os.getenv("DOWNLOAD_RELAY_URL")
        if relay and (result.bot_blocked or not result.ok):
            result.attempts.append("relay")
            try:
                fetch = self._relay_fetch or _default_relay_fetch
                if fetch(url, out) and out.exists():
                    result.ok, result.path, result.method = True, str(out), "relay"
                    return result
            except Exception as exc:  # noqa: BLE001 — relay é best-effort
                result.error = f"relay: {exc}"[:200]

        if not result.error:
            result.error = "bot_block" if result.bot_blocked else "sem método de download disponível"
        return result


def _default_relay_fetch(url: str, out: Path) -> bool:
    """POST {url} ao relay (DOWNLOAD_RELAY_URL); grava o MP4 retornado no volume."""
    import urllib.request
    relay = os.environ["DOWNLOAD_RELAY_URL"]
    token = os.getenv("DOWNLOAD_RELAY_TOKEN", "")
    req = urllib.request.Request(relay, data=json.dumps({"url": url}).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=1800) as resp, open(out, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return out.stat().st_size > 0


def _main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Baixa uma fonte com fallback em cascata.")
    p.add_argument("url")
    p.add_argument("--dest", default="/tmp")
    p.add_argument("--name", default="source.mp4")
    r = RobustDownloader().download(p.parse_args().url, p.parse_args().dest, p.parse_args().name)
    print(json.dumps({"ok": r.ok, "method": r.method, "bot_blocked": r.bot_blocked,
                      "attempts": r.attempts, "error": r.error, "path": r.path}))


if __name__ == "__main__":
    _main()
