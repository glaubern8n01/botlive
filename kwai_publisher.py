from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from PIL import Image
from moviepy.editor import VideoFileClip

from feature_flags import FeatureFlags
from publisher_contract import (
    AuthenticationError,
    PermanentPublishError,
    PlatformAccount,
    PublishJob,
    PublishResult,
    PublisherCapabilities,
    PublishStatus,
    RateLimitError,
    RetryablePublishError,
    ValidationResult,
)


OPEN_API = "https://open.kuaishou.com"
START_UPLOAD_PATH = "/openapi/photo/start_upload"
PUBLISH_PATH = "/openapi/photo/publish"
CHUNK_SIZE = 8 * 1024 * 1024


class KwaiHttpClient:
    def json_post(
        self,
        url: str,
        query: Mapping[str, str],
        body: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(query)}",
            data=body or b"",
            method="POST",
            headers=dict(headers or {}),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            if exc.code in {401, 403}:
                raise AuthenticationError("Kwai authorization rejected") from exc
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                raise RateLimitError(
                    "Kwai rate limit reached",
                    int(retry_after) if retry_after and retry_after.isdigit() else None,
                ) from exc
            if exc.code >= 500:
                raise RetryablePublishError(f"Kwai HTTP {exc.code}") from exc
            raise PermanentPublishError(f"Kwai HTTP {exc.code}: {message[:200]}") from exc
        except (OSError, TimeoutError) as exc:
            raise RetryablePublishError("Kwai network error") from exc
        if int(data.get("result", 0)) != 1:
            code = int(data.get("result", 0))
            message = str(data.get("error_msg") or "Kwai API error")
            if code == 100100402:
                raise RateLimitError(message)
            if code in {100120001, 100120002, 100120003, 100100400}:
                raise PermanentPublishError(message)
            raise RetryablePublishError(message)
        return data

    def upload_binary(self, endpoint: str, upload_token: str, path: Path) -> None:
        base = endpoint if endpoint.startswith(("http://", "https://")) else f"http://{endpoint}"
        size = path.stat().st_size
        if size <= CHUNK_SIZE:
            self.json_post(
                f"{base}/api/upload",
                {"upload_token": upload_token},
                path.read_bytes(),
                {"Content-Type": "video/mp4"},
                timeout=600,
            )
            return
        fragment_count = 0
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK_SIZE):
                self.json_post(
                    f"{base}/api/upload/fragment",
                    {"upload_token": upload_token, "fragment_id": str(fragment_count)},
                    chunk,
                    {"Content-Type": "video/mp4"},
                    timeout=600,
                )
                fragment_count += 1
        self.json_post(
            f"{base}/api/upload/complete",
            {"upload_token": upload_token, "fragment_count": str(fragment_count)},
        )


def ensure_cover(job: PublishJob) -> Path:
    if job.cover_path and job.cover_path.is_file():
        return job.cover_path
    output = job.asset_path.with_name(f"{job.asset_path.stem}_kwai_cover.jpg")
    clip = VideoFileClip(str(job.asset_path), audio=False)
    try:
        timestamp = min(1.0, max(0.0, float(clip.duration or 0) / 2))
        Image.fromarray(clip.get_frame(timestamp)).convert("RGB").save(
            output, "JPEG", quality=90
        )
    finally:
        clip.close()
    return output


