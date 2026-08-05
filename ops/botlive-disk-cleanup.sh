#!/bin/bash
# Limpeza automática de disco do BotLive.
# Previne o incidente que derruba TODOS os serviços quando o disco enche
# (cortes acumulados + cache do vigia). Conservador: mantém cortes recentes e
# NUNCA apaga o cache de um render ativo (blocos de sessão ativa têm minutos;
# só apaga cache com +12h). Rode por cron (ex.: a cada 2h).
set -u
V=/etc/easypanel/projects/botlive/botlive-app/volumes/botlive-output
LOG=/var/log/botlive-cleanup.log
USE=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
echo "$(date '+%F %T') inicio | disco=${USE}%" >> "$LOG"

# Sempre (barato e seguro):
# - cortes finais com +2 dias (os recentes/pendentes ficam);
find "$V/cortes" -type f -mtime +2 -delete 2>/dev/null
find "$V/cortes" -type d -empty -delete 2>/dev/null
# - trunca logs de container gigantes (não apaga o arquivo);
find /var/lib/docker/containers -name "*-json.log" -size +20M -exec truncate -s 0 {} \; 2>/dev/null
# - imagens docker DANGLING (sem tag). NUNCA -a: isso apagaria imagem de
#   serviço temporariamente parado (foi o que derrubou o tiktok-public).
docker image prune -f >/dev/null 2>&1
docker builder prune -f >/dev/null 2>&1

# Agressivo só quando o disco está alto (>=82%):
if [ "${USE:-0}" -ge 82 ]; then
  # cache do vigia com +12h (render ativo tem blocos de minutos, nunca 12h)
  find "$V/cache" -mindepth 1 -mmin +720 -delete 2>/dev/null
  # cortes com +1 dia
  find "$V/cortes" -type f -mtime +1 -delete 2>/dev/null
  # arquivos-fonte do relay (temporários, já cortados)
  find "$V/relay" -type f -mmin +120 -delete 2>/dev/null
  echo "$(date '+%F %T') limpeza agressiva (disco>=82%)" >> "$LOG"
fi

USE2=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
echo "$(date '+%F %T') fim | disco=${USE2}%" >> "$LOG"
