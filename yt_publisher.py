from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


# Plugin YouTube do auto-post (YouTube Data API v3, gratuita).
# Sub-etapa A: monta os metadados reais (titulo/descricao/tags) a partir do
# publish.json e simula o post em dry-run. O upload real (OAuth + resumable
# upload) entra na sub-etapa C; ate la, tentar postar sem --post-dry-run
# registra erro claro no json e o pipeline segue.
#
# As dependencias do Google (google-api-python-client, google-auth-oauthlib)
# so serao importadas dentro do caminho de upload real: quem roda dry-run ou
# nao usa a flag nao precisa delas instaladas.

TITULO_MAX_CHARS = 100
TAGS_MAX_TOTAL_CHARS = 400  # limite oficial ~500; folga para nao tomar 400 da API
SHORTS_TAG = "#shorts"

# categoryId oficial do YouTube: 20=Gaming, 17=Sports, 24=Entertainment.
CATEGORIA_POR_NICHO = {"gta": "20", "football": "17"}
CATEGORIA_DEFAULT = "24"

DESTINOS = ("horizontal", "vertical")


def _sanitizar_titulo(text: str) -> str:
    # YouTube rejeita "<" e ">" no titulo; corta em palavra ate 100 chars.
    cleaned = text.replace("<", "").replace(">", "").strip()
    if len(cleaned) > TITULO_MAX_CHARS:
        cut = cleaned[: TITULO_MAX_CHARS - 3]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        cleaned = cut.rstrip(".,;:!?") + "..."
    return cleaned


def montar_titulo(registro: dict, destino: str) -> str:
    legenda = (registro.get("legenda") or "").strip() or "CORTE DA LIVE"
    streamer = (registro.get("credito_streamer") or "").strip()
    sufixo = f" {SHORTS_TAG}" if destino == "vertical" else ""
    titulo = f"{legenda} | {streamer}{sufixo}" if streamer else f"{legenda}{sufixo}"
    if destino == "vertical" and SHORTS_TAG not in _sanitizar_titulo(titulo):
        # Legenda longa engoliu o #shorts no truncamento: garante a tag
        # encurtando a legenda, nunca o contrario.
        base = f" | {streamer}{sufixo}" if streamer else sufixo
        titulo = legenda[: TITULO_MAX_CHARS - len(base)].rstrip() + base
    return _sanitizar_titulo(titulo)


def montar_descricao(registro: dict, destino: str) -> str:
    linhas = [(registro.get("legenda") or "").strip() or "Corte da live."]
    streamer = (registro.get("credito_streamer") or "").strip()
    canal = (registro.get("credito_canal") or "").strip()
    if streamer:
        linhas.append("")
        linhas.append(f"Creditos: {streamer}")
    if canal:
        linhas.append(f"Siga: {canal}")
    hashtags = list(registro.get("hashtags") or [])
    if destino == "vertical" and SHORTS_TAG not in hashtags:
        hashtags.append(SHORTS_TAG)
    if hashtags:
        linhas.append("")
        linhas.append(" ".join(hashtags))
    return "\n".join(linhas)


def montar_tags(registro: dict) -> list[str]:
    tags: list[str] = []
    total = 0
    candidatas = [tag.lstrip("#") for tag in (registro.get("hashtags") or [])]
    streamer = (registro.get("credito_streamer") or "").lstrip("@").strip()
    if streamer:
        candidatas.append(streamer)
    nicho = (registro.get("nicho") or "").strip()
    if nicho:
        candidatas.append(nicho)
    for tag in candidatas:
        if not tag or tag in tags:
            continue
        if total + len(tag) > TAGS_MAX_TOTAL_CHARS:
            break
        tags.append(tag)
        total += len(tag)
    return tags


def montar_metadados(registro: dict, destino: str, visibilidade: str) -> dict:
    """Corpo do post no YouTube para um destino (horizontal ou vertical)."""
    return {
        "titulo": montar_titulo(registro, destino),
        "descricao": montar_descricao(registro, destino),
        "tags": montar_tags(registro),
        "categoria_id": CATEGORIA_POR_NICHO.get(registro.get("nicho") or "", CATEGORIA_DEFAULT),
        "visibilidade": visibilidade,
        "made_for_kids": False,
    }


def _video_path(registro: dict, destino: str) -> Optional[Path]:
    raw = registro.get(destino)
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _upload(video_path: Path, metadados: dict, conta: str) -> dict:
    # Sub-etapa C: OAuth (token em .tokens/youtube/<conta>.json) + upload
    # resumavel via google-api-python-client, com import lazy aqui dentro.
    raise RuntimeError(
        "upload real do YouTube ainda nao implementado (sub-etapa C); "
        "use --post-dry-run por enquanto"
    )


def postar_corte_registro(registro: dict, config) -> dict:
    """Contrato do plugin (ver social_publisher): posta horizontal + vertical.

    Erro em um destino nao bloqueia o outro; cada destino carrega seu proprio
    resultado ou erro. Horizontal e vertical vao para o MESMO canal (config.conta)
    nesta etapa; separar por destino e evolucao futura do SocialConfig.
    """
    resultado: dict = {"erro": None}
    for destino in DESTINOS:
        video_path = _video_path(registro, destino)
        if video_path is None:
            motivo = registro.get("vertical_erro") if destino == "vertical" else None
            resultado[destino] = {"pulado": motivo or f"arquivo {destino} inexistente"}
            continue
        metadados = montar_metadados(registro, destino, config.visibilidade)
        if config.dry_run:
            resultado[destino] = {
                "simulado": True,
                "video_id": None,
                "url": None,
                "arquivo": str(video_path),
                "metadados": metadados,
            }
            continue
        try:
            upload = _upload(video_path, metadados, config.conta)
            resultado[destino] = {
                "simulado": False,
                "video_id": upload.get("video_id"),
                "url": upload.get("url"),
                "arquivo": str(video_path),
                "metadados": metadados,
            }
        except Exception as exc:
            resultado[destino] = {"erro": str(exc), "arquivo": str(video_path)}
            resultado["erro"] = str(exc)
    return resultado


if __name__ == "__main__":
    import argparse
    import json

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="Mostra os metadados de YouTube que um publish.json geraria (sem postar)."
    )
    parser.add_argument("publish_json", help="Caminho de um *_publish.json.")
    parser.add_argument("--visibilidade", default="unlisted")
    args = parser.parse_args()

    registro = json.loads(Path(args.publish_json).read_text(encoding="utf-8"))
    for destino in DESTINOS:
        print(f"--- {destino} ---")
        print(json.dumps(montar_metadados(registro, destino, args.visibilidade), ensure_ascii=False, indent=4))