def _multipart_cover(cover: Path, caption: str) -> tuple[bytes, str]:
    boundary = f"----BotLive{uuid4().hex}"
    mime = mimetypes.guess_type(cover.name)[0] or "image/jpeg"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode(),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"cover\"; "
            f"filename=\"{cover.name}\"\r\nContent-Type: {mime}\r\n\r\n"
        ).encode(),
        cover.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class KwaiPublisher:
    platform = "kwai"
    capabilities = PublisherCapabilities(
        accepts_cover=True,
        accepts_title=True,
        accepts_caption=True,
        aspect_ratios=("9:16",),
        asynchronous_processing=True,
        supports_polling=True,
        supports_draft=False,
        privacy_options=("public",),
    )

    def __init__(
        self,
        flags: Optional[FeatureFlags] = None,
        client: Optional[KwaiHttpClient] = None,
    ) -> None:
        self.flags = flags or FeatureFlags.from_env()
        self.client = client or KwaiHttpClient()

    def validate(self, job: PublishJob) -> ValidationResult:
        errors: list[str] = []
        if not self.flags.kwai:
            errors.append("KWAI_ENABLED is disabled")
        if not job.asset_path.is_file():
            errors.append("asset not found")
        if job.account.mode not in {"dry_run", "prepare_only", "api"}:
            errors.append("unsupported Kwai mode")
        if job.account.mode == "api":
            if not self.flags.kwai_api:
                errors.append("KWAI_API_ENABLED is disabled")
            if not job.account.options.get("official_api_authorized"):
                errors.append("official Kwai/Kuaishou API authorization is not confirmed")
            scopes = set(job.account.options.get("scopes") or ())
            if "user_video_publish" not in scopes:
                errors.append("user_video_publish scope is missing")
            if not job.account.secret_ref:
                errors.append("Kwai secret_ref is missing")
        return ValidationResult(not errors, tuple(errors))

    def publish(self, job: PublishJob, secrets: Mapping[str, str]) -> PublishResult:
        validation = self.validate(job)
        if not validation.valid:
            raise PermanentPublishError("; ".join(validation.errors))
        cover = ensure_cover(job)
        prepared = {
            "asset_path": str(job.asset_path),
            "cover_path": str(cover),
            "caption": job.caption or job.title or job.asset_path.stem,
            "mode": job.account.mode,
        }
        if job.account.mode == "dry_run":
            return PublishResult(
                status=PublishStatus.PENDING,
                remote_status="dry_run",
                metadata=prepared,
            )
        if job.account.mode == "prepare_only":
            return PublishResult(
                status=PublishStatus.PENDING,
                remote_status="prepared",
                metadata=prepared,
            )
        app_id = secrets.get("app_id")
        access_token = secrets.get("access_token")
        if not app_id or not access_token:
            raise AuthenticationError("Kwai app_id/access_token are not configured")
        started = self.client.json_post(
            f"{OPEN_API}{START_UPLOAD_PATH}",
            {"app_id": app_id, "access_token": access_token},
        )
        upload_token = str(started["upload_token"])
        self.client.upload_binary(str(started["endpoint"]), upload_token, job.asset_path)
        body, content_type = _multipart_cover(cover, prepared["caption"])
        published = self.client.json_post(
            f"{OPEN_API}{PUBLISH_PATH}",
            {
                "app_id": app_id,
                "access_token": access_token,
                "upload_token": upload_token,
            },
            body,
            {"Content-Type": content_type},
        )
        video_info = published.get("video_info") or {}
        photo_id = video_info.get("photo_id")
        if not photo_id:
            raise RetryablePublishError("Kwai publish response has no photo_id")
        pending = bool(video_info.get("pending", True))
        return PublishResult(
            status=PublishStatus.PROCESSING if pending else PublishStatus.PUBLISHED,
            external_id=str(photo_id),
            remote_url=video_info.get("play_url"),
            remote_status="pending" if pending else "published",
            metadata={"cover_path": str(cover)},
        )

    def get_status(
        self, external_id: str, account: PlatformAccount, secrets: Mapping[str, str]
    ) -> PublishResult:
        # A documentação pública confirma consulta por photo_id, mas o endpoint
        # REST varia por produto/contrato. Só chamamos uma URL explicitamente
        # fornecida no cadastro aprovado da conta; nunca inventamos endpoint.
        query_url = account.options.get("video_info_url")
        if not query_url:
            return PublishResult(
                status=PublishStatus.UNKNOWN,
                external_id=external_id,
                remote_status="polling_endpoint_not_configured",
            )
        app_id, token = secrets.get("app_id"), secrets.get("access_token")
        if not app_id or not token:
            raise AuthenticationError("Kwai status credentials are not configured")
        data = self.client.json_post(
            str(query_url),
            {"app_id": app_id, "access_token": token, "photo_id": external_id},
        )
        info = data.get("video_info") or {}
        pending = bool(info.get("pending", True))
        return PublishResult(
            status=PublishStatus.PROCESSING if pending else PublishStatus.PUBLISHED,
            external_id=external_id,
            remote_url=info.get("play_url"),
            remote_status="pending" if pending else "published",
        )
