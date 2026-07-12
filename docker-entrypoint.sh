#!/usr/bin/env bash
# Traduz env vars BOTLIVE_* em argv para o main.py.
# Escape hatch: argumentos diretos no container ignoram as envs
# (ex.: docker run imagem python yt_publisher.py auth --conta principal).
set -euo pipefail

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Modo vigia: sem SOURCE/LISTA (alvos vem do Supabase/Twitch). Servico continuo.
if [ "${BOTLIVE_MODO:-}" = "vigia" ]; then
    args=(--modo vigia)
    if [ "${BOTLIVE_VIGIA_DRY:-0}" = "1" ]; then
        args+=(--vigia-dry-run)
    fi
    echo "[entrypoint] python main.py ${args[*]}"
    exec python main.py "${args[@]}"
fi

if [ -n "${BOTLIVE_SOURCE:-}" ] && [ -n "${BOTLIVE_LISTA_LINKS:-}" ]; then
    echo "[entrypoint] BOTLIVE_SOURCE e BOTLIVE_LISTA_LINKS sao mutuamente exclusivos." >&2
    exit 1
fi
if [ -z "${BOTLIVE_SOURCE:-}" ] && [ -z "${BOTLIVE_LISTA_LINKS:-}" ]; then
    echo "[entrypoint] defina BOTLIVE_SOURCE (URL/arquivo) ou BOTLIVE_LISTA_LINKS (arquivo com um link por linha)." >&2
    exit 1
fi

args=()

if [ -n "${BOTLIVE_SOURCE:-}" ]; then
    args+=("$BOTLIVE_SOURCE")
else
    args+=(--lista-links "$BOTLIVE_LISTA_LINKS")
fi

if [ -n "${BOTLIVE_MODO:-}" ]; then
    args+=(--modo "$BOTLIVE_MODO")
fi
args+=(--session-id "${BOTLIVE_SESSION_ID:-vps_$(date +%Y%m%d_%H%M%S)}")

if [ -n "${BOTLIVE_CONTENT_FILTER:-}" ]; then
    args+=(--content-filter "$BOTLIVE_CONTENT_FILTER")
fi
if [ "${BOTLIVE_STRICT_FOOTBALL:-0}" = "1" ]; then
    args+=(--strict-football-filter)
fi
if [ -n "${BOTLIVE_RETENTION:-}" ]; then
    args+=(--live-retention-seconds "$BOTLIVE_RETENTION")
fi
if [ -n "${BOTLIVE_MAX_CORTES:-}" ]; then
    args+=(--max-cortes "$BOTLIVE_MAX_CORTES")
fi
if [ -n "${BOTLIVE_CLIP_DURATION:-}" ]; then
    args+=(--clip-duration "$BOTLIVE_CLIP_DURATION")
fi
if [ -n "${BOTLIVE_TARGET_HEIGHT:-}" ]; then
    args+=(--target-height "$BOTLIVE_TARGET_HEIGHT")
fi
if [ -n "${BOTLIVE_OUTPUT_LAYOUT:-}" ]; then
    args+=(--output-layout "$BOTLIVE_OUTPUT_LAYOUT")
fi

if [ "${BOTLIVE_PUBLISH_VERTICAL:-0}" = "1" ]; then
    args+=(--publish-vertical)
fi
if [ "${BOTLIVE_POST_YOUTUBE:-0}" = "1" ]; then
    args+=(--post-youtube)
fi
if [ -n "${BOTLIVE_POST_VISIBILIDADE:-}" ]; then
    args+=(--post-visibilidade "$BOTLIVE_POST_VISIBILIDADE")
fi
if [ -n "${BOTLIVE_POST_CONTA:-}" ]; then
    args+=(--post-conta "$BOTLIVE_POST_CONTA")
fi
if [ -n "${BOTLIVE_CREDITO_STREAMER:-}" ]; then
    args+=(--credito-streamer "$BOTLIVE_CREDITO_STREAMER")
fi
if [ -n "${BOTLIVE_CREDITO_CANAL:-}" ]; then
    args+=(--credito-canal "$BOTLIVE_CREDITO_CANAL")
fi

# Qualquer flag nao mapeada acima (word-splitting proposital, sem aspas).
if [ -n "${BOTLIVE_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    args+=(${BOTLIVE_EXTRA_ARGS})
fi

echo "[entrypoint] python main.py ${args[*]}"
exec python main.py "${args[@]}"
