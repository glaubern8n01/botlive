from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib import error, request

from publisher_contract import (
    AssetValidationError,
    AuthenticationError,
    PermanentPublishError,
    PlatformAccount,
    PublishJob,
    PublishResult,
    PublisherCapabilities,
    PublishStatus,
    RateLimitError,
    ValidationResult,
)
from tiktok_platform import TikTokPlatform

API_ROOT = "https://open.tiktokapis.com"
UPLOAD_INIT = "/v2/post/publish/inbox/video/init/"
DIRECT_INIT = "/v2/post/publish/video/init/"
CREATOR_INFO = "/v2/post/publish/creator_info/query/"
STATUS_FETCH = "/v2/post/publish/status/fetch/"
CANCEL = "/v2/post/publish/cancel/"
MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def upload_geometry(size: int) -> tuple[int, int]:
    if size <= 0 or size > MAX_FILE_SIZE:
        raise AssetValidationError("TikTok video size is outside the supported range")
    if size < MIN_CHUNK:
        return size, 1
    chunk_size = min(MAX_CHUNK, max(MIN_CHUNK, 10 * 1024 * 1024))
    count = size // chunk_size
    if size % chunk_size:
        count += 1
    return chunk_size, count


class TikTokStandardPublisher:
    platform = TikTokPlatform.STANDARD.value
    capabilities = PublisherCapabilities(
        accepts_video=True,
        accepts_cover=False,
        accepts_title=True,
        accepts_caption=True,
        min_duration_seconds=1,
        max_duration_seconds=600,
        aspect_ratios=("9:16",),
        max_file_size_bytes=MAX_FILE_SIZE,
        asynchronous_processing=True,
        supports_polling=True,
        supports_draft=True,
        privacy_options=(
            "PUBLIC_TO_EVERYONE",
            "MUTUAL_FOLLOW_FRIENDS",
            "FOLLOWER_OF_CREATOR",
            "SELF_ONLY",
        ),
    )

    def validate(self, job: PublishJob) -> ValidationResult:
        errors: list[str] = []
        path = Path(job.asset_path)
        if not path.is_file():
            errors.append("asset not found")
        elif path.suffix.lower() != ".mp4":
            errors.append("TikTok Standard requires an MP4 file")
        elif path.stat().st_size > MAX_FILE_SIZE:
            errors.append("asset exceeds TikTok's 4 GB maximum")
        if job.platform != self.platform or job.account.platform != self.platform:
            errors.append("job/account is not TikTok Standard")
        if job.account.options.get("rights_status") in {"blocked", "review_required"}:
            errors.append("content rights do not permit automatic progression")
        return ValidationResult(valid=not errors, errors=tuple(errors))

    def _api(self, path: str, token: str, body: Mapping[str, Any]) -> dict[str, Any]:
        req = request.Request(
            f"{API_ROOT}{path}",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                value = json.load(response)
        except error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimitError("TikTok rate limit exceeded") from exc
            if exc.code == 401:
                raise AuthenticationError("TikTok authorization is invalid") from exc
            raise PermanentPublishError(f"TikTok API request failed ({exc.code})") from exc
        api_error = value.get("error") or {}
        if api_error.get("code") not in {None, "", "ok"}:
            raise PermanentPublishError(f"TikTok API rejected request: {api_error.get('code')}")
        return value.get("data") or {}

    def query_creator_info(self, token: str) -> Mapping[str, Any]:
        return self._api(CREATOR_INFO, token, {})

    def initialize_upload_draft(self, token: str, size: int) -> Mapping[str, Any]:
        chunk_size, count = upload_geometry(size)
        return self._api(
            UPLOAD_INIT,
            token,
            {"source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": count,
            }},
        )

    def upload_media(self, upload_url: str, path: Path, chunk_size: int) -> None:
        total = path.stat().st_size
        with path.open("rb") as handle:
            start = 0
            while start < total:
                data = handle.read(chunk_size)
                end = start + len(data) - 1
                req = request.Request(
                    upload_url,
                    data=data,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    },
                    method="PUT",
                )
                try:
                    with request.urlopen(req, timeout=120) as response:
                        if response.status not in {201, 206}:
                            raise PermanentPublishError("TikTok rejected a media chunk")
                except error.HTTPError as exc:
                    raise PermanentPublishError(f"TikTok media upload failed ({exc.code})") from exc
                start = end + 1

    def initialize_direct_post(
        self, token: str, job: PublishJob, creator_info: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if not job.metadata.get("explicit_consent"):
            raise PermanentPublishError("explicit user consent is required")
        privacy = job.privacy
        allowed = tuple(creator_info.get("privacy_level_options") or ())
        if not privacy or privacy not in allowed:
            raise PermanentPublishError("select a privacy option returned by creator_info")
        disabled = creator_info
        duet = bool(job.metadata.get("allow_duet", False))
        stitch = bool(job.metadata.get("allow_stitch", False))
        comment = bool(job.metadata.get("allow_comment", False))
        if duet and disabled.get("duet_disabled"):
            raise PermanentPublishError("Duet is disabled for this account")
        if stitch and disabled.get("stitch_disabled"):
            raise PermanentPublishError("Stitch is disabled for this account")
        if comment and disabled.get("comment_disabled"):
            raise PermanentPublishError("comments are disabled for this account")
        size = Path(job.asset_path).stat().st_size
        chunk_size, count = upload_geometry(size)
        return self._api(
            DIRECT_INIT,
            token,
            {
                "post_info": {
                    "title": job.caption or job.title or "",
                    "privacy_level": privacy,
                    "disable_duet": not duet,
                    "disable_comment": not comment,
                    "disable_stitch": not stitch,
                    "video_cover_timestamp_ms": 1000,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": count,
                },
            },
        )

    def publish(self, job: PublishJob, secrets: Mapping[str, str]) -> PublishResult:
        validation = self.validate(job)
        if not validation.valid:
            raise AssetValidationError("; ".join(validation.errors))
        mode = job.account.mode
        if mode in {"dry_run", "prepare_only"}:
            return PublishResult(
                status=PublishStatus.PENDING,
                remote_status="ready",
                metadata={"mode": mode, "network_called": False},
            )
        if not _enabled("TIKTOK_STANDARD_API_ENABLED"):
            raise PermanentPublishError("TikTok Standard API is disabled")
        token = secrets.get("access_token")
        if not token:
            raise AuthenticationError("TikTok access token is unavailable")
        path = Path(job.asset_path)
        if mode == "upload_draft":
            if not _enabled("TIKTOK_STANDARD_UPLOAD_DRAFT_ENABLED"):
                raise PermanentPublishError("TikTok draft upload is disabled")
            init = self.initialize_upload_draft(token, path.stat().st_size)
        elif mode == "direct_post":
            if not _enabled("TIKTOK_STANDARD_DIRECT_POST_ENABLED"):
                raise PermanentPublishError("TikTok Direct Post is disabled")
            creator = self.query_creator_info(token)
            max_duration = int(creator.get("max_video_post_duration_sec") or 0)
            duration = float(job.metadata.get("duration_seconds") or 0)
            if max_duration and duration > max_duration:
                raise AssetValidationError("video exceeds creator_info duration limit")
            init = self.initialize_direct_post(token, job, creator)
        else:
            raise PermanentPublishError(f"unsupported TikTok mode: {mode}")
        upload_url = str(init.get("upload_url") or "")
        publish_id = str(init.get("publish_id") or "")
        if not upload_url or not publish_id:
            raise PermanentPublishError("TikTok did not return upload identifiers")
        chunk_size, _ = upload_geometry(path.stat().st_size)
        self.upload_media(upload_url, path, chunk_size)
        return PublishResult(
            status=PublishStatus.PROCESSING,
            external_id=publish_id,
            remote_status="uploaded",
            metadata={"mode": mode},
        )

    def get_status(
        self, external_id: str, account: PlatformAccount, secrets: Mapping[str, str]
    ) -> PublishResult:
        del account
        token = secrets.get("access_token")
        if not token:
            raise AuthenticationError("TikTok access token is unavailable")
        data = self._api(STATUS_FETCH, token, {"publish_id": external_id})
        remote = str(data.get("status") or "UNKNOWN")
        status = (
            PublishStatus.PUBLISHED if remote == "PUBLISH_COMPLETE"
            else PublishStatus.FAILED if remote == "FAILED"
            else PublishStatus.PROCESSING
        )
        post_ids = data.get("publicaly_available_post_id") or []
        return PublishResult(
            status=status,
            external_id=str(post_ids[0]) if post_ids else external_id,
            remote_status=remote,
            metadata={"uploaded_bytes": data.get("uploaded_bytes")},
        )

    def cancel(self, publish_id: str, token: str) -> None:
        self._api(CANCEL, token, {"publish_id": publish_id})
