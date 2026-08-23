"""Ponte entre a live do influenciador e o corte da campanha.

O buraco que isto fecha
-----------------------
O modulo so aceitava material subido a mao: alguem baixava a live, enviava o
arquivo e so entao o bot cortava. Numa campanha que dura 16 dias, com live
quase diaria, isso e trabalho humano todo dia - e era o que impedia o bot de
trabalhar sozinho.

Agora a campanha aponta para a FONTE (o canal do influenciador). O bot busca o
material de la, registra como material autorizado da campanha e o resto do
pipeline que ja existe segue igual: detectar, renderizar, validar contra as
regras, fila de revisao.

Autorizacao continua sendo declarada, nao presumida
--------------------------------------------------
Uma fonte so entra com `authorization_source` preenchido - o texto que diz por
que aquele acervo pode ser cortado (a campanha X autoriza cortes do canal Y).
Sem isso, nao registra. E a mesma regra do upload manual, que nao mudou.

Reaproveita o yt-dlp que o BotLive ja usa em outros modulos, com o mesmo
fallback para `python -m yt_dlp` quando o executavel nao esta no PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .store import ROOT, audit, connect, get, insert, now, rows, uid, update


REDES = ("twitch", "youtube", "kick", "instagram", "tiktok", "arquivo-direto")
TIMEOUT_BUSCA = int(os.getenv("CAMPAIGNS_FETCH_TIMEOUT", "1800"))
# Quantos VODs/lives novos buscar por rodada. Baixo de proposito: campanha nao
# precisa de tudo, precisa do que ainda nao foi cortado.
POR_RODADA = int(os.getenv("CAMPAIGNS_FETCH_POR_RODADA", "1"))


def comando_ytdlp() -> list:
    caminho = shutil.which("yt-dlp")
    if caminho:
        return [caminho]
    import importlib.util

    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    raise RuntimeError("yt-dlp indisponivel: instale com python -m pip install yt-dlp")


def _cookies() -> list:
    """Cookies do proprio dono, quando a fonte exige sessao.

    O YouTube barra IP de datacenter com "Sign in to confirm you're not a bot":
    listar funciona, baixar nao. A saida gratuita e exportar os cookies do
    navegador uma vez e apontar CAMPAIGNS_COOKIES_FILE para o arquivo.

    Nao e contorno de protecao: sao os cookies da conta do proprio operador,
    o mesmo que o yt-dlp documenta e o que o modulo de massa ja faz.
    """
    arquivo = os.getenv("CAMPAIGNS_COOKIES_FILE", "").strip()
    if arquivo and Path(arquivo).is_file():
        return ["--cookies", arquivo]
    return []


def pasta_da_campanha(campaign_id: str) -> Path:
    destino = Path(os.getenv("CAMPAIGNS_MEDIA_ROOT", ROOT / "data" / "media")) / campaign_id
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def registrar(campaign_id: str, network: str, url: str, influencer: str,
              authorization_source: str, notes: str = "") -> dict:
    """Liga uma fonte de conteudo a campanha.

    `authorization_source` e obrigatorio pelo mesmo motivo do upload: material
    sem origem declarada nao entra, e cortar canal alheio sem a campanha
    autorizar e o caminho para tomar strike.
    """
    campanha = get("campaign_campaigns", campaign_id)
    if not campanha:
        raise ValueError("Campanha inexistente")
    if network not in REDES:
        raise ValueError(f"Rede invalida: {network}. Use {list(REDES)}")
    if not (url or "").strip().startswith(("http://", "https://")):
        raise ValueError("URL da fonte precisa ser http(s)")
    if not (authorization_source or "").strip():
        raise ValueError("Fonte sem autorizacao declarada nao entra")

    existente = rows("campaign_sources", 1, 0, "campaign_id=? AND url=?", (campaign_id, url.strip()))
    if existente:
        return existente[0]

    item = insert("campaign_sources", {
        "campaign_id": campaign_id,
        "network": network,
        "url": url.strip(),
        "influencer": (influencer or "").strip()[:120],
        "authorization_source": authorization_source.strip(),
        "notes": notes,
        "enabled": 1,
        "last_checked_at": None,
        "last_error": "",
        "created_at": now(),
    })
    audit("source.registered", "source", item["id"],
          {"campaign": campaign_id, "network": network})
    return item


def listar(campaign_id: str | None = None) -> list:
    if campaign_id:
        return rows("campaign_sources", 200, 0, "campaign_id=?", (campaign_id,))
    return rows("campaign_sources", 200, 0)


def alternar(source_id: str, enabled: bool) -> dict:
    fonte = get("campaign_sources", source_id)
    if not fonte:
        raise ValueError("Fonte inexistente")
    return update("campaign_sources", source_id, {"enabled": 1 if enabled else 0})


def _ja_baixado(campaign_id: str, video_id: str) -> bool:
    """Um VOD nunca e baixado duas vezes para a mesma campanha."""
    with connect() as db:
        linha = db.execute(
            "SELECT id FROM campaign_materials WHERE campaign_id=? AND metadata LIKE ? LIMIT 1",
            (campaign_id, f'%"video_id": "{video_id}"%'),
        ).fetchone()
    return bool(linha)


def listar_disponiveis(fonte: dict, limite: int = 5) -> list:
    """Lista o que existe na fonte sem baixar nada."""
    comando = [*comando_ytdlp(), "--flat-playlist", "--dump-json",
               "--playlist-end", str(max(1, limite)), "--ignore-errors",
               *_cookies(), fonte["url"]]
    processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT_BUSCA)
    achados = []
    for linha in processo.stdout.splitlines():
        try:
            dado = json.loads(linha)
        except json.JSONDecodeError:
            continue
        achados.append({
            "video_id": str(dado.get("id") or ""),
            "titulo": dado.get("title") or "",
            "url": dado.get("url") or dado.get("webpage_url") or "",
            "duracao": dado.get("duration"),
        })
    achados = [x for x in achados if x["video_id"]]
    # Sem isto, canal que nao existe, video removido ou bloqueio de IP voltavam
    # como lista vazia - e a fonte era marcada "nada novo", escondendo a falha.
    # Custou uma investigacao inteira: o erro real era um ID digitado errado.
    if not achados and processo.returncode != 0:
        motivo = (processo.stderr or "").strip().splitlines()
        detalhe = next((x for x in reversed(motivo) if x.startswith("ERROR")), "")
        raise RuntimeError(detalhe[:300] or f"yt-dlp saiu com codigo {processo.returncode}")
    return achados


def buscar(source_id: str, limite: int = POR_RODADA) -> dict:
    """Baixa o que ainda nao foi cortado e registra como material da campanha.

    Devolve os materiais criados. Falha vira `last_error` na fonte - uma fonte
    ruim nao pode derrubar as outras campanhas.
    """
    fonte = get("campaign_sources", source_id)
    if not fonte:
        raise ValueError("Fonte inexistente")
    if not int(fonte["enabled"]):
        return {"materiais": [], "motivo": "fonte desativada"}

    campanha = get("campaign_campaigns", fonte["campaign_id"])
    if not campanha or campanha["status"] == "archived":
        return {"materiais": [], "motivo": "campanha arquivada"}

    try:
        disponiveis = listar_disponiveis(fonte, limite=max(5, limite * 3))
    except Exception as erro:
        update("campaign_sources", source_id,
               {"last_error": str(erro)[:300], "last_checked_at": now()})
        return {"materiais": [], "motivo": f"falha ao listar: {erro}"}

    novos = [x for x in disponiveis if not _ja_baixado(fonte["campaign_id"], x["video_id"])]
    if not novos:
        update("campaign_sources", source_id, {"last_checked_at": now(), "last_error": ""})
        return {"materiais": [], "motivo": "nada novo na fonte"}

    destino_base = pasta_da_campanha(fonte["campaign_id"])
    criados = []
    for item in novos[:max(1, limite)]:
        alvo = destino_base / f"{item['video_id']}.mp4"
        comando = [
            *comando_ytdlp(), "--no-playlist", "--no-overwrites",
            "--merge-output-format", "mp4", "--restrict-filenames",
            *_cookies(),
            "-o", str(alvo), item["url"] or fonte["url"],
        ]
        processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT_BUSCA)
        if processo.returncode != 0 or not alvo.exists():
            update("campaign_sources", source_id, {
                "last_error": (processo.stderr or "")[-300:].strip() or "download falhou",
                "last_checked_at": now(),
            })
            continue

        from hashlib import sha256 as _sha

        digest = _sha()
        with alvo.open("rb") as stream:
            for bloco in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(bloco)

        material = insert("campaign_materials", {
            "campaign_id": fonte["campaign_id"],
            "name": (item["titulo"] or item["video_id"])[:160],
            "source_url": item["url"] or fonte["url"],
            "stored_name": alvo.name,
            "local_path": str(alvo),
            "sha256": digest.hexdigest(),
            "declared_mime": "video/mp4",
            "detected_mime": "video/mp4",
            "size_bytes": alvo.stat().st_size,
            # A autorizacao vem da fonte, que so existe com ela declarada.
            "authorized": 1,
            "authorization_source": fonte["authorization_source"],
            "rights_notes": f"capturado da fonte {fonte['network']} de {fonte['influencer'] or 'canal'}",
            "expires_at": None,
            "status": "validated",
            "metadata": json.dumps({
                "video_id": item["video_id"],
                "source_id": source_id,
                "duracao": item.get("duracao"),
            }, ensure_ascii=False),
            "created_at": now(),
        })
        criados.append(material)
        audit("material.captured", "material", material["id"],
              {"source": source_id, "video_id": item["video_id"]})

    update("campaign_sources", source_id, {"last_checked_at": now(), "last_error": ""})
    return {"materiais": criados, "motivo": ""}


def fontes_para_checar(limite: int = 5) -> list:
    """Fontes ativas de campanhas ativas, mais antigas primeiro."""
    with connect() as db:
        linhas = db.execute(
            "SELECT s.* FROM campaign_sources s "
            "JOIN campaign_campaigns c ON c.id = s.campaign_id "
            "WHERE s.enabled=1 AND c.status IN ('active','draft') "
            "ORDER BY COALESCE(s.last_checked_at,'') ASC LIMIT ?",
            (max(1, limite),),
        ).fetchall()
    return [dict(x) for x in linhas]
