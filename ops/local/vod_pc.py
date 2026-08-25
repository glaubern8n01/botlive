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

# A coluna vod_job_status tem CHECK no banco: valor inventado e recusado com
# "violates check constraint". Entao o estado e o mesmo "running" de sempre, e
# quem diz que o job e DESTE PC (e desde quando) e a marca no error_message.
#
# Efeito colateral conhecido: a varredura de orfaos do vigia marca como failed
# toda linha em "running" quando ele reinicia. Nao e grave - quem escreve o
# resultado final e este runner, no fim do processamento - mas e o motivo de a
# recuperacao aqui olhar a MARCA, e nao so o estado.
EM_ANDAMENTO = "running"
MARCA_DO_PC = "running_pc@"

# Quanto tempo um job pode ficar "running_pc" sem sinal de vida antes de ser
# considerado abandonado. Se o PC desligar no meio de um VOD, sem isso a linha
# ficava presa para sempre e aquele VOD nunca mais seria cortado. Generoso de
# propósito: um VOD longo leva bem mais de uma hora no PC.
HORAS_DE_ABANDONO = float(os.getenv("VOD_PC_HORAS_ABANDONO", "4"))


def _marca_de_posse() -> str:
    """Quem pegou o job e quando.

    Vai no `error_message`, que é texto livre e já aparece no painel: dá para
    ver de qual máquina o job é sem inventar coluna nova numa tabela de
    produção. O carimbo de hora é escrito por nós de propósito - depender do
    `updated_at` seria depender de um gatilho no banco que pode não existir.
    """
    import socket

    return f"{MARCA_DO_PC}{socket.gethostname()}|{datetime.now(timezone.utc).isoformat()}"


def visto_em(linha: dict):
    """Última vez que o dono deu sinal de vida. None quando não dá para saber."""
    marca = str(linha.get("error_message") or "")
    carimbo = marca.split("|", 1)[1] if "|" in marca else linha.get("updated_at")
    if not carimbo:
        return None
    try:
        return datetime.fromisoformat(str(carimbo).replace("Z", "+00:00"))
    except ValueError:
        return None


def abandonados(client) -> list:
    """Jobs que ficaram para trás quando um PC desligou no meio.

    `updated_at` é da própria linha: se ninguém mexe nela há horas, o processo
    que a reivindicou morreu. Volta para `waiting_vod`, que é a fila normal -
    e não para `failed`, senão aquele VOD nunca mais seria processado.
    """
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS_DE_ABANDONO)
    linhas = (
        client.table(STREAMS_TABLE)
        .select("stream_id, updated_at, error_message")
        .eq("vod_job_status", EM_ANDAMENTO)
        .like("error_message", f"{MARCA_DO_PC}%")
        .execute()
        .data
        or []
    )
    perdidos = []
    for linha in linhas:
        visto = visto_em(linha)
        # Sem carimbo legível não dá para julgar: mexer numa linha dessas
        # poderia reprocessar um VOD que está sendo cortado agora.
        if visto is not None and visto < limite:
            perdidos.append(linha)
    return perdidos


def devolver_abandonados(client, log) -> int:
    devolvidos = 0
    for linha in abandonados(client):
        resposta = (
            client.table(STREAMS_TABLE)
            .update({"vod_job_status": "waiting_vod",
                     "error_message": "retomado: o PC que processava sumiu"})
            .eq("stream_id", linha["stream_id"])
            # Só devolve se ainda estiver como a gente viu: se outro PC pegou
            # neste meio tempo, quem manda é ele.
            .eq("vod_job_status", EM_ANDAMENTO)
            .eq("error_message", linha.get("error_message") or "")
            .execute()
        )
        if resposta.data:
            devolvidos += 1
            log(f"stream {linha['stream_id']}: devolvido para a fila "
                f"(sem sinal desde {visto_em(linha)})")
    return devolvidos


# Credenciais da VPS ficam num arquivo do disco de dados, fora do repositorio.
# Sem isto os atalhos do Windows precisariam carregar segredo na linha de
# comando - que fica visivel no Gerenciador de Tarefas para qualquer um.
ARQUIVO_DE_AMBIENTE = Path(os.getenv("BOTLIVE_ENV_LOCAL", "G:/botlive-campanhas/vps.env"))


def carregar_ambiente() -> None:
    if not ARQUIVO_DE_AMBIENTE.is_file():
        return
    for linha in ARQUIVO_DE_AMBIENTE.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        # Quem ja esta no ambiente manda - mas so se tiver conteudo. Variavel
        # definida como texto vazio existe para o os.environ e faria o
        # setdefault desistir, deixando tudo sem credencial: foi exatamente o
        # que aconteceu na primeira tentativa.
        if not os.environ.get(chave.strip(), "").strip():
            os.environ[chave.strip()] = valor.strip()


