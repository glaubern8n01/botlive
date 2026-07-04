from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


# Cliente generico de IA de texto para gerar a legenda clickbait a partir da
# FALA transcrita do corte. Suporta dois formatos de API:
#   - openai: endpoint OpenAI-compatible (OpenAI, DeepSeek, Groq, OpenRouter...);
#   - anthropic: /v1/messages com headers x-api-key + anthropic-version.
# Regras de ouro:
#   - desligavel: sem PUBLISH_AI_API_KEY, cai no fallback e NUNCA quebra;
#   - barato: so texto curto (fala de 30-40s), nenhum frame de video;
#   - PUBLISH_AI_PROVIDER escolhe o formato; sem ele, detecta pela chave/URL.

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_SECONDS = 25
LEGENDA_MAX_CHARS = 70

FALLBACK_POR_NICHO = {
    "football": "OLHA ESSE LANCE",
    "gta": "OLHA O QUE ACONTECEU NA LIVE",
}
FALLBACK_GENERICO = "OLHA O QUE ACONTECEU NA LIVE"

_PROMPT_SISTEMA = (
    "Voce cria legendas clickbait curtas para cortes de streamer em portugues do Brasil."
)

_PROMPT_USUARIO = """A fala abaixo foi transcrita de um corte curto de live ({nicho}).

FALA:
\"\"\"{transcricao}\"\"\"

Crie UMA legenda clickbait para a tarja de cima do video vertical.
Regras:
- No maximo {max_chars} caracteres.
- Portugues do Brasil, CAIXA ALTA, sem emoji, sem aspas, sem hashtag.
- Descreva o momento mais forte da fala, chamativo, estilo clipe de streamer.
- NUNCA invente fato que nao esta na fala.
- Se a fala nao tiver drama (ex.: pedido de like, conversa comum), faca uma
  legenda neutra e curta sobre o que foi dito e marque a forca como "fraco".

Responda SOMENTE com JSON neste formato:
{{"legenda": "TEXTO DA LEGENDA", "forca": "forte" ou "fraco"}}"""


@dataclass(frozen=True)
class LegendaResultado:
    legenda: str
    source: str  # "ia" | "fallback" | "sem_fala"
    weak: bool = False
    error: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def from_ai(self) -> bool:
        return self.source == "ia"


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


def _detectar_provider(api_key: Optional[str], base_url: Optional[str]) -> str:
    explicit = (os.environ.get("PUBLISH_AI_PROVIDER") or "").strip().lower()
    if explicit in {"anthropic", "openai"}:
        return explicit
    if (api_key or "").startswith("sk-ant-"):
        return "anthropic"
    if "anthropic" in (base_url or "").lower():
        return "anthropic"
    return "openai"


