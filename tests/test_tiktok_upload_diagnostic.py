from pathlib import Path

from tiktok_upload_diagnostic import chunk_geometry, file_sha256


def test_real_size_geometry_uses_64mb_then_remainder(tmp_path: Path) -> None:
    size = 78_748_000
    chunk, count = chunk_geometry(size)
    assert chunk == 64 * 1024 * 1024
    assert count == 2
    assert 5 * 1024 * 1024 <= size - chunk <= 64 * 1024 * 1024


def test_small_and_medium_files_use_one_exact_chunk() -> None:
    for size in (1_000_000, 30_567_100, 64 * 1024 * 1024):
        assert chunk_geometry(size) == (size, 1)


def test_hash_streams_file(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"raw-video-bytes")
    assert file_sha256(path) == "bacd9276c14dcb3a68ad966559e3ca40c7e5f0c159155ba5fa687684a33de60b"


def test_diagnostic_source_has_exact_headers_and_persists_before_put() -> None:
    source = Path("tiktok_upload_diagnostic.py").read_text(encoding="utf-8")
    assert "persist_upload(persisted)" in source
    assert source.index("persist_upload(persisted)") < source.index('method="PUT"')
    assert '"Content-Length": str(len(block))' in source
    assert '"Content-Range": f"bytes {start}-{end}/{size}"' in source
    assert "post_info" not in source
    assert "/v2/post/publish/inbox/video/init/" in source