def cliente():
    carregar_ambiente()
    # O antivirus desta maquina (AVG) faz MITM de TLS, e o Python nao conhece a
    # CA dele: sem isto todo acesso ao Supabase morre em CERTIFICATE_VERIFY_FAILED.
    # `truststore` usa o cofre de certificados do Windows, que ja confia nela -
    # continua verificando o certificado, so muda de onde vem a lista de CAs.
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    from supabase import create_client

    url = os.getenv("ROBO_SUPABASE_URL", "").strip()
    chave = os.getenv("ROBO_SUPABASE_KEY", "").strip()
    if not url or not chave:
        raise SystemExit("Faltam ROBO_SUPABASE_URL e ROBO_SUPABASE_KEY no ambiente")
    return create_client(url, chave)


def ler_config(client) -> VigiaConfig:
    linha = (client.table(CONFIG_TABLE).select("*").eq("id", 1).execute().data or [{}])[0]
    return VigiaConfig.from_row(linha)


def ambiente_do_filho() -> dict:
    """Ambiente do `main.py`, com o remendo de TLS desta maquina.

    O AVG intercepta TLS com uma CA que o OpenSSL do Python 3.14 recusa por
    formato. Injetar `truststore` no vod_pc.py nao adianta para o main.py, que
    e outro processo - e sem isso o VOD chegava a escolher os cortes e morria
    no fim, em CERTIFICATE_VERIFY_FAILED, jogando fora todo o trabalho.

    A pasta com o sitecustomize entra pelo PYTHONPATH so aqui, nos filhos que o
    BotLive inicia: nao mexe no Python do sistema nem em outros projetos.
    """
    ambiente = dict(os.environ)
    remendo = os.getenv("BOTLIVE_PYENV", "G:/botlive-campanhas/pyenv")
    if Path(remendo).is_dir():
        atual = ambiente.get("PYTHONPATH", "")
        ambiente["PYTHONPATH"] = remendo + (os.pathsep + atual if atual else "")
    # SSL_CERT_FILE apontando para um pacote com a CA do AVG NAO resolve (o
    # OpenSSL recusa o formato dela) e ainda atrapalha o truststore.
    ambiente.pop("SSL_CERT_FILE", None)
    ambiente.pop("REQUESTS_CA_BUNDLE", None)
    return ambiente


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

    # Reivindicação atômica: o `.eq("vod_job_status", "waiting_vod")` faz o
    # banco decidir quem ganha. Sem ele, dois PCs (ou duas cópias deste script)
    # liam a mesma linha, os dois marcavam como sua e o mesmo VOD era cortado e
    # postado duas vezes. Lista vazia = outro chegou primeiro.
    reivindicacao = (
        client.table(STREAMS_TABLE)
        .update({"vod_job_status": EM_ANDAMENTO, "vod_url": vod_url,
                 "error_message": _marca_de_posse()})
        .eq("stream_id", stream_id)
        .eq("vod_job_status", "waiting_vod")
        .execute()
    )
    if not reivindicacao.data:
        log(f"{linha['channel_login']}: outro processo pegou este VOD antes")
        return False

    # Cada job tem seu proprio log. Sem isto, um job que falha em 8 minutos nao
    # deixa pista nenhuma - e foi exatamente o que aconteceu na primeira
    # tentativa real.
    pasta = Path(os.getenv("VOD_PC_LOGS", "G:/botlive-campanhas/logs-vod"))
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"vigia_{stream_id}_vod.log"

    log(f"{linha['channel_login']}: processando {vod_url}")
    log(f"  log em {arquivo}")
    inicio = time.time()
    with arquivo.open("w", encoding="utf-8", errors="replace") as saida:
        processo = subprocess.run(comando, cwd=str(REPO), stdout=saida,
                                  stderr=subprocess.STDOUT, text=True,
                                  env=ambiente_do_filho())
    minutos = (time.time() - inicio) / 60

    ok = processo.returncode == 0
    motivo = ""
    if not ok:
        # A ultima linha do log costuma dizer o que houve; leva junto para o
        # painel, senao o "failed" no banco nao explica nada.
        try:
            linhas_log = [x.strip() for x in
                          arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
                          if x.strip()]
            motivo = linhas_log[-1][:180] if linhas_log else ""
        except OSError:
            motivo = ""
    client.table(STREAMS_TABLE).update(
        {
            "vod_job_status": "done" if ok else "failed",
            "error_message": "" if ok else f"vod_pc saiu com {processo.returncode}: {motivo}"[:400],
        }
    ).eq("stream_id", stream_id).execute()
    log(f"{linha['channel_login']}: {'pronto' if ok else 'FALHOU'} em {minutos:.0f} min"
        + (f" - {motivo[:100]}" if motivo else ""))
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
            devolver_abandonados(client, log)
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
