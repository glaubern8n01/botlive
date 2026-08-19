"""Fontes autorizadas de importacao.

Uma fonte so entra com autorizacao declarada: quem autorizou, sob qual licenca
e com que observacao de direitos. Isso nao e burocracia - e o que separa
"adaptar material permitido" de "pegar video dos outros".

Download automatico (yt-dlp e afins) e um segundo interruptor, por fonte, e
so vale para fonte ja autorizada. Nada aqui remove marca d'agua, credito ou
protecao: material com protecao tecnica simplesmente nao e importavel.
"""

from __future__ import annotations

import os

from .store import ImportError_, agora, atualizar, inserir, listar, obter


TIPOS = ("local_folder", "upload", "url_list")
LICENCAS_CONHECIDAS = (
    "propria",
    "cc-by",
    "cc-by-sa",
    "cc0",
    "dominio-publico",
    "autorizacao-direta",
    "campanha",
)


def download_liberado_no_ambiente() -> bool:
    return os.getenv("IMPORT_ALLOW_DOWNLOAD", "false").strip().lower() == "true"


def criar(
    name: str,
    kind: str,
    location: str = "",
    channel_id: str = "",
    authorized: bool = False,
    authorization_source: str = "",
    license: str = "",
    rights_notes: str = "",
    allow_download: bool = False,
) -> dict:
    if kind not in TIPOS:
        raise ImportError_(f"Tipo de fonte invalido: {kind}. Use {list(TIPOS)}")
    if not (name or "").strip():
        raise ImportError_("Nome da fonte obrigatorio")
    if not authorized:
        raise ImportError_("Fonte precisa ser marcada como autorizada")
    if not (authorization_source or "").strip():
        raise ImportError_("Descreva quem autorizou o uso do material")
    if license not in LICENCAS_CONHECIDAS:
        raise ImportError_(f"Licenca desconhecida: {license}. Use {list(LICENCAS_CONHECIDAS)}")
    if kind == "url_list" and not location.strip():
        raise ImportError_("Fonte de URLs precisa da lista de origem")

    stamp = agora()
    return inserir(
        "import_sources",
        {
            "name": name.strip(),
            "kind": kind,
            "location": location.strip(),
            "channel_id": channel_id,
            "authorized": 1,
            "authorization_source": authorization_source.strip(),
            "license": license,
            "rights_notes": rights_notes,
            "allow_download": 1 if allow_download else 0,
            "status": "active",
            "created_at": stamp,
            "updated_at": stamp,
        },
    )


def arquivar(source_id: str) -> dict:
    if not obter("import_sources", source_id):
        raise ImportError_("Fonte inexistente")
    return atualizar(
        "import_sources", source_id, {"status": "archived", "updated_at": agora()}
    )


def exigir_ativa(source_id: str) -> dict:
    fonte = obter("import_sources", source_id)
    if not fonte:
        raise ImportError_("Fonte inexistente")
    if fonte["status"] != "active":
        raise ImportError_("Fonte arquivada")
    if not fonte["authorized"]:
        raise ImportError_("Fonte sem autorizacao registrada")
    return fonte


def exigir_download_permitido(fonte: dict) -> dict:
    """Dois interruptores: o do ambiente e o da fonte. Faltando um, nao baixa."""
    if not download_liberado_no_ambiente():
        raise ImportError_("Download desligado: defina IMPORT_ALLOW_DOWNLOAD=true")
    if not fonte.get("allow_download"):
        raise ImportError_("Esta fonte nao autoriza download automatico")
    return fonte


def ativas() -> list:
    return listar("import_sources", where="status=?", params=("active",))
