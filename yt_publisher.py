from __future__ import annotations

import json
import os
import sys
import time
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

# OAuth: o client secret (baixado do Google Cloud Console) e os refresh tokens
# vivem em .tokens/ (gitignored), ancorados na pasta do repo para funcionar de
# qualquer cwd. Um token por conta/canal: .tokens/youtube/<conta>.json.
# Fallback sem arquivo: YT_CLIENT_ID + YT_CLIENT_SECRET no .env.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
TOKENS_DIR = Path(__file__).resolve().parent / ".tokens" / "youtube"
CLIENT_SECRET_FILE_DEFAULT = TOKENS_DIR / "client_secret.json"


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass


def _token_path(conta: str) -> Path:
    return TOKENS_DIR / f"{conta}.json"


def _client_config() -> dict:
    """Config OAuth do app: arquivo client_secret.json ou YT_CLIENT_ID/SECRET do .env."""
    _carregar_dotenv()
    secret_file = Path(os.environ.get("YT_CLIENT_SECRET_FILE") or CLIENT_SECRET_FILE_DEFAULT)
    if secret_file.is_file():
        return json.loads(secret_file.read_text(encoding="utf-8"))
    client_id = os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("YT_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    raise RuntimeError(
        f"credenciais OAuth ausentes: coloque o client_secret.json em {CLIENT_SECRET_FILE_DEFAULT} "
        "ou defina YT_CLIENT_ID e YT_CLIENT_SECRET no .env"
    )


def autorizar(conta: str) -> Path:
    """Fluxo OAuth unico por conta: abre o navegador, salva o refresh token.

    Roda uma vez por conta/canal; depois o sistema renova o access token
    sozinho. App em modo Testing no Google Cloud -> refresh token expira em
    7 dias (publicar o app 'Em producao' resolve).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_client_config(), list(SCOPES))
    creds = flow.run_local_server(
        port=0,
        authorization_prompt_message="[yt-auth] abra o link no navegador se nao abrir sozinho:\n{url}",
        success_message="Autorizado! Pode fechar esta aba e voltar ao terminal.",
    )
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    token_path = _token_path(conta)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"[yt-auth] token da conta {conta!r} salvo em {token_path}")
    return token_path


def _credenciais(conta: str):
    """Carrega o token salvo e renova o access token se preciso. Erro aqui tem
    sempre instrucao clara de como resolver (reautorizar)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = _token_path(conta)
    ajuda = f"rode: python yt_publisher.py autorizar --conta {conta}"
    if not token_path.is_file():
        raise RuntimeError(f"conta {conta!r} nao autorizada ({token_path} inexistente); {ajuda}")
    creds = Credentials.from_authorized_user_file(str(token_path), list(SCOPES))
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"refresh token da conta {conta!r} invalido/expirado ({exc}); {ajuda}. "
                "Lembrete: app em modo Testing expira o token em 7 dias."
            ) from exc
    if not creds.valid:
        raise RuntimeError(f"credenciais da conta {conta!r} invalidas; {ajuda}")
    return creds


def _service(conta: str):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=_credenciais(conta), cache_discovery=False)


def testar_auth(conta: str) -> dict:
    """Prova a conexao listando o canal da conta (channels.list, 1 unidade de cota)."""
    response = (
        _service(conta)
        .channels()
        .list(part="snippet,statistics", mine=True)
        .execute()
    )
    itens = response.get("items") or []
    if not itens:
        raise RuntimeError(
            "nenhum canal encontrado nesta conta Google; confira se escolheu a conta/canal certo na autorizacao"
        )
    canal = itens[0]
    info = {
        "canal": canal["snippet"]["title"],
        "channel_id": canal["id"],
        "inscritos": canal["statistics"].get("subscriberCount"),
        "videos": canal["statistics"].get("videoCount"),
    }
    print(f"[yt-auth] conta {conta!r} conectada ao canal: {info['canal']}")
    print(f"[yt-auth] channel_id={info['channel_id']} inscritos={info['inscritos']} videos={info['videos']}")
    return info


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


# Cota do dia estourou nesta execucao: os proximos cortes nem tentam a API,
# so registram o motivo no json (a cota reseta a meia-noite PT).
_quota_bloqueada = False

_UPLOAD_TENTATIVAS = 3
_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_HTTP_RETRIAVEIS = {500, 502, 503, 504}
_MOTIVOS_COTA = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded", "rateLimitExceeded"}


