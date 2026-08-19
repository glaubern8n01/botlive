#!/usr/bin/env bash
# Sobe os tres agentes no mesmo container, um uvicorn por porta.
#
# Um container so, e nao tres servicos, porque os tres compartilham o mesmo
# volume de dados e o mesmo codigo: separar traria sincronizacao de volume
# sem ganho. Se um cair, o container inteiro reinicia - e o que a gente quer,
# porque o painel depende dos tres.
set -euo pipefail

mkdir -p /data/agents/sessions

echo "[agents] migrando bancos..."
python vexpublish/migrations/manage.py upgrade
python botlive-import/migrations/manage.py upgrade
python botlive-commerce/migrations/manage.py upgrade
python -c "import sys; sys.path.insert(0,'/app/botlive-dm'); from dm.store import migrar; migrar(); print('[agents] dm.db migrado')"

echo "[agents] subindo VexPublish :8785"
uvicorn vexpublish.api:app --host 0.0.0.0 --port 8785 --no-access-log &
PID_VEX=$!

echo "[agents] subindo Import :8795"
PYTHONPATH=/app/botlive-import/local-agent uvicorn importer.main:app --host 0.0.0.0 --port 8795 --no-access-log &
PID_IMP=$!

echo "[agents] subindo Commerce :8805"
PYTHONPATH=/app/botlive-commerce uvicorn commerce.main:app --host 0.0.0.0 --port 8805 --no-access-log &
PID_COM=$!

echo "[agents] subindo DM :8815"
PYTHONPATH=/app/botlive-dm uvicorn dm.main:app --host 0.0.0.0 --port 8815 --no-access-log &
PID_DM=$!

# Se qualquer um morrer, derruba o container inteiro (swarm reinicia).
trap 'kill $PID_VEX $PID_IMP $PID_COM $PID_DM 2>/dev/null || true' TERM INT
wait -n $PID_VEX $PID_IMP $PID_COM $PID_DM
echo "[agents] um dos agentes encerrou; derrubando o container para reiniciar"
exit 1
