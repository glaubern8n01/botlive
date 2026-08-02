from __future__ import annotations

"""Plugin TikTok: envia o MP4 vertical para a caixa de entrada como rascunho.

Usa a Content Posting API / Upload to TikTok com o escopo ``video.upload``.
O usuário recebe uma notificação no aplicativo TikTok, abre o vídeo, edita e
publica manualmente. O plugin nunca publica diretamente no perfil.

Credencial esperada em ``.tokens/tiktok/<conta>.json``:
{
  "access_token": "...",
  "open_id": "...",
  "display_name": "opcional",
  "expires_at": "opcional"
}

O client secret nunca deve ser salvo no repositório.
"""

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


API_BASE = "https://open.tiktokapis.com"
INIT_ENDPOINT = f"{API_BASE}/v2/post/publish/inbox/video/init/"
STATUS_ENDPOINT = f"{API_BASE}/v2/post/publish/status/fetch/"
TOKENS_DIR = Path(__file__).resolve().parent / ".tokens" / "tiktok"
MAX_SINGLE_CHUNK = 64 * 1024 * 1024
DEFAULT_CHUNK = 32 * 1024 * 1024


def _token_path(conta: str) -> Path:
    return TOKENS_DIR / f"{conta}.json"


def _credenciais(conta: str) -> dict:
    path = _token_path(conta)
    if not path.is_file():
        raise RuntimeError(
            f"TikTok não autorizado para a conta {conta!r}; "
            f"salve o token em {path} com escopo video.upload"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError(f"access_token ausente em {path}")
    return data


def salvar_token(
    conta: str,
    access_token: str,
    open_id: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Path:
    """Importa um token já concedido pelo OAuth oficial do TikTok."""
    if not access_token.strip():
        raise RuntimeError("access_token vazio")
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    path = _token_path(conta)
    payload = {
        "access_token": access_token.strip(),
        "open_id": open_id,
        "display_name": display_name,
        "scope": "video.upload",
        "obtido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _json_request(url: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TikTok HTTP {exc.code}: {body}") from exc
    data = json.loads(body)
    error = data.get("error") or {}
    if error.get("code") not in (None, "", "ok"):
        raise RuntimeError(
            f"TikTok API {error.get('code')}: {error.get('message') or 'erro sem mensagem'}"
        )
    return data


def _plano_chunks(video_size: int) -> tuple[int, int]:
    if video_size <= 0:
        raise RuntimeError("arquivo de vídeo vazio")
    if video_size <= MAX_SINGLE_CHUNK:
        return video_size, 1
    chunk_size = DEFAULT_CHUNK
    total = (video_size + chunk_size - 1) // chunk_size
    return chunk_size, total


def _iniciar_upload(video_path: Path, token: str) -> tuple[str, str, int]:
    size = video_path.stat().st_size
    chunk_size, total_chunks = _plano_chunks(size)
    response = _json_request(
        INIT_ENDPOINT,
        token,
        {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            }
        },
    )
    data = response.get("data") or {}
    upload_url = data.get("upload_url")
    publish_id = data.get("publish_id")
    if not upload_url or not publish_id:
        raise RuntimeError(f"TikTok não retornou upload_url/publish_id: {response}")
    return str(upload_url), str(publish_id), chunk_size


def _enviar_arquivo(upload_url: str, video_path: Path, chunk_size: int) -> None:
    total = video_path.stat().st_size
    mime = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    offset = 0
    with video_path.open("rb") as stream:
        while offset < total:
            data = stream.read(chunk_size)
            if not data:
                break
            end = offset + len(data) - 1
            request = urllib.request.Request(upload_url, data=data, method="PUT")
            request.add_header("Content-Type", mime)
            request.add_header("Content-Length", str(len(data)))
            request.add_header("Content-Range", f"bytes {offset}-{end}/{total}")
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    status = int(response.status)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"TikTok upload HTTP {exc.code}: {body}") from exc
            if status not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload retornou HTTP {status}")
            offset = end + 1
    if offset != total:
        raise RuntimeError(f"upload incompleto: {offset}/{total} bytes")


def consultar_status(publish_id: str, conta: str = "principal") -> dict:
    token = _credenciais(conta)["access_token"]
    return _json_request(STATUS_ENDPOINT, token, {"publish_id": publish_id})


def _video_vertical(registro: dict) -> Path:
    raw = registro.get("vertical")
    if not raw:
        raise RuntimeError("publish.json não contém vídeo vertical")
    path = Path(raw)
    if not path.is_file():
        raise RuntimeError(f"vídeo vertical não encontrado: {path}")
    if path.suffix.lower() != ".mp4":
        raise RuntimeError("TikTok requer MP4 neste fluxo")
    return path


def postar_corte_registro(registro: dict, config) -> dict:
    """Contrato do social_publisher: cria um rascunho, nunca post direto."""
    video = _video_vertical(registro)
    if getattr(config, "dry_run", False):
        return {
            "tipo": "rascunho_inbox",
            "video": str(video),
            "publish_id": None,
            "status": "dry_run",
            "erro": None,
        }

    conta = getattr(config, "conta", "principal")
    creds = _credenciais(conta)
    token = creds["access_token"]
    upload_url, publish_id, chunk_size = _iniciar_upload(video, token)
    _enviar_arquivo(upload_url, video, chunk_size)
    return {
        "tipo": "rascunho_inbox",
        "video": str(video),
        "publish_id": publish_id,
        "status": "enviado_para_caixa_de_entrada",
        "conta_tiktok": creds.get("display_name") or creds.get("open_id"),
        "erro": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TikTok Upload: envia MP4 como rascunho.")
    sub = parser.add_subparsers(dest="comando", required=True)

    importar = sub.add_parser("salvar-token", help="Importa token OAuth com video.upload.")
    importar.add_argument("--conta", default="principal")
    importar.add_argument("--access-token", default=None)
    importar.add_argument("--open-id", default=None)
    importar.add_argument("--display-name", default=None)

    status = sub.add_parser("status", help="Consulta status de um envio.")
    status.add_argument("publish_id")
    status.add_argument("--conta", default="principal")

    args = parser.parse_args()
    if args.comando == "salvar-token":
        token = args.access_token or input("Cole o access token do TikTok: ").strip()
        path = salvar_token(args.conta, token, args.open_id, args.display_name)
        print(f"Token TikTok salvo com segurança em {path}")
    elif args.comando == "status":
        print(json.dumps(consultar_status(args.publish_id, args.conta), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    main()
