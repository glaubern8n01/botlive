from __future__ import annotations

import subprocess
from pathlib import Path

from robust_downloader import RobustDownloader, is_direct_media


def _out_from_cmd(cmd: list[str]) -> Path | None:
    if "-o" in cmd:
        return Path(cmd[cmd.index("-o") + 1])
    # ffmpeg: último argumento é a saída
    return Path(cmd[-1]) if cmd and cmd[0] == "ffmpeg" else None


def make_runner(succeed_on, bot_block=False):
    """succeed_on: substring que, presente no comando, faz o download 'funcionar'."""
    def runner(cmd):
        joined = " ".join(cmd)
        if bot_block and "yt-dlp" in cmd[0]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ERROR: Sign in to confirm you're not a bot")
        if succeed_on and succeed_on in joined:
            out = _out_from_cmd(cmd)
            if out:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"video-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="download falhou")
    return runner


def test_direct_media_detection() -> None:
    assert is_direct_media("https://x/y/video.mp4")
    assert is_direct_media("https://x/stream.m3u8")
    assert not is_direct_media("https://www.youtube.com/watch?v=abc")


def test_direct_source_uses_ffmpeg(tmp_path) -> None:
    dl = RobustDownloader(runner=make_runner(succeed_on="ffmpeg"))
    r = dl.download("https://cdn/x/highlight.mp4", tmp_path)
    assert r.ok and r.method == "direct"


def test_ytdlp_first_client_wins(tmp_path) -> None:
    dl = RobustDownloader(runner=make_runner(succeed_on="player_client=tv"))
    r = dl.download("https://www.youtube.com/watch?v=abc", tmp_path)
    assert r.ok and r.method == "ytdlp:tv"


def test_ytdlp_falls_through_clients(tmp_path) -> None:
    dl = RobustDownloader(runner=make_runner(succeed_on="player_client=android"))
    r = dl.download("https://www.youtube.com/watch?v=abc", tmp_path)
    assert r.ok and r.method == "ytdlp:android"
    assert "ytdlp:tv" in r.attempts and "ytdlp:ios" in r.attempts


def test_bot_block_detected_and_relay_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOWNLOAD_RELAY_URL", "https://relay.example/dl")
    def relay_fetch(url, out):
        out.write_bytes(b"relayed"); return True
    dl = RobustDownloader(runner=make_runner(succeed_on=None, bot_block=True), relay_fetch=relay_fetch)
    r = dl.download("https://www.youtube.com/watch?v=abc", tmp_path)
    assert r.bot_blocked is True
    assert r.ok and r.method == "relay"
    assert "relay" in r.attempts


def test_bot_block_without_relay_reports_error(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOWNLOAD_RELAY_URL", raising=False)
    monkeypatch.delenv("BOTLIVE_COOKIES_FILE", raising=False)
    dl = RobustDownloader(runner=make_runner(succeed_on=None, bot_block=True))
    r = dl.download("https://www.youtube.com/watch?v=abc", tmp_path)
    assert not r.ok and r.bot_blocked and r.error == "bot_block"


def test_cookies_path_used_when_configured(tmp_path, monkeypatch) -> None:
    cookies = tmp_path / "cookies.txt"; cookies.write_text("# netscape")
    monkeypatch.setenv("BOTLIVE_COOKIES_FILE", str(cookies))
    monkeypatch.delenv("DOWNLOAD_RELAY_URL", raising=False)
    # yt-dlp só 'funciona' quando o comando inclui --cookies.
    dl = RobustDownloader(runner=make_runner(succeed_on="--cookies"))
    r = dl.download("https://www.youtube.com/watch?v=abc", tmp_path)
    assert r.ok and r.method == "ytdlp:cookies"
