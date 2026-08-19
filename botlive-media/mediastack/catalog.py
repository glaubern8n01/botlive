"""Catalogo dos repositorios candidatos para a stack de midia.

AVISO IMPORTANTE SOBRE A ORIGEM DOS DADOS
-----------------------------------------
Nada aqui foi auditado. Os campos `descricao_declarada` e `uso_sugerido` vem
do documento de arquitetura do projeto, ou seja, sao o que *se diz* sobre cada
ferramenta - nao o que foi verificado rodando, lendo licenca ou medindo VRAM.

Por isso todo item nasce com `auditoria="NAO AUDITADO"` e com licenca, VRAM,
RAM, headless, API e CLI em None. None significa "ninguem mediu ainda", e e
diferente de 0 ou False. A funcao registrar_auditoria() preenche esses campos
quando alguem de fato conferir, e matrix.py se recusa a escolher ferramenta
nao auditada para producao.

Regra do projeto: auditar antes de instalar. Nao instalar todos cegamente.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path


CAPACIDADES = (
    "imagem",
    "video",
    "tts",
    "transcricao",
    "legendas",
    "montagem",
    "render",
    "thumbnail",
    "clipping",
    "publicacao",
    "avatar_live",
    "infra",
)

NIVEIS_AUDITORIA = ("NAO AUDITADO", "PARCIAL", "AUDITADO", "DESCARTADO")


@dataclass(frozen=True)
class Ferramenta:
    id: str
    repositorio: str
    descricao_declarada: str
    uso_sugerido: str
    capacidades: tuple = ()
    prioridade_declarada: str = "media"

    # Tudo abaixo so deixa de ser None depois de auditoria real.
    licenca: str | None = None
    custo: str | None = None
    vram_gb: float | None = None
    ram_gb: float | None = None
    headless: bool | None = None
    api: bool | None = None
    cli: bool | None = None
    maturidade: str | None = None
    integracao: str | None = None
    commit_auditado: str | None = None
    auditoria: str = "NAO AUDITADO"
    observacoes: str = ""
    pendencias: tuple = ()

    @property
    def auditada(self) -> bool:
        return self.auditoria in {"PARCIAL", "AUDITADO"}

    @property
    def usavel_em_producao(self) -> bool:
        """So entra em producao com licenca conhecida e auditoria concluida."""
        return self.auditoria == "AUDITADO" and bool(self.licenca)


def _f(id, repositorio, descricao, uso, capacidades, prioridade="media"):
    return Ferramenta(
        id=id,
        repositorio=repositorio,
        descricao_declarada=descricao,
        uso_sugerido=uso,
        capacidades=tuple(capacidades),
        prioridade_declarada=prioridade,
        pendencias=("licenca", "custo", "vram", "ram", "headless", "api", "cli", "maturidade"),
    )


FERRAMENTAS = {
    item.id: item
    for item in (
        _f("wan2gp", "https://github.com/deepbeepmeep/Wan2GP",
           "Video, imagem, audio/TTS, low-VRAM, API, headless, fila.",
           "Prioridade declarada muito alta: local e gratuito.",
           ("imagem", "video", "tts"), "muito-alta"),
        _f("video-shotcraft", "https://github.com/Vincentwei1021/video-shotcraft",
           "152 shot cards, 209 previews, Remotion, sound design, export JianYing.",
           "Prioridade declarada alta para montagem e edicao.",
           ("montagem", "render"), "alta"),
        _f("openshorts", "https://github.com/mutonby/openshorts",
           "Whisper, deteccao de cenas, cortes, 9:16, captions, UGC.",
           "Forte para Campanhas de Cortes e Shorts.",
           ("clipping", "transcricao", "legendas"), "alta"),
        _f("openmontage", "https://github.com/calesthio/OpenMontage",
           "Clipes, narracao, musica, legenda, edicao e render.",
           "Candidato declarado forte.",
           ("montagem", "render", "legendas", "tts")),
        _f("dramaclaw", "https://github.com/dramaclaw/dramaclaw",
           "Pipeline self-hosted de roteiro ate filme.",
           "Candidato declarado forte.",
           ("video", "montagem", "render")),
        _f("moneyprinterturbo", "https://github.com/harry0703/MoneyPrinterTurbo",
           "Roteiro, narracao, legendas, busca visual e montagem de shorts.",
           "Comparar antes de usar: sobrepoe o motor atual.",
           ("video", "tts", "legendas", "montagem")),
        _f("joyai-video-editor", "https://github.com/jd-opensource/JoyAI-Video-Editor",
           "Edicao e transformacao de video em streaming.",
           "Candidato para edicao avancada.",
           ("montagem", "render")),
        _f("capcut-cli", "https://github.com/renezander030/capcut-cli",
           "Automacao de drafts CapCut/JianYing via CLI/JSON.",
           "Validar se exporta/renderiza de fato.",
           ("montagem",)),
        _f("open-generative-ai", "https://github.com/Anil-matcha/Open-Generative-AI",
           "Interface agregadora de imagem/video; providers variam.",
           "Referencia. Checar custo dos providers.",
           ("imagem", "video")),
        _f("arcads-claude-code", "https://github.com/krusemediallc/arcads-claude-code",
           "UGC, anuncios, thumbnails, clone-ad, workflows.",
           "Usar como referencia de workflow, nao como dependencia paga.",
           ("thumbnail", "video")),
        _f("youtube-automation-agent", "https://github.com/darkzOGx/youtube-automation-agent",
           "Agente de gestao/producao/publicacao de canal.",
           "Referencia para automacao de canal.",
           ("publicacao",)),
        _f("autosocial", "https://github.com/Katzca/AutoSocial",
           "TikTok, Instagram, YouTube; multi-conta, filas, Playwright, FFmpeg.",
           "Referencia para o VexPublish.",
           ("publicacao",), "alta"),
        _f("social-auto-upload", "https://github.com/dreammis/social-auto-upload",
           "CLI, skills para agentes, upload e agendamento; Kuaishou suportado.",
           "Prioridade declarada para Kwai/Kuaishou.",
           ("publicacao",), "alta"),
        _f("docker-android", "https://github.com/HQarroum/docker-android",
           "Android em Docker, ADB, KVM, headless.",
           "Fallback de ultimo recurso para automacao no app.",
           ("infra",), "baixa"),
        _f("open-llm-vtuber", "https://github.com/Open-LLM-VTuber/Open-LLM-VTuber",
           "LLM + STT + TTS + Live2D, pode operar local/offline.",
           "Opcional para avatar em LIVE.",
           ("avatar_live", "tts"), "baixa"),
    )
}


def caminho_auditorias() -> Path:
    padrao = Path(__file__).resolve().parents[1] / "data" / "auditorias.json"
    return Path(os.getenv("MEDIA_AUDIT_PATH", padrao))


def _carregar_auditorias() -> dict:
    caminho = caminho_auditorias()
    if not caminho.is_file():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def registrar_auditoria(ferramenta_id: str, **campos) -> dict:
    """Grava o resultado de uma auditoria real.

    Exige nivel valido e, para concluir como AUDITADO, exige licenca e commit -
    conclusao sem licenca registrada nao e auditoria, e chute.
    """
    if ferramenta_id not in FERRAMENTAS:
        raise KeyError(f"Ferramenta desconhecida: {ferramenta_id}")
    nivel = campos.get("auditoria", "PARCIAL")
    if nivel not in NIVEIS_AUDITORIA:
        raise ValueError(f"Nivel de auditoria invalido: {nivel}")
    if nivel == "AUDITADO" and not (campos.get("licenca") and campos.get("commit_auditado")):
        raise ValueError("Concluir auditoria exige licenca e commit auditado")

    dados = _carregar_auditorias()
    dados[ferramenta_id] = {**dados.get(ferramenta_id, {}), **campos, "auditoria": nivel}
    caminho = caminho_auditorias()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return dados[ferramenta_id]


def obter(ferramenta_id: str) -> Ferramenta:
    base = FERRAMENTAS[ferramenta_id]
    registrado = _carregar_auditorias().get(ferramenta_id)
    if not registrado:
        return base
    campos = {k: v for k, v in registrado.items() if k in {f.name for f in base.__dataclass_fields__.values()}}
    if "pendencias" in campos:
        campos["pendencias"] = tuple(campos["pendencias"])
    if "capacidades" in campos:
        campos["capacidades"] = tuple(campos["capacidades"])
    return replace(base, **campos)


def todas() -> list:
    return [obter(x) for x in FERRAMENTAS]


def por_capacidade(capacidade: str) -> list:
    if capacidade not in CAPACIDADES:
        raise ValueError(f"Capacidade desconhecida: {capacidade}")
    return [x for x in todas() if capacidade in x.capacidades]


def como_dicts() -> list:
    return [asdict(x) for x in todas()]
