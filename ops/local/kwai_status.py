"""Diz, em uma tela, se o Kwai CUT esta trabalhando ou parado - e por que.

Por que existe
--------------
O Kwai CUT e o que esta mais perto de virar dinheiro, e a forma de saber se ele
estava vivo era abrir o painel, olhar log de container e contar arquivo na mao.
Em 24/08/2026 ele passou dias descobrindo ZERO canais (117 de 120 com erro) por
causa de um cookie do YouTube vencido, e ninguem percebeu ate faltar video.

Aqui a resposta vem mastigada: cookie ok?, produtor rodando?, quantos videos
prontos?, a ultima varredura achou alguma coisa? E, quando o problema for o
cookie, a tela diz exatamente o que fazer.

Uso: clique no atalho "Status do Kwai", ou
     python ops/local/kwai_status.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone

VPS = "root@69.62.96.161"
VOLUME = "/etc/easypanel/projects/botlive/botlive-app/volumes/botlive-output"

# Cookies que de fato autenticam. Sem um destes, o yt-dlp volta a levar
# "Sign in to confirm you're not a bot" e a descoberta morre.
COOKIES_DE_SESSAO = {"SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID"}


def na_vps(comando: str, segundos: int = 90) -> str:
    try:
        pronto = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VPS, comando],
            capture_output=True, text=True, timeout=segundos)
        return pronto.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def ler_cookie(texto: str) -> tuple[str, str]:
    """Devolve (estado, recado). Mesma regra do card do painel."""
    vencimentos = []
    for linha in texto.splitlines():
        if not linha or linha.startswith("#"):
            continue
        campos = linha.split("\t")
        if len(campos) < 7 or "youtube.com" not in campos[0]:
            continue
        if campos[5] in COOKIES_DE_SESSAO and campos[4].isdigit() and int(campos[4]) > 0:
            vencimentos.append(int(campos[4]))
    if not vencimentos:
        return "RUIM", "Nao achei o cookie de login (SID / LOGIN_INFO) no arquivo."
    dias = (min(vencimentos) - datetime.now(timezone.utc).timestamp()) / 86400
    if dias < 0:
        return "VENCIDO", f"Venceu ha {abs(int(dias))} dia(s)."
    if dias <= 7:
        return "VENCENDO", f"Vence em {int(dias)} dia(s)."
    return "OK", f"Valido por mais {int(dias)} dia(s)."


def main() -> int:
    print("=" * 58)
    print("  KWAI CUT - como esta agora")
    print("=" * 58)

    cookie = na_vps(f"cat {VOLUME}/cookies-youtube.txt 2>/dev/null")
    if not cookie:
        estado, recado = "AUSENTE", "Nao ha cookie instalado na VPS."
    else:
        estado, recado = ler_cookie(cookie)
    print(f"\nCookie do YouTube : {estado}\n  {recado}")

    produtor = na_vps('docker ps --format "{{.Names}} {{.Status}}" | grep kwai-cut | head -1')
    print(f"\nProdutor          : {'rodando - ' + produtor.split(maxsplit=1)[-1] if produtor else 'PARADO'}")

    prontos = na_vps(f'find {VOLUME}/kwai_cut/ready -name "*.mp4" 2>/dev/null | wc -l')
    print(f"Videos prontos    : {prontos or '?'}")

    log = na_vps('docker service logs botlive_kwai-cut-producer --tail 400 2>&1 '
                 '| grep -i "multichannel discovery" | tail -1')
    achado = re.search(r"channels_consulted.: (\d+).*?candidates.: (\d+).*?"
                       r"live_found.: (\d+).*?channel_errors.: (\d+)", log or "")
    if achado:
        canais, candidatos, ao_vivo, erros = achado.groups()
        print(f"\nUltima varredura  : {canais} canais, {candidatos} candidato(s), "
              f"{ao_vivo} ao vivo, {erros} com erro")
        if int(erros) > int(canais) * 0.5:
            print("  ATENCAO: mais da metade dos canais falhou - cara de cookie vencido.")
    else:
        print("\nUltima varredura  : nao achei no log recente")

    print("\n" + "-" * 58)
    if estado in {"OK"} and produtor and achado and int(achado.group(4)) < int(achado.group(1)) * 0.5:
        print("TUDO CERTO. Nao precisa fazer nada.")
    elif estado in {"VENCIDO", "AUSENTE", "RUIM"} or (achado and int(achado.group(4)) > int(achado.group(1)) * 0.5):
        print("PRECISA DE COOKIE NOVO.")
        print("  1. No Chrome, com o YouTube aberto e logado,")
        print("     use a extensao 'Get cookies.txt' (formato Netscape).")
        print("  2. Cole no painel: aba Kwai CUT, card 'Cookie do YouTube'.")
        print("     (painel.vextriq.online)")
    elif estado == "VENCENDO":
        print("FUNCIONANDO, mas troque o cookie esta semana (painel, aba Kwai CUT).")
    else:
        print("Funcionando em parte - veja os itens acima.")
    print("-" * 58)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(1)
