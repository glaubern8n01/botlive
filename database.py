from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()

VALID_STATUSES = {"pendente", "processando", "concluido", "erro"}
TABLE_NAME = os.getenv("ROBO_SUPABASE_CLIPS_TABLE", "dark_gta_clips")
BASE_DIR = Path("D:/robo-cortes-dark")
LOCAL_QUEUE_FILE = BASE_DIR / "fila_local.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_client() -> Optional[Client]:
    url = os.getenv("ROBO_SUPABASE_URL")
    key = os.getenv("ROBO_SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Status invalido: {status}. Use um de: {sorted(VALID_STATUSES)}")


def _append_local(payload: Dict[str, Any]) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCAL_QUEUE_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def registrar_corte(
    live_url: str,
    peak_timestamp: int,
    keywords: Optional[list[str]] = None,
    messages_per_minute: Optional[int] = None,
    status: str = "pendente",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Registra uma tarefa de corte no Supabase, com fallback local em D:."""
    _validate_status(status)

    payload: Dict[str, Any] = {
        "live_url": live_url,
        "peak_timestamp": int(peak_timestamp),
        "keywords": keywords or [],
        "messages_per_minute": messages_per_minute,
        "status": status,
        "metadata": metadata or {},
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }

    client = _get_client()
    if client is None:
        payload["id"] = str(uuid4())
        payload["storage"] = "local_fallback"
        _append_local(payload)
        return payload

    response = client.table(TABLE_NAME).insert(payload).execute()
    if not response.data:
        raise RuntimeError("Supabase nao retornou dados ao registrar o corte.")
    return response.data[0]


def atualizar_status_corte(
    corte_id: str,
    status: str,
    output_path: Optional[str] = None,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Atualiza o status de uma tarefa de corte no Supabase, ou no log local."""
    _validate_status(status)

    payload: Dict[str, Any] = {
        "id": corte_id,
        "status": status,
        "updated_at": _utc_now(),
    }
    if output_path:
        payload["output_path"] = output_path
    if error_message:
        payload["error_message"] = error_message
    if metadata:
        payload["metadata"] = metadata

    client = _get_client()
    if client is None:
        payload["storage"] = "local_fallback"
        payload["event"] = "status_update"
        _append_local(payload)
        return payload

    update_payload = {key: value for key, value in payload.items() if key != "id"}
    response = client.table(TABLE_NAME).update(update_payload).eq("id", corte_id).execute()
    if not response.data:
        raise RuntimeError(f"Supabase nao encontrou o corte id={corte_id} para atualizar.")
    return response.data[0]


def marcar_processando(corte_id: str) -> Dict[str, Any]:
    return atualizar_status_corte(corte_id, "processando")


def marcar_concluido(corte_id: str, output_path: str) -> Dict[str, Any]:
    return atualizar_status_corte(corte_id, "concluido", output_path=output_path)


def marcar_erro(corte_id: str, error_message: str) -> Dict[str, Any]:
    return atualizar_status_corte(corte_id, "erro", error_message=error_message)
