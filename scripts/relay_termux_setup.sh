#!/data/data/com.termux/files/usr/bin/bash
# Setup do relay do Kwai CUT em um celular Android antigo (Termux), no Wi-Fi de casa.
# Requisitos atendidos: tela apagada (wake-lock), reinício após reboot (Termux:Boot),
# fila persistente na VPS, download residencial, validação, envio, guardas de
# bateria/armazenamento. Sem app, sem porta no roteador, sem token no Git.
#
# Passos manuais (uma vez):
#   1. Instale o app "Termux" e "Termux:Boot" (F-Droid).
#   2. Copie este repositório para ~/botlive no celular (git clone).
#   3. Crie ~/botlive/.env com ROBO_SUPABASE_URL e ROBO_SUPABASE_KEY (NÃO no Git).
#   4. Gere/instale a chave SSH da VPS em ~/.ssh/id_ed25519 (NÃO no Git).
#   5. Rode:  bash scripts/relay_termux_setup.sh
set -e

pkg update -y
pkg install -y python ffmpeg openssh termux-api git
pip install --upgrade yt-dlp

# Mantém CPU/rede com a tela apagada.
termux-wake-lock || true

# Auto-start após reboot: cria o hook do Termux:Boot.
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/botlive-relay.sh <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd ~/botlive
export RELAY_MIN_BATTERY=30 RELAY_MAX_TEMP_C=45 RELAY_MIN_FREE_GB=2
python relay_run.py --limit 30 --loop --target 30 >> ~/botlive-relay.log 2>&1
BOOT
chmod +x ~/.termux/boot/botlive-relay.sh

echo "OK. Iniciando o relay agora (log em ~/botlive-relay.log):"
cd ~/botlive
export RELAY_MIN_BATTERY=30 RELAY_MAX_TEMP_C=45 RELAY_MIN_FREE_GB=2
exec python relay_run.py --limit 30 --loop --target 30
