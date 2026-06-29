from __future__ import annotations

import argparse
import os
import re
import socket
import ssl
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from threading import Event
from typing import Callable, Deque, Iterable, Optional
from urllib.parse import parse_qs, urlparse

import pytchat
from dotenv import load_dotenv


load_dotenv()


DEFAULT_KEYWORDS = [
    "KKKK",
    "MDS",
    "NAO ACREDITO",
    "NÃO ACREDITO",
    "PQP",
    "OLHA ISSO",
]


@dataclass
class ChatMessage:
    message: str
    timestamp_seconds: int
    author: str = ""


@dataclass
class PeakEvent:
    live_url: str
    timestamp_seconds: int
    messages_per_minute: int
    baseline_messages_per_minute: float
    matched_keywords: list[str]
    sample_messages: list[str]
    platform: str


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.upper()


def parse_time_to_seconds(value: str | int | float | None) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    value = str(value).strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)

    parts = value.split(":")
    if not all(part.isdigit() for part in parts):
        return None

    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def extract_youtube_video_id(url_or_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id

    parsed = urlparse(url_or_id)
    query = parse_qs(parsed.query)
    if "v" in query and query["v"]:
        return query["v"][0]

    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if "youtu.be" in host and path:
        return path.split("/")[0]
    if path.startswith("live/"):
        return path.split("/")[1]
    if path.startswith("shorts/"):
        return path.split("/")[1]

    raise ValueError("Nao consegui extrair o video_id do YouTube. Passe a URL completa ou o ID.")


def detect_platform(url: str, explicit_platform: str = "auto") -> str:
    if explicit_platform != "auto":
        return explicit_platform
    host = urlparse(url).netloc.lower()
    if "twitch.tv" in host:
        return "twitch"
    return "youtube"


class EngagementDetector:
    def __init__(
        self,
        live_url: str,
        platform: str,
        keywords: Optional[list[str]] = None,
        spike_multiplier: float = 3.0,
        window_seconds: int = 60,
        baseline_windows: int = 5,
        min_messages_per_minute: int = 20,
        cooldown_seconds: int = 120,
    ) -> None:
        self.live_url = live_url
        self.platform = platform
        self.keywords = keywords or DEFAULT_KEYWORDS
        self.normalized_keywords = [normalize_text(keyword) for keyword in self.keywords]
        self.spike_multiplier = spike_multiplier
        self.window_seconds = window_seconds
        self.baseline_windows = baseline_windows
        self.min_messages_per_minute = min_messages_per_minute
        self.cooldown_seconds = cooldown_seconds
        self.messages: Deque[ChatMessage] = deque()
        self.minute_history: Deque[int] = deque(maxlen=baseline_windows)
        self.current_window_start: Optional[int] = None
        self.current_window_count = 0
        self.last_peak_timestamp = -cooldown_seconds

    def process(self, chat_message: ChatMessage) -> Optional[PeakEvent]:
        timestamp = chat_message.timestamp_seconds
        if self.current_window_start is None:
            self.current_window_start = timestamp

        while timestamp - self.current_window_start >= self.window_seconds:
            self.minute_history.append(self.current_window_count)
            self.current_window_start += self.window_seconds
            self.current_window_count = 0

        self.current_window_count += 1
        self.messages.append(chat_message)

        cutoff = timestamp - self.window_seconds
        while self.messages and self.messages[0].timestamp_seconds < cutoff:
            self.messages.popleft()

        if timestamp - self.last_peak_timestamp < self.cooldown_seconds:
            return None

        baseline = self._baseline()
        current_mpm = len(self.messages)
        matched_keywords = self._matched_keywords()
        has_spike = current_mpm >= self.min_messages_per_minute and current_mpm >= baseline * self.spike_multiplier

        if not has_spike or not matched_keywords:
            return None

        self.last_peak_timestamp = timestamp
        sample_messages = [message.message for message in list(self.messages)[-10:]]
        return PeakEvent(
            live_url=self.live_url,
            timestamp_seconds=timestamp,
            messages_per_minute=current_mpm,
            baseline_messages_per_minute=round(baseline, 2),
            matched_keywords=matched_keywords,
            sample_messages=sample_messages,
            platform=self.platform,
        )

    def _baseline(self) -> float:
        if not self.minute_history:
            return max(1.0, self.min_messages_per_minute / self.spike_multiplier)
        return max(1.0, sum(self.minute_history) / len(self.minute_history))

    def _matched_keywords(self) -> list[str]:
        matched: set[str] = set()
        for message in self.messages:
            text = normalize_text(message.message)
            for original, normalized in zip(self.keywords, self.normalized_keywords):
                if normalized in text:
                    matched.add(original)
        return sorted(matched)


def youtube_messages(url: str, stop_event: Optional[Event] = None) -> Iterable[ChatMessage]:
    video_id = extract_youtube_video_id(url)
    chat = pytchat.create(video_id=video_id)
    started_at = time.monotonic()

    while chat.is_alive():
        if stop_event and stop_event.is_set():
            break

        data = chat.get()
        for item in data.items:
            timestamp = parse_time_to_seconds(getattr(item, "elapsedTime", None))
            if timestamp is None:
                timestamp = int(time.monotonic() - started_at)
            yield ChatMessage(
                message=getattr(item, "message", ""),
                timestamp_seconds=timestamp,
                author=getattr(getattr(item, "author", None), "name", ""),
            )
        time.sleep(1)


def twitch_channel_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    channel = path.split("/")[0] if path else url.strip().split("/")[-1]
    if not channel:
        raise ValueError("Nao consegui extrair o canal da Twitch.")
    return channel.lower()


def twitch_messages(url: str, stop_event: Optional[Event] = None) -> Iterable[ChatMessage]:
    """Leitor IRC da Twitch.

    Por padrao usa login anonimo justinfan para chats publicos.
    Se TWITCH_BOT_USERNAME e TWITCH_OAUTH_TOKEN existirem no .env, usa OAuth.
    """
    channel = twitch_channel_from_url(url)
    started_at = time.monotonic()
    configured_nickname = os.getenv("TWITCH_BOT_USERNAME", "").strip()
    configured_token = os.getenv("TWITCH_OAUTH_TOKEN", "").strip()

    if configured_nickname and configured_token:
        nickname = configured_nickname.lower()
        password = configured_token if configured_token.startswith("oauth:") else f"oauth:{configured_token}"
    else:
        nickname = f"justinfan{int(time.time()) % 100000}"
        password = "SCHMOOPIIE"

    context = ssl.create_default_context()
    with socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=30) as raw_socket:
        with context.wrap_socket(raw_socket, server_hostname="irc.chat.twitch.tv") as sock:
            sock.settimeout(1)
            sock.sendall(f"PASS {password}\r\nNICK {nickname}\r\nJOIN #{channel}\r\n".encode("utf-8"))
            buffer = ""

            while not stop_event or not stop_event.is_set():
                try:
                    chunk = sock.recv(4096).decode("utf-8", errors="ignore")
                except socket.timeout:
                    continue

                if not chunk:
                    break
                buffer += chunk
                lines = buffer.split("\r\n")
                buffer = lines.pop()

                for line in lines:
                    if line.startswith("PING"):
                        sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                        continue
                    if "PRIVMSG" not in line:
                        continue
                    _, message = line.split("PRIVMSG", 1)
                    message_text = message.split(":", 1)[-1].strip()
                    timestamp = int(time.monotonic() - started_at)
                    yield ChatMessage(message=message_text, timestamp_seconds=timestamp)