def _motivo_http(exc) -> str:
    """Extrai o 'reason' de um HttpError da API (ex.: quotaExceeded)."""
    try:
        for detail in exc.error_details or []:
            if detail.get("reason"):
                return str(detail["reason"])
    except Exception:
        pass
    return ""


def _upload(video_path: Path, metadados: dict, conta: str) -> dict:
    """Upload resumavel via videos.insert (~100 unidades de cota).

    Retenta ate 3x em erro 5xx/rede; cota estourada bloqueia novas tentativas
    na execucao inteira e levanta erro claro (quem contem e o social_publisher).
    """
    global _quota_bloqueada
    if _quota_bloqueada:
        raise RuntimeError("cota diaria do YouTube estourada nesta execucao; reseta a meia-noite PT")

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": metadados["titulo"],
            "description": metadados["descricao"],
            "tags": metadados["tags"],
            "categoryId": metadados["categoria_id"],
        },
        "status": {
            "privacyStatus": metadados["visibilidade"],
            "selfDeclaredMadeForKids": metadados["made_for_kids"],
        },
    }
    media = MediaFileUpload(
        str(video_path), mimetype="video/mp4", chunksize=_UPLOAD_CHUNK_BYTES, resumable=True
    )
    request = _service(conta).videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    tentativa = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"[yt-upload] {video_path.name}: {int(status.progress() * 100)}%")
            tentativa = 0
        except HttpError as exc:
            motivo = _motivo_http(exc)
            if motivo in _MOTIVOS_COTA:
                _quota_bloqueada = True
                raise RuntimeError(
                    f"cota do YouTube estourada ({motivo}); reseta a meia-noite PT, "
                    "reposte depois com: python social_publisher.py <pasta> --rede youtube"
                ) from exc
            if exc.resp.status in _HTTP_RETRIAVEIS and tentativa < _UPLOAD_TENTATIVAS:
                tentativa += 1
                espera = 2 ** tentativa
                print(f"[yt-upload] erro {exc.resp.status}, tentativa {tentativa}/{_UPLOAD_TENTATIVAS} em {espera}s")
                time.sleep(espera)
                continue
            raise RuntimeError(f"upload falhou (HTTP {exc.resp.status} {motivo}): {exc}") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            if tentativa < _UPLOAD_TENTATIVAS:
                tentativa += 1
                espera = 2 ** tentativa
                print(f"[yt-upload] erro de rede ({exc}), tentativa {tentativa}/{_UPLOAD_TENTATIVAS} em {espera}s")
                time.sleep(espera)
                continue
            raise RuntimeError(f"upload falhou apos {_UPLOAD_TENTATIVAS} tentativas de rede: {exc}") from exc

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    print(f"[yt-upload] {video_path.name} publicado ({metadados['visibilidade']}): {url}")
    return {"video_id": video_id, "url": url}


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

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Plugin YouTube do auto-post: OAuth e utilidades.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_auth = sub.add_parser("autorizar", help="Fluxo OAuth unico: abre o navegador e salva o refresh token.")
    p_auth.add_argument("--conta", default="principal", help="Nome do token em .tokens/youtube/<conta>.json.")

    p_teste = sub.add_parser("testar-auth", help="Lista o canal da conta para provar a conexao (1 unidade de cota).")
    p_teste.add_argument("--conta", default="principal")

    p_meta = sub.add_parser("metadados", help="Mostra os metadados que um publish.json geraria (sem postar).")
    p_meta.add_argument("publish_json", help="Caminho de um *_publish.json.")
    p_meta.add_argument("--visibilidade", default="unlisted")

    args = parser.parse_args()

    if args.comando == "autorizar":
        try:
            autorizar(args.conta)
        except Exception as exc:
            raise SystemExit(f"[yt-auth][falha] {exc}")
    elif args.comando == "testar-auth":
        try:
            testar_auth(args.conta)
        except Exception as exc:
            raise SystemExit(f"[yt-auth][falha] {exc}")
    else:
        registro = json.loads(Path(args.publish_json).read_text(encoding="utf-8"))
        for destino in DESTINOS:
            print(f"--- {destino} ---")
            print(json.dumps(montar_metadados(registro, destino, args.visibilidade), ensure_ascii=False, indent=4))
