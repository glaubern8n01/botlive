from __future__ import annotations

from pathlib import Path

from feature_flags import FeatureFlags
from kwai_publisher import KwaiPublisher
from publisher_contract import PlatformAccount, PublishJob, PublishStatus


def _job(tmp_path: Path, mode: str, options=None, secret_ref=None) -> PublishJob:
    asset = tmp_path / "asset.mp4"
    asset.write_bytes(b"video")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"jpg")
    return PublishJob(
        job_id="job",
        profile_id="profile",
        platform="kwai",
        account=PlatformAccount(
            "account",
            "kwai",
            "principal",
            secret_ref=secret_ref,
            mode=mode,
            options=options or {},
        ),
        asset_path=asset,
        cover_path=cover,
        publication_key="key",
        caption="Caption",
    )


def test_kwai_dry_run_never_calls_api(tmp_path: Path) -> None:
    class NoNetwork:
        def json_post(self, *_args, **_kwargs):
            raise AssertionError("network must not be called")

    publisher = KwaiPublisher(FeatureFlags(kwai=True), NoNetwork())
    result = publisher.publish(_job(tmp_path, "dry_run"), {})
    assert result.status == PublishStatus.PENDING
    assert result.remote_status == "dry_run"


def test_kwai_prepare_only_returns_complete_package(tmp_path: Path) -> None:
    publisher = KwaiPublisher(FeatureFlags(kwai=True))
    result = publisher.publish(_job(tmp_path, "prepare_only"), {})
    assert result.remote_status == "prepared"
    assert result.metadata["cover_path"].endswith("cover.jpg")
    assert result.metadata["caption"] == "Caption"


def test_kwai_api_requires_flags_authorization_scope_and_secret(tmp_path: Path) -> None:
    publisher = KwaiPublisher(FeatureFlags(kwai=True, kwai_api=False))
    validation = publisher.validate(_job(tmp_path, "api"))
    assert validation.valid is False
    assert any("KWAI_API_ENABLED" in error for error in validation.errors)
    assert any("scope" in error for error in validation.errors)


def test_kwai_api_uses_only_documented_upload_flow(tmp_path: Path) -> None:
    calls = []

    class FakeClient:
        def json_post(self, url, query, body=None, headers=None, timeout=60):
            calls.append((url, set(query)))
            if url.endswith("start_upload"):
                return {"result": 1, "upload_token": "upload", "endpoint": "upload.test"}
            return {
                "result": 1,
                "video_info": {"photo_id": "photo", "pending": True},
            }

        def upload_binary(self, endpoint, token, path):
            calls.append((endpoint, token, path.name))

    publisher = KwaiPublisher(FeatureFlags(kwai=True, kwai_api=True), FakeClient())
    job = _job(
        tmp_path,
        "api",
        {"official_api_authorized": True, "scopes": ["user_video_publish"]},
        "env:KWAI_TEST",
    )
    result = publisher.publish(job, {"app_id": "app", "access_token": "token"})
    assert result.external_id == "photo"
    assert result.status == PublishStatus.PROCESSING
    assert calls[0][0].endswith("/openapi/photo/start_upload")
    assert calls[-1][0].endswith("/openapi/photo/publish")


def test_kwai_status_does_not_guess_endpoint(tmp_path: Path) -> None:
    publisher = KwaiPublisher(FeatureFlags(kwai=True))
    job = _job(tmp_path, "prepare_only")
    result = publisher.get_status("photo", job.account, {})
    assert result.status == PublishStatus.UNKNOWN
    assert result.remote_status == "polling_endpoint_not_configured"
