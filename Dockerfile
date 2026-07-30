FROM python:3.12-slim

# ffmpeg do apt cobre todos os call sites: o codigo resolve o binario via
# imageio_ffmpeg.get_ffmpeg_exe(), que respeita IMAGEIO_FFMPEG_EXE.
# fonts-dejavu-core: fallback de sistema; a fonte principal (Anton) vem no repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        espeak-ng \
        fonts-dejavu-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg \
    HF_HOME=/app/.hf-cache \
    BOTLIVE_OUTPUT_ROOT=/data/botlive/output

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Usuario nao-root (uid 1000). Volumes montados na VPS precisam ser
# graveis por esse uid — ver secao de deploy no README.
RUN useradd --create-home --uid 1000 botlive \
    && mkdir -p /data/botlive/output /app/.hf-cache /app/.tokens \
    && chown -R botlive:botlive /data/botlive /app

USER botlive

# Modelo whisper small (~460MB) baixado no BUILD, nunca em runtime.
# Camada separada do codigo: mudar .py nao re-baixa o modelo.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

COPY --chown=botlive:botlive . .

VOLUME /data/botlive/output

ENTRYPOINT ["bash", "/app/docker-entrypoint.sh"]