class ChatMonitor:
    def __init__(
        self,
        live_url: str,
        platform: str = "auto",
        keywords: Optional[list[str]] = None,
        spike_multiplier: float = 3.0,
        min_messages_per_minute: int = 20,
        cooldown_seconds: int = 120,
    ) -> None:
        self.live_url = live_url
        self.platform = detect_platform(live_url, platform)
        self.detector = EngagementDetector(
            live_url=live_url,
            platform=self.platform,
            keywords=keywords,
            spike_multiplier=spike_multiplier,
            min_messages_per_minute=min_messages_per_minute,
            cooldown_seconds=cooldown_seconds,
        )

    def run(
        self,
        on_peak: Callable[[PeakEvent], None],
        stop_event: Optional[Event] = None,
    ) -> None:
        source = youtube_messages if self.platform == "youtube" else twitch_messages
        for chat_message in source(self.live_url, stop_event=stop_event):
            peak = self.detector.process(chat_message)
            if peak:
                on_peak(peak)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor autonomo de picos de chat.")
    parser.add_argument("url", help="URL da live no YouTube ou Twitch.")
    parser.add_argument("--platform", choices=["auto", "youtube", "twitch"], default="auto")
    parser.add_argument("--spike-multiplier", type=float, default=3.0)
    parser.add_argument("--min-messages-per-minute", type=int, default=20)
    args = parser.parse_args()

    monitor = ChatMonitor(
        live_url=args.url,
        platform=args.platform,
        spike_multiplier=args.spike_multiplier,
        min_messages_per_minute=args.min_messages_per_minute,
    )

    def print_peak(event: PeakEvent) -> None:
        print(
            f"PICO DETECTADO em {event.timestamp_seconds}s | "
            f"{event.messages_per_minute} msg/min | keywords={event.matched_keywords}"
        )

    monitor.run(print_peak)


if __name__ == "__main__":
    main()