def _config() -> dict[str, Any]:
    _carregar_dotenv()
    api_key = os.environ.get("PUBLISH_AI_API_KEY") or None
    base_url = os.environ.get("PUBLISH_AI_BASE_URL") or None
    provider = _detectar_provider(api_key, base_url)
    if not base_url:
        base_url = DEFAULT_ANTHROPIC_BASE_URL if provider == "anthropic" else DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")
    if provider == "anthropic" and base_url.endswith("/v1"):
        # Formato anthropic monta /v1/messages sozinho; aceita base com ou sem /v1.
        base_url = base_url[: -len("/v1")]
    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": os.environ.get("PUBLISH_AI_MODEL") or None,
        "timeout": float(os.environ.get("PUBLISH_AI_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS),
        "fallback": os.environ.get("PUBLISH_AI_FALLBACK_LEGENDA") or None,
    }


def _legenda_fallback(nicho: Optional[str], streamer: Optional[str], config_fallback: Optional[str]) -> str:
    if config_fallback:
        return _sanitizar_legenda(config_fallback)
    base = FALLBACK_POR_NICHO.get(nicho or "", FALLBACK_GENERICO)
    if streamer:
        return _sanitizar_legenda(f"{base} DE {streamer}")
    return base


def _sanitizar_legenda(text: str) -> str:
    """Normaliza o que veio da IA: 1 linha, sem emoji/aspas, CAIXA ALTA, <=70 chars."""
    cleaned = "".join(ch for ch in text if ord(ch) <= 0x24F or ch in "-...")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip('"').strip("'").strip()
    cleaned = cleaned.upper()
    if len(cleaned) > LEGENDA_MAX_CHARS:
        cut = cleaned[: LEGENDA_MAX_CHARS - 3]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        cleaned = cut.rstrip(".,;:!?") + "..."
    return cleaned


def _extrair_json(content: str) -> Optional[dict]:
    # Modelos as vezes embrulham o JSON em cerca de codigo ou texto extra.
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _prompt_usuario(transcricao: str, nicho: Optional[str]) -> str:
    return _PROMPT_USUARIO.format(
        nicho=nicho or "live",
        transcricao=transcricao.strip(),
        max_chars=LEGENDA_MAX_CHARS,
    )


def _chamar_api_anthropic(transcricao: str, nicho: Optional[str], config: dict[str, Any]) -> tuple[str, int, int]:
    """POST /v1/messages da Anthropic. Retorna (texto, tokens_entrada, tokens_saida)."""
    payload = {
        "model": config["model"],
        "max_tokens": 200,
        "system": _PROMPT_SISTEMA,
        "messages": [{"role": "user", "content": _prompt_usuario(transcricao, nicho)}],
    }
    request = urllib.request.Request(
        f"{config['base_url']}/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": config["api_key"],
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("stop_reason") == "refusal":
        raise RuntimeError("api recusou a solicitacao (stop_reason=refusal)")
    content = "".join(
        block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
    )
    usage = body.get("usage") or {}
    return content, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def _chamar_api(transcricao: str, nicho: Optional[str], config: dict[str, Any]) -> tuple[dict, dict]:
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": _PROMPT_SISTEMA},
            {"role": "user", "content": _prompt_usuario(transcricao, nicho)},
        ],
        "temperature": 0.7,
        "max_tokens": 120,
    }
    request = urllib.request.Request(
        f"{config['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
        body = json.loads(response.read().decode("utf-8"))
    usage = body.get("usage") or {}
    return body, usage


def gerar_legenda(
    transcricao: str,
    nicho: Optional[str] = None,
    streamer: Optional[str] = None,
) -> LegendaResultado:
    """Gera a legenda clickbait pela fala transcrita. Nunca levanta excecao.

    Sem fala -> fallback sem gastar API. Sem chave ou erro de API -> fallback.
    weak=True sinaliza corte sem drama (fala fraca) para o publish.json.
    """
    config = _config()
    fallback = _legenda_fallback(nicho, streamer, config["fallback"])

    if not (transcricao or "").strip():
        return LegendaResultado(legenda=fallback, source="sem_fala")

    if not config["api_key"] or not config["model"]:
        missing = "PUBLISH_AI_API_KEY" if not config["api_key"] else "PUBLISH_AI_MODEL"
        return LegendaResultado(legenda=fallback, source="fallback", error=f"{missing} ausente")

    try:
        if config["provider"] == "anthropic":
            content, prompt_tokens, completion_tokens = _chamar_api_anthropic(transcricao, nicho, config)
        else:
            body, usage = _chamar_api(transcricao, nicho, config)
            content = body["choices"][0]["message"]["content"]
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        data = _extrair_json(content)
        if data and data.get("legenda"):
            legenda = _sanitizar_legenda(str(data["legenda"]))
            weak = str(data.get("forca", "")).strip().lower() == "fraco"
        else:
            # JSON quebrado: usa o texto cru como legenda, melhor que fallback.
            legenda = _sanitizar_legenda(content)
            weak = False
        if not legenda:
            return LegendaResultado(legenda=fallback, source="fallback", error="ia retornou legenda vazia")
        return LegendaResultado(
            legenda=legenda,
            source="ia",
            weak=weak,
            model=config["model"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception as exc:
        reason = exc.read().decode("utf-8", "replace")[:300] if isinstance(exc, urllib.error.HTTPError) else str(exc)
        return LegendaResultado(legenda=fallback, source="fallback", error=reason)


if __name__ == "__main__":
    import argparse

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Gera legenda clickbait a partir da fala transcrita.")
    parser.add_argument("texto", help="Texto transcrito da fala do corte.")
    parser.add_argument("--nicho", choices=["football", "gta"], default=None)
    parser.add_argument("--streamer", default=None, help="@ do streamer, usado no fallback.")
    args = parser.parse_args()

    result = gerar_legenda(args.texto, nicho=args.nicho, streamer=args.streamer)
    print(f"legenda: {result.legenda}")
    print(f"fonte={result.source} fraca={result.weak} modelo={result.model}")
    print(f"tokens: entrada={result.prompt_tokens} saida={result.completion_tokens}")
    if result.error:
        print(f"erro tratado: {result.error}")
