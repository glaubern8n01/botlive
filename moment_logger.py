from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


BASE_DIR = Path("D:/robo-cortes-dark")
QUEUE_FILE = BASE_DIR / "fila_local.jsonl"
MOMENT_EVENT = "moment_detected"


@dataclass(frozen=True)
class MomentRecord:
    id: str
    event: str
    source_url: str
    source_id: str
    timestamp_seconds: int
    score: float
    reason: str
    created_at: str
    status: str
    session_id: Optional[str] = None
    block_index: Optional[int] = None
    block_file: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_id_from_url(source_url: str) -> str:
    normalized = source_url.strip().lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def append_jsonl(payload: dict[str, Any]) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with QUEUE_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def salvar_momento(
    source_url: str,
    timestamp_seconds: int,
    score: float,
    reason: str,
    status: str = "detectado",
    session_id: Optional[str] = None,
    block_index: Optional[int] = None,
    block_file: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> MomentRecord:
    record = MomentRecord(
        id=str(uuid4()),
        event=MOMENT_EVENT,
        source_url=source_url,
        source_id=source_id_from_url(source_url),
        timestamp_seconds=int(timestamp_seconds),
        score=round(float(score), 4),
        reason=reason,
        created_at=utc_now(),
        status=status,
        session_id=session_id,
        block_index=block_index,
        block_file=block_file,
        metadata=metadata or {},
    )
    append_jsonl(asdict(record))
    return record


def _iter_jsonl() -> list[dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []

    rows: list[dict[str, Any]] = []
    with QUEUE_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def carregar_momentos(
    source_url: Optional[str] = None,
    source_id: Optional[str] = None,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[MomentRecord]:
    expected_source_id = source_id or (source_id_from_url(source_url) if source_url else None)
    moments: list[MomentRecord] = []

    for row in _iter_jsonl():
        if row.get("event") != MOMENT_EVENT:
            continue
        if expected_source_id and row.get("source_id") != expected_source_id:
            continue
        if session_id and row.get("session_id") != session_id:
            continue
        if status and row.get("status") != status:
            continue

        try:
            moments.append(
                MomentRecord(
                    id=str(row["id"]),
                    event=str(row.get("event", MOMENT_EVENT)),
                    source_url=str(row.get("source_url", "")),
                    source_id=str(row.get("source_id", "")),
                    timestamp_seconds=int(row["timestamp_seconds"]),
                    score=float(row.get("score", 0.0)),
                    reason=str(row.get("reason", "")),
                    created_at=str(row.get("created_at", "")),
                    status=str(row.get("status", "")),
                    session_id=row.get("session_id"),
                    block_index=row.get("block_index"),
                    block_file=row.get("block_file"),
                    metadata=row.get("metadata") or {},
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return sorted(moments, key=lambda item: item.created_at)


def listar_melhores_momentos(
    source_url: Optional[str] = None,
    source_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 8,
    min_gap_seconds: int = 45,
) -> list[MomentRecord]:
    moments = sorted(
        carregar_momentos(source_url=source_url, source_id=source_id, session_id=session_id),
        key=lambda item: item.score,
        reverse=True,
    )

    selected: list[MomentRecord] = []
    for moment in moments:
        if any(abs(moment.timestamp_seconds - kept.timestamp_seconds) < min_gap_seconds for kept in selected):
            continue
        selected.append(moment)
        if len(selected) >= limit:
            break

    return sorted(selected, key=lambda item: item.timestamp_seconds)
