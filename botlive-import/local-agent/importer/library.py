"""Biblioteca de midia importada.

Deduplicacao por SHA-256: o mesmo arquivo nao entra duas vezes, venha ele de
pasta local, upload ou download. Metadados saem do ffprobe; sem ffprobe o item
entra com metadado vazio e fica marcado, em vez de fingir que foi medido.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .sources import exigir_ativa
from .store import ImportError_, agora, conectar, inserir, listar, obter


EXTENSOES = {".mp4", ".mov", ".webm", ".mkv"}


def sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with Path(caminho).open("rb") as stream:
        for bloco in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def sondar(caminho: Path) -> dict:
    """Le metadados com ffprobe. Falha de sonda nao derruba a importacao."""
    comando = [
        os.getenv("IMPORT_FFPROBE", "ffprobe"),
        "-v", "error", "-show_streams", "-show_format", "-of", "json", str(caminho),
    ]
    try:
        bruto = subprocess.run(
            comando, capture_output=True, text=True, check=True,
            timeout=int(os.getenv("IMPORT_FFPROBE_TIMEOUT", "20")),
        ).stdout
        dados = json.loads(bruto)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {"probed": False}

    streams = dados.get("streams", [])
    video = next((x for x in streams if x.get("codec_type") == "video"), None)
    audio = next((x for x in streams if x.get("codec_type") == "audio"), None)
    formato = dados.get("format", {})
    if not video:
        raise ImportError_("Arquivo sem stream de video")
    return {
        "probed": True,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration_seconds": round(float(formato.get("duration") or video.get("duration") or 0), 3),
        "has_audio": bool(audio),
        "video_codec": video.get("codec_name") or "",
        "audio_codec": (audio or {}).get("codec_name") or "",
    }


def por_sha(digest: str) -> dict | None:
    with conectar() as db:
        linha = db.execute("SELECT * FROM import_items WHERE sha256=?", (digest,)).fetchone()
    return dict(linha) if linha else None


def registrar(source_id: str, caminho: str | Path, credit: str = "", origin_url: str = "") -> dict:
    """Coloca um arquivo ja presente no disco na biblioteca.

    Devolve o item existente quando o SHA-256 ja estiver na biblioteca - dois
    caminhos diferentes para o mesmo conteudo continuam sendo um item so.
    """
    fonte = exigir_ativa(source_id)
    arquivo = Path(caminho)
    if not arquivo.is_file():
        raise ImportError_(f"Arquivo inexistente: {arquivo}")
    if arquivo.suffix.lower() not in EXTENSOES:
        raise ImportError_(f"Extensao nao suportada: {arquivo.suffix}")
    if arquivo.stat().st_size <= 0:
        raise ImportError_("Arquivo vazio")

    digest = sha256(arquivo)
    existente = por_sha(digest)
    if existente:
        return existente

    metadados = sondar(arquivo)
    return inserir(
        "import_items",
        {
            "source_id": fonte["id"],
            "name": arquivo.name[:160],
            "local_path": str(arquivo.resolve()),
            "sha256": digest,
            "size_bytes": arquivo.stat().st_size,
            "mime": f"video/{arquivo.suffix.lstrip('.')}",
            "width": metadados.get("width", 0),
            "height": metadados.get("height", 0),
            "duration_seconds": metadados.get("duration_seconds", 0),
            "has_audio": 1 if metadados.get("has_audio") else 0,
            "origin_url": origin_url,
            "credit": credit or fonte["authorization_source"],
            "status": "library",
            "metadata": json.dumps(metadados, ensure_ascii=False),
            "created_at": agora(),
        },
    )


def importar_pasta(source_id: str, pasta: str | Path | None = None) -> dict:
    """Importacao em lote de uma pasta autorizada.

    Devolve contagem de importados, repetidos e recusados - com o motivo de
    cada recusa, em vez de falhar o lote inteiro por causa de um arquivo.
    """
    fonte = exigir_ativa(source_id)
    if fonte["kind"] not in {"local_folder", "upload"}:
        raise ImportError_("Esta fonte nao e de pasta local")
    raiz = Path(pasta or fonte["location"])
    if not raiz.is_dir():
        raise ImportError_(f"Pasta inexistente: {raiz}")

    importados, repetidos, recusados = [], [], []
    for arquivo in sorted(raiz.iterdir()):
        if not arquivo.is_file() or arquivo.suffix.lower() not in EXTENSOES:
            continue
        try:
            antes = por_sha(sha256(arquivo))
            item = registrar(source_id, arquivo)
            (repetidos if antes else importados).append(item["id"])
        except ImportError_ as erro:
            recusados.append({"arquivo": arquivo.name, "motivo": str(erro)})
    return {
        "source_id": source_id,
        "importados": len(importados),
        "repetidos": len(repetidos),
        "recusados": recusados,
        "item_ids": importados,
    }


def biblioteca(source_id: str | None = None, limite: int = 100) -> list:
    if source_id:
        return listar("import_items", limite, where="source_id=?", params=(source_id,))
    return listar("import_items", limite)


def exigir_item(item_id: str) -> dict:
    item = obter("import_items", item_id)
    if not item:
        raise ImportError_("Item inexistente")
    if not Path(item["local_path"]).is_file():
        raise ImportError_("Arquivo do item sumiu do disco")
    return item
