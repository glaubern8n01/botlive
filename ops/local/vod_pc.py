"""Processa os VODs do vigia aqui no PC, em vez de na VPS.

Por que existe
--------------
Em 24/08/2026 a Hostinger ligou "Limitação de CPU" na VPS. A tabela de culpados
do painel deles apontou o comando exato: `main.py --modo vod-clips`, com dois
ffmpeg filhos a 76,8% e 66,6% analisando um VOD quadro a quadro. Esse job estava
rodando havia 28 horas - ele derrubou a CPU, a limitação o deixou 10x mais lento
e ele nunca terminava.

A captura da live é barata (`ffmpeg -c copy`) e continua na VPS. O que pesa é a
ANÁLISE do VOD, e é isso que vem para cá, onde não há teto de CPU nem cobrança
por uso. Mesmo desenho que já funcionou com as campanhas de corte.

Como funciona
-------------
A VPS continua sendo dona do registro: ela descobre a live, captura, e quando o
VOD aparece marca a linha como `waiting_vod` no Supabase. Este script pega as
linhas nesse estado, roda o MESMO comando que o vigia rodaria (montado por
`watcher.montar_comando_vod`, para os dois lados nunca divergirem) e devolve o
resultado para o mesmo registro.

Para não haver dois processando o mesmo VOD, `vod_mode_enabled` fica desligado
na `vigia_config`: o vigia da VPS deixa de despachar, mas continua marcando os
VODs que aparecem.

Uso
---
    python ops/local/vod_pc.py            # uma passada
    python ops/local/vod_pc.py --laco     # fica rodando, checa a cada 10 min
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from watcher import CONFIG_TABLE, STREAMS_TABLE, VigiaConfig, montar_comando_vod  # noqa: E402

# Estado próprio: o vigia da VPS varre órfãos procurando "running" e marcaria
# como failed um job que está saudável aqui. "running_pc" passa longe disso.
EM_ANDAMENTO = "running_pc"


def cliente():
    from supabase import create_client

    url = os.getenv("ROBO_SUPABASE_URL", "").strip()
    chave = os.getenv("ROBO_SUPABASE_KEY", "").strip()
    if not url or not chave:
        raise SystemExit("Faltam ROBO_SUPABASE_URL e ROBO_SUPABASE_KEY no ambiente")
    return create_client(url, chave)


def ler_config(client) -> VigiaConfig:
    linha = (client.table(CONFIG_TABLE).select("*").eq("id", 1).execute().data or [{}])[0]
    return VigiaConfig.from_row(linha)


def pode_postar() -> bool:
    """Só passa --post-youtube se o token da conta estiver aqui.

    Sem o arquivo, o `main.py` morreria no fim do processamento, jogando fora
    todo o trabalho de análise. Melhor render sem postar e o Glauber sobe o
    corte, do que perder a análise inteira.
    """
    return (REPO / ".tokens" / "youtube" / "principal.json").is_file()


def pendentes(client, config: VigiaConfig) -> list:
    linhas = (
        client.table(STREAMS_TABLE)
        .select("*")
        .eq("vod_job_status", "waiting_vod")
        .execute()
        .data
        or []
    )
    agora = datetime.now(timezone.utc)
    prontas = []
    for linha in linhas:
        if bool(linha.get("dry_run")):
            continue
        fim = linha.get("ended_at")
        if not fim:
            continue
        encerrada = datetime.fromisoformat(str(fim).replace("Z", "+00:00"))
        # A Twitch demora a publicar o VOD; o vigia sempre respeitou essa espera.
        if agora < encerrada + timedelta(minutes=config.vod_delay_minutes):
            continue
        prontas.append(linha)
    return prontas


def achar_vod(linha: dict) -> str | None:
    from twitch_api import TwitchHelix

    api = TwitchHelix()
    user_id = linha.get("channel_user_id") or api.get_user_id(linha["channel_login"])
    if not user_id:
        return None
    for video in api.get_videos_archive(str(user_id), first=10):
        if str(video.get("stream_id") or "") == str(linha["stream_id"]):
            return str(video["url"])
    return None


def processar(client, config: VigiaConfig, linha: dict, log) -> bool:
    stream_id = str(linha["stream_id"])
    vod_url = achar_vod(linha)
    if not vod_url:
        tentativas = int(linha.get("vod_attempts") or 0) + 1
        patch = {"vod_attempts": tentativas}
        if tentativas >= config.vod_max_attempts:
            patch["vod_job_status"] = "vod_unavailable"
            log(f"{linha['channel_login']}: VOD nunca apareceu, desistindo")
        client.table(STREAMS_TABLE).update(patch).eq("stream_id", stream_id).execute()
        return False

    postar = config.post_youtube_enabled and pode_postar()
    if config.post_youtube_enabled and not postar:
        log("aviso: token do YouTube nao esta neste PC; vou cortar sem postar")

    comando = montar_comando_vod(config, linha, vod_url, postar)
    client.table(STREAMS_TABLE).update(
        {"vod_job_status": EM_ANDAMENTO, "vod_url": vod_url}
    ).eq("stream_id", stream_id).execute()

    log(f"{linha['channel_login']}: processando {vod_url}")
    inicio = time.time()
    processo = subprocess.run(comando, cwd=str(REPO))
    minutos = (time.time() - inicio) / 60

    ok = processo.returncode == 0
    client.table(STREAMS_TABLE).update(
        {
            "vod_job_status": "done" if ok else "failed",
            "error_message": "" if ok else f"vod_pc: saiu com {processo.returncode}",
        }
    ).eq("stream_id", stream_id).execute()
    log(f"{linha['channel_login']}: {'pronto' if ok else 'FALHOU'} em {minutos:.0f} min")
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Roda os VODs do vigia neste PC")
    parser.add_argument("--laco", action="store_true", help="fica rodando")
    parser.add_argument("--intervalo", type=int, default=600)
    parser.add_argument("--max-por-rodada", type=int, default=1,
                        help="quantos VODs por passada; um de cada vez poupa a maquina")
    args = parser.parse_args(argv)

    def log(*mensagem):
        print(f"[vod-pc {datetime.now():%H:%M:%S}]", *mensagem, flush=True)

    client = cliente()
    while True:
        try:
            config = ler_config(client)
            fila = pendentes(client, config)
            if not fila:
                log("nenhum VOD esperando")
            for linha in fila[: max(1, args.max_por_rodada)]:
                processar(client, config, linha, log)
        except Exception as exc:  # uma falha nao pode matar o laco
            log(f"erro na rodada: {exc}")
        if not args.laco:
            return 0
        time.sleep(max(60, args.intervalo))


if __name__ == "__main__":
    raise SystemExit(main())
