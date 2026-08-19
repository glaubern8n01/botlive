# Imagem dos agentes locais do BotLive (VexPublish, Import, Commerce).
#
# Separada da imagem do vigia de proposito: o vigia nao precisa de fastapi e
# nao pode ganhar dependencia nova por causa de um painel. Aqui roda so a
# camada de API, atras do nginx do painel (mesmo dominio, mesmo Basic Auth).
FROM python:3.12-slim

WORKDIR /app

# ffmpeg/ffprobe: o doctor checa e o modulo de importacao le metadata.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY ops/agents/requirements-agents.txt /tmp/requirements-agents.txt
RUN pip install --no-cache-dir -r /tmp/requirements-agents.txt

COPY . .

# Bancos e sessoes ficam em volume, nunca na imagem.
ENV VEXPUBLISH_DATABASE_PATH=/data/agents/vexpublish.db \
    VEXPUBLISH_SESSIONS_DIR=/data/agents/sessions \
    IMPORT_DATABASE_PATH=/data/agents/import.db \
    COMMERCE_DATABASE_PATH=/data/agents/commerce.db \
    PYTHONUNBUFFERED=1

# Checkout no Windows entrega CRLF; com CRLF o shebang quebra (exit 127).
RUN sed -i "s/$//" /app/ops/agents/start.sh && chmod +x /app/ops/agents/start.sh

EXPOSE 8785 8795 8805

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8785/vexpublish/v1/health || exit 1

CMD ["/app/ops/agents/start.sh"]
