from __future__ import annotations
import hashlib, hmac, ipaddress, os, socket
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"https"}

def valid_token(candidate: str | None) -> bool:
    expected = os.getenv("CAMPAIGNS_LOCAL_TOKEN", "")
    return bool(expected and candidate and hmac.compare_digest(expected, candidate))

def safe_reference_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Somente URL HTTPS pública sem credenciais é permitida")
    for result in socket.getaddrinfo(parsed.hostname, parsed.port or 443):
        address = ipaddress.ip_address(result[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            raise ValueError("Destino privado ou reservado bloqueado")
    return value

def confined_path(root: Path, name: str) -> Path:
    clean = Path(name).name
    if not clean or clean in {".", ".."}:
        raise ValueError("Nome de arquivo inválido")
    target = (root / clean).resolve()
    if root.resolve() not in target.parents:
        raise ValueError("Caminho fora da área de mídia")
    return target

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
