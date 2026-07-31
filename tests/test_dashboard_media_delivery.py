from pathlib import Path


SERVER = Path("dashboard/server.mjs").read_text(encoding="utf-8")
PRODUCER = Path("scripts/prepare_kwai_manual_batch.py").read_text(encoding="utf-8")


def test_dashboard_media_endpoint_supports_range_and_mobile_download() -> None:
    assert "'Accept-Ranges': 'bytes'" in SERVER
    assert "'Content-Range': `bytes ${start}-${end}/${info.size}`" in SERVER
    assert "'Content-Length': end - start + 1" in SERVER
    assert "'Content-Type': type" in SERVER
    assert "Content-Disposition" in SERVER
    assert "request.method === 'HEAD'" in SERVER


def test_legacy_asset_identifier_remains_addressable() -> None:
    assert "[0-9a-f]{11,12}" in SERVER
    assert "querySupabaseFlexibleId" in SERVER
    assert "String(row.asset_id) === String(value)" in SERVER
    assert "findMediaFile(job?.metadata?.download_filename)" in SERVER
    assert "findMediaFile(safeFilename(url.searchParams.get('name'), ''))" in SERVER


def test_producer_writes_only_under_configured_output_root() -> None:
    assert 'OUTPUT_ROOT = Path(os.getenv("BOTLIVE_OUTPUT_ROOT"' in PRODUCER
    assert 'READY_ROOT = OUTPUT_ROOT / "kwai_cut" / "ready"' in PRODUCER
    assert 'if video.exists()' in PRODUCER
    assert 'hashlib.sha256(work_video.read_bytes())' in PRODUCER
    assert 'work_video.replace(video)' in PRODUCER
