"""Fila de download em massa.

Reaproveita o yt-dlp que o BotLive ja tem (requirements.txt) - o documento e
explicito em nao criar um segundo sistema para a mesma coisa. A resolucao do
comando cai para "python -m yt_dlp" quando o executavel nao esta no PATH,
que e o caso na maquina do Glauber.

A fila e por item: um link que falha nao derruba o lote, fica em `failed` com
o motivo e pode ser retentado sozinho.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import fontes, projetos
from .store import MassaError, agora, atualizar, auditar, conectar, contar, inserir, listar, obter


TIMEOUT_ITEM = int(os.getenv("MASS_DOWNLOAD_TIMEOUT", "900"))
MAX_TENTATIVAS = int(os.getenv("MASS_DOWNLOAD_TENTATIVAS", "3"))


def comando_base() -> list:
    """yt-dlp como lista de argumentos, com fallback para o modulo Python."""
    caminho = shutil.which("yt-dlp")
    if caminho:
        return [caminho]
    import importlib.util

    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    raise MassaError("yt-dlp indisponivel. Instale com: python -m pip install yt-dlp")


def _cookies() -> list:
    arquivo = os.getenv("MASS_COOKIES_FILE", "").strip()
    if arquivo and Path(arquivo).is_file():
        return ["--cookies", arquivo]
    return []


def enfileirar(projeto_id: str, urls: list) -> dict:
    """Coloca as URLs na fila. Link repetido no mesmo projeto e ignorado."""
    projeto = projetos.exigir(projeto_id)
    novos, repetidos = [], 0
    for url in urls:
        plataforma = fontes.detectar(url)
        try:
            item = inserir("mass_downloads", {
                "projeto_id": projeto["id"],
                "url": url,
                "plataforma": plataforma.nome,
                "status": "queued",
                "created_at": agora(),
            })
            novos.append(item["id"])
        except Exception:
            repetidos += 1  # UNIQUE(projeto_id,url): ja estava na fila
    auditar("download.enfileirado", "projeto", projeto_id,
            {"novos": len(novos), "repetidos": repetidos})
    return {"enfileirados": len(novos), "repetidos": repetidos, "ids": novos}


def listar_perfil(url: str, limite: int = 0) -> dict:
    """Lista os videos de um perfil/pagina sem baixar nada.

    limite=0 traz tudo. Serve para a tela mostrar a lista com caixinhas antes
    de o operador escolher o que quer.
    """
    comando = [*comando_base(), "--flat-playlist", "--dump-json", "--ignore-errors"]
    if limite and limite > 0:
        comando += ["--playlist-end", str(limite)]
    comando += [*_cookies(), url]

    processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT_ITEM)
    itens = []
    for linha in processo.stdout.splitlines():
        try:
            dado = json.loads(linha)
        except json.JSONDecodeError:
            continue
        itens.append({
            "id": dado.get("id"),
            "titulo": dado.get("title") or "",
            "url": dado.get("url") or dado.get("webpage_url") or "",
            "duracao": dado.get("duration"),
        })
    if not itens and processo.returncode != 0:
        raise MassaError(f"nao consegui listar o perfil: {processo.stderr[-300:].strip()}")
    return {"total": len(itens), "itens": itens, "plataforma": fontes.detectar(url).nome}


def _sonda(caminho: Path) -> dict:
    """ffprobe do proprio BotLive - metadado nao pode travar o fluxo."""
    comando = [
        os.getenv("MASS_FFPROBE", "ffprobe"), "-v", "error",
        "-show_streams", "-show_format", "-of", "json", str(caminho),
    ]
    try:
        dados = json.loads(subprocess.run(
            comando, capture_output=True, text=True, check=True, timeout=60
        ).stdout)
    except Exception:
        return {}
    video = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})
    formato = dados.get("format", {})
    return {
        "largura": int(video.get("width") or 0),
        "altura": int(video.get("height") or 0),
        "duracao": round(float(formato.get("duration") or 0), 2),
    }


def baixar_item(download_id: str) -> dict:
    """Baixa um item da fila. Nunca levanta: falha vira status + motivo."""
    item = obter("mass_downloads", download_id)
    if not item:
        raise MassaError("Item de download inexistente")
    if item["status"] in {"completed", "cancelled"}:
        return item

    projeto = projetos.exigir(item["projeto_id"])
    destino = projetos.pasta_de(projeto, "downloads") / item["plataforma"]
    destino.mkdir(parents=True, exist_ok=True)

    atualizar("mass_downloads", download_id,
              {"status": "running", "tentativas": int(item["tentativas"]) + 1})

    comando = [
        *comando_base(),
        "--no-playlist",
        "--no-overwrites",
        "--restrict-filenames",
        "--merge-output-format", "mp4",
        "--print-json",
        "-o", str(destino / "%(id)s.%(ext)s"),
        *_cookies(),
        item["url"],
    ]
    try:
        processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT_ITEM)
    except subprocess.TimeoutExpired:
        return atualizar("mass_downloads", download_id,
                         {"status": "failed", "erro": "tempo esgotado no download"})

    if processo.returncode != 0:
        return atualizar("mass_downloads", download_id, {
            "status": "failed",
            "erro": (processo.stderr or "")[-300:].strip() or "yt-dlp falhou",
        })

    info, arquivo = {}, None
    for linha in processo.stdout.splitlines():
        try:
            info = json.loads(linha)
            break
        except json.JSONDecodeError:
            continue
    candidato = info.get("_filename") or info.get("filepath")
    if candidato and Path(candidato).is_file():
        arquivo = Path(candidato)
    else:
        recentes = sorted(destino.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        arquivo = recentes[0] if recentes else None

    if not arquivo:
        return atualizar("mass_downloads", download_id,
                         {"status": "failed", "erro": "arquivo nao encontrado apos o download"})

    from hashlib import sha256 as _sha

    digest = _sha()
    with arquivo.open("rb") as stream:
        for bloco in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(bloco)

    medida = _sonda(arquivo)
    return atualizar("mass_downloads", download_id, {
        "status": "completed",
        "arquivo": str(arquivo),
        "sha256": digest.hexdigest(),
        "titulo": (info.get("title") or "")[:200],
        "autor": (info.get("uploader") or info.get("channel") or "")[:120],
        "tamanho_bytes": arquivo.stat().st_size,
        "duracao": medida.get("duracao", 0),
        "largura": medida.get("largura", 0),
        "altura": medida.get("altura", 0),
        "erro": "",
        "baixado_em": agora(),
    })


def proximos(projeto_id: str, quantidade: int = 1) -> list:
    """Itens prontos para baixar, respeitando pausa e teto de tentativas."""
    with conectar() as db:
        linhas = db.execute(
            "SELECT * FROM mass_downloads WHERE projeto_id=? AND status='queued' "
            "AND tentativas < ? ORDER BY rowid LIMIT ?",
            (projeto_id, MAX_TENTATIVAS, max(1, quantidade)),
        ).fetchall()
    return [dict(x) for x in linhas]


def rodar_fila(projeto_id: str, maximo: int = 5) -> dict:
    """Processa ate `maximo` itens. Chamado pela interface ou por um worker."""
    projetos.exigir(projeto_id)
    processados = []
    for item in proximos(projeto_id, maximo):
        resultado = baixar_item(item["id"])
        processados.append({"id": item["id"], "status": resultado["status"],
                            "erro": resultado.get("erro", "")})
    return {"processados": len(processados), "itens": processados,
            "fila": contar("mass_downloads", "projeto_id=?", (projeto_id,))}


def mudar_status(download_id: str, status: str) -> dict:
    """Pausar, continuar, cancelar ou retentar um item."""
    permitidos = {"queued", "paused", "cancelled"}
    if status not in permitidos:
        raise MassaError(f"Status invalido: {status}. Use {sorted(permitidos)}")
    item = obter("mass_downloads", download_id)
    if not item:
        raise MassaError("Item inexistente")
    campos = {"status": status}
    if status == "queued":  # retry zera o motivo antigo
        campos["erro"] = ""
    return atualizar("mass_downloads", download_id, campos)


def fila(projeto_id: str, limite: int = 500) -> dict:
    return {
        "itens": listar("mass_downloads", limite, "projeto_id=?", (projeto_id,)),
        "resumo": contar("mass_downloads", "projeto_id=?", (projeto_id,)),
    }
