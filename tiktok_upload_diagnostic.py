from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

from tiktok_platform import TIKTOK_STANDARD_ACCOUNT_KEY
from tiktok_public_server import _supabase_request, token_store

INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
MAX_CHUNK = 64 * 1024 * 1024
MIN_CHUNK = 5 * 1024 * 1024


class SafeTikTokError(RuntimeError):
    def __init__(self, stage: str, status: int, payload: dict, content_type: str = "") -> None:
        api_error = payload.get("error") if isinstance(payload, dict) else {}
        if not isinstance(api_error, dict):
            api_error = {}
        self.report = {
            "stage": stage, "http_status": status,
            "code": str(api_error.get("code") or "unknown_tiktok_error"),
            "message": str(api_error.get("message") or "TikTok request failed")[:500],
            "log_id": str(api_error.get("log_id") or "")[:200],
            "content_type": content_type.split(";", 1)[0],
        }
        super().__init__(json.dumps(self.report, ensure_ascii=False))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def chunk_geometry(video_size: int) -> tuple[int, int]:
    if video_size <= 0:
        raise ValueError("empty video")
    if video_size <= MAX_CHUNK:
        return video_size, 1
    # >64MB: divide em chunks ~iguais, todos entre MIN_CHUNK e MAX_CHUNK. Usar
    # MAX_CHUNK direto deixava o último chunk < 5MB (TikTok recusa com
    # "total chunk count is invalid"); chunks iguais evitam isso.
    # O TikTok recalcula total_chunk_count = floor(video_size / chunk_size) e o
    # ÚLTIMO chunk absorve o resto (pode passar de chunk_size). Por isso chunk_size
    # tem que ser FLOOR (video_size // count), senão o count enviado diverge do
    # que o TikTok calcula ("total chunk count is invalid").
    count = (video_size + MAX_CHUNK - 1) // MAX_CHUNK
    chunk_size = video_size // count
    last = video_size - chunk_size * (count - 1)
    if count > 1000 or chunk_size > MAX_CHUNK or chunk_size < MIN_CHUNK or last <= 0 or video_size // chunk_size != count:
        raise ValueError("invalid chunk geometry")
    return chunk_size, count


def safe_api(stage: str, req: request.Request, timeout: int = 30) -> tuple[int, dict, str]:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            payload = json.loads(raw) if raw else {}
            content_type = response.headers.get("Content-Type", "")
            status = response.status
    except error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        raise SafeTikTokError(stage, exc.code, payload, exc.headers.get("Content-Type", "")) from None
    api_error = payload.get("error") if isinstance(payload, dict) else {}
    if isinstance(api_error, dict) and api_error.get("code") not in {None, "", "ok"}:
        raise SafeTikTokError(stage, status, payload, content_type)
    return status, payload, content_type


def account_id() -> str:
    rows = _supabase_request(
        "platform_accounts?platform=eq.tiktok_standard&account_key="
        f"eq.{TIKTOK_STANDARD_ACCOUNT_KEY}&select=id&limit=1"
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("TikTok account metadata missing")
    return str(rows[0]["id"])


def persist_upload(values: dict) -> None:
    _supabase_request(
        "tiktok_standard_uploads?on_conflict=publication_key",
        method="POST", payload=values,
    )


def diagnose_tiktok_upload(path: Path, publication_key: str, no_upload: bool = False) -> dict:
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("valid MP4 asset required")
    size = path.stat().st_size
    sha256 = file_sha256(path)
    chunk_size, chunk_count = chunk_geometry(size)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    tokens = token_store().load(TIKTOK_STANDARD_ACCOUNT_KEY)
    scopes = {part.strip() for part in str(tokens.get("scope") or "").replace(" ", ",").split(",")}
    if "video.upload" not in scopes:
        raise RuntimeError("video.upload is not granted")
    if int(tokens.get("expires_at") or 0) <= int(time.time()) + 60:
        raise RuntimeError("access token is expired; refresh required before upload")
    report = {
        "asset": path.name, "video_size": size, "sha256": sha256,
        "mime": mime, "chunk_size": chunk_size, "total_chunk_count": chunk_count,
        "scope_ok": True, "no_upload": no_upload,
    }
    if no_upload:
        return report
    token = str(tokens["access_token"])
    body = {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": chunk_size, "total_chunk_count": chunk_count}}
    init_req = request.Request(
        INIT_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
    )
    init_status, init_payload, _ = safe_api("init", init_req)
    data = init_payload.get("data") or {}
    publish_id, upload_url = str(data.get("publish_id") or ""), str(data.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise SafeTikTokError("init", init_status, {"error": {"code": "missing_upload_identifiers",
                                                               "message": "TikTok did not return upload identifiers"}})
    started = datetime.now(timezone.utc).isoformat()
    persisted = {
        "account_id": account_id(), "publication_key": publication_key,
        "publish_id": publish_id, "asset_path": str(path), "asset_sha256": sha256,
        "video_size": size, "chunk_size": chunk_size, "total_chunk_count": chunk_count,
        "status": "upload_initialized", "upload_started_at": started, "updated_at": started,
    }
    persist_upload(persisted)
    host = urlparse(upload_url).hostname or ""
    sent = 0
    with path.open("rb") as handle:
        for index in range(chunk_count):
            # último chunk absorve o resto (pode ser > chunk_size), como o TikTok espera
            to_read = (size - sent) if index == chunk_count - 1 else chunk_size
            block = handle.read(to_read)
            if not block:
                raise RuntimeError("unexpected empty media chunk")
            start, end = sent, sent + len(block) - 1
            put_req = request.Request(
                upload_url, data=block, method="PUT",
                headers={"Content-Type": "video/mp4", "Content-Length": str(len(block)),
                         "Content-Range": f"bytes {start}-{end}/{size}"},
            )
            expected = 201 if index == chunk_count - 1 else 206
            try:
                with request.urlopen(put_req, timeout=180) as response:
                    put_status = response.status
                    if put_status != expected:
                        raise SafeTikTokError("upload", put_status, {"error": {
                            "code": "unexpected_upload_status", "message": f"Expected HTTP {expected}"}},
                            response.headers.get("Content-Type", ""))
            except error.HTTPError as exc:
                raw = exc.read()
                try: payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError: payload = {}
                raise SafeTikTokError("upload", exc.code, payload, exc.headers.get("Content-Type", "")) from None
            sent += len(block)
    persisted.update({"status": "uploaded", "bytes_sent": sent, "upload_host": host,
                      "updated_at": datetime.now(timezone.utc).isoformat()})
    persist_upload(persisted)
    status_req = request.Request(
        STATUS_URL, data=json.dumps({"publish_id": publish_id}).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
    )
    status_http, status_payload, _ = safe_api("status", status_req)
    remote = str((status_payload.get("data") or {}).get("status") or "UNKNOWN")
    persisted.update({"status": "processing", "remote_status": remote,
                      "updated_at": datetime.now(timezone.utc).isoformat()})
    persist_upload(persisted)
    report.update({"init_http": init_status, "put_http": 201, "status_http": status_http,
                   "publish_id_masked": f"{publish_id[:6]}...{publish_id[-4:]}",
                   "bytes_sent": sent, "remote_status": remote, "upload_host": host})
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", type=Path)
    parser.add_argument("--publication-key", required=True)
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(diagnose_tiktok_upload(args.asset, args.publication_key, args.no_upload), ensure_ascii=False))
    except SafeTikTokError as exc:
        print(json.dumps(exc.report, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
