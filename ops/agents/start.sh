#!/usr/bin/env bash
# Sobe os agentes no mesmo container, um uvicorn por porta.
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
python -c "import sys; sys.path.insert(0,'/app/botlive-mass'); from massa.store import migrar; migrar(); print('[agents] massa.db migrado')"
python botlive-campaigns/migrations/manage.py upgrade

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

echo "[agents] subindo Campanhas :8775"
# O pacote e `app`, dentro de local-agent/ - o modulo nasceu como agente local
# separado e continua com essa raiz.
PYTHONPATH=/app/botlive-campaigns/local-agent uvicorn app.main:app --host 0.0.0.0 --port 8775 --no-access-log &
PID_CAM=$!

# O worker das Campanhas: e ele que faz o bot trabalhar SOZINHO em cada
# campanha - detecta os cortes do material autorizado, renderiza e manda para a
# fila de revisao, sem ninguem apertar nada. A API sozinha nao faz isso: ela so
# enfileira. Respeita CAMPAIGNS_ENABLED e CAMPAIGNS_PAUSED.
if [ "${CAMPAIGNS_ENABLED,,}" = "true" ]; then
    echo "[agents] subindo worker de Campanhas"
    PYTHONPATH=/app/botlive-campaigns/local-agent python -m app.worker &
    PID_CAMW=$!
else
    echo "[agents] worker de Campanhas parado (CAMPAIGNS_ENABLED != true)"
    PID_CAMW=""
fi

echo "[agents] subindo Massa :8825"
PYTHONPATH=/app/botlive-mass uvicorn massa.main:app --host 0.0.0.0 --port 8825 --no-access-log &
PID_MASS=$!

# Se qualquer um morrer, derruba o container inteiro (swarm reinicia).
trap 'kill $PID_VEX $PID_IMP $PID_COM $PID_DM $PID_MASS $PID_CAM $PID_CAMW 2>/dev/null || true' TERM INT
# O wait cobre so as APIs. Worker que morre nao derruba o container:
# o swarm reiniciaria tudo por causa de um job ruim.
wait -n $PID_VEX $PID_IMP $PID_COM $PID_DM $PID_MASS $PID_CAM
echo "[agents] um dos agentes encerrou; derrubando o container para reiniciar"
exit 1
