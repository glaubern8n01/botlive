from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def cookies_path() -> Optional[Path]:
    """Arquivo cookies.txt (formato Netscape) para o yt-dlp, via env BOTLIVE_COOKIES_FILE.

    Plano B contra o "Sign in to confirm you're not a bot" da VPS: cookies
    exportados de um navegador logado. Sem a env (ou com arquivo inexistente)
    nada muda — uso local segue igual.
    """
    raw = os.environ.get("BOTLIVE_COOKIES_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        print(f"[cookies] BOTLIVE_COOKIES_FILE definido mas o arquivo nao existe: {path}")
        return None
    return path


def yt_player_client() -> Optional[list[str]]:
    """player_client do extractor do YouTube, via env BOTLIVE_YT_CLIENT.

    Tentativa A contra o bloqueio de IP de datacenter: android (ou ios, web...)
    faz o yt-dlp se apresentar como app em vez de navegador. Aceita lista
    separada por virgula (ex.: android,web) para fallback do proprio yt-dlp.
    """
    raw = os.environ.get("BOTLIVE_YT_CLIENT", "").strip()
    if not raw:
        return None
    clients = [c.strip() for c in raw.split(",") if c.strip()]
    return clients or None


def tls_no_verify() -> bool:
    """Desliga a verificacao TLS dos resolvedores (yt-dlp e streamlink), via
    env BOTLIVE_TLS_NO_VERIFY=1.

    Quirk de DEV LOCAL: antivirus que intercepta TLS (MITM) com CA propria sem
    Basic Constraints critico — o Python 3.13+ liga VERIFY_X509_STRICT por
    padrao e rejeita essa CA mesmo no bundle. Na VPS nao ha MITM e a env nunca
    deve ser definida.
    """
    return os.environ.get("BOTLIVE_TLS_NO_VERIFY", "").strip().lower() in {"1", "true", "yes"}


def com_opcoes_env(ydl_opts: dict) -> dict:
    """Retorna copia das opcoes do YoutubeDL com os ajustes opcionais de env:

    BOTLIVE_YT_CLIENT   -> extractor_args youtube:player_client
    BOTLIVE_COOKIES_FILE -> cookiefile
    BOTLIVE_TLS_NO_VERIFY -> nocheckcertificate (quirk de dev local, ver acima)

    Sem nenhuma das envs, devolve as opcoes originais intactas.
    """
    cookies = cookies_path()
    clients = yt_player_client()
    no_verify = tls_no_verify()
    if cookies is None and clients is None and not no_verify:
        return ydl_opts

    opts = dict(ydl_opts)
    if no_verify:
        opts["nocheckcertificate"] = True
    if cookies is not None:
        opts["cookiefile"] = str(cookies)
    if clients is not None:
        extractor_args = dict(opts.get("extractor_args") or {})
        youtube_args = dict(extractor_args.get("youtube") or {})
        youtube_args["player_client"] = clients
        extractor_args["youtube"] = youtube_args
        opts["extractor_args"] = extractor_args
    return opts
