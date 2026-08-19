"""Adaptacao visual do material importado.

Reaproveita o motor do BotLive: clipper.renderizar_layout para proporcao,
recorte e reenquadramento; overlay_editor para tarjas, titulo, identidade e
CTA; clipper.validar_video_final para conferir a saida.

Limite explicito: o plano de adaptacao nao aceita nenhuma opcao cujo objetivo
seja apagar autoria ou contornar protecao. As chaves proibidas estao listadas
em CHAVES_PROIBIDAS e sao recusadas antes de qualquer render.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from .library import exigir_item
from .store import ImportError_, REPO_ROOT, agora, atualizar, conectar, inserir, obter


LAYOUTS = ("vertical-fit", "vertical-crop", "original")

# Adaptar material permitido e uma coisa; apagar a autoria dele e outra.
CHAVES_PROIBIDAS = (
    "remove_watermark",
    "remove_watermarks",
    "remove_credit",
    "remove_credits",
    "remove_logo",
    "remove_attribution",
    "strip_attribution",
    "hide_credit",
    "bypass_drm",
    "remove_protection",
)

CAMPOS_DO_PLANO = {
    "layout",
    "focus_x",
    "title",
    "description",
    "brand",
    "cta",
    "cta_seconds",
    "subtitles",
    "intro_path",
    "outro_path",
    "keep_credit",
}


def _legado(nome: str):
    """Carrega um modulo da raiz do BotLive sem mexer no pacote original."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    caminho = REPO_ROOT / f"{nome}.py"
    spec = importlib.util.spec_from_file_location(f"import_legacy_{nome}", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def validar_plano(plano: dict) -> dict:
    """Normaliza e recusa plano invalido ou com intencao de apropriacao."""
    plano = dict(plano or {})

    proibidas = [chave for chave in plano if chave.lower() in CHAVES_PROIBIDAS]
    if proibidas:
        raise ImportError_(
            "Plano recusado: adaptacao nao remove autoria nem protecao "
            f"({', '.join(sorted(proibidas))})"
        )
    desconhecidas = set(plano) - CAMPOS_DO_PLANO
    if desconhecidas:
        raise ImportError_(f"Campos desconhecidos no plano: {sorted(desconhecidas)}")

    layout = plano.get("layout", "vertical-fit")
    if layout not in LAYOUTS:
        raise ImportError_(f"Layout invalido: {layout}. Use {list(LAYOUTS)}")

    foco = float(plano.get("focus_x", 0.5))
    if not 0 <= foco <= 1:
        raise ImportError_("focus_x deve ficar entre 0 e 1")

    for chave in ("intro_path", "outro_path"):
        caminho = plano.get(chave)
        if caminho and not Path(caminho).is_file():
            raise ImportError_(f"{chave} aponta para arquivo inexistente")

    if plano.get("keep_credit") is False:
        raise ImportError_("keep_credit=false nao e permitido: o credito da origem fica")

    return {
        "layout": layout,
        "focus_x": foco,
        "title": (plano.get("title") or "")[:120],
        "description": (plano.get("description") or "")[:400],
        "brand": (plano.get("brand") or "")[:80],
        "cta": (plano.get("cta") or "")[:80],
        "cta_seconds": int(plano.get("cta_seconds", 4)),
        "subtitles": bool(plano.get("subtitles", False)),
        "intro_path": plano.get("intro_path") or "",
        "outro_path": plano.get("outro_path") or "",
        "keep_credit": True,
    }


def chave_idempotencia(item_id: str, channel_id: str, plano: dict) -> str:
    bruto = json.dumps({"item": item_id, "channel": channel_id, "plano": plano}, sort_keys=True)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def planejar(item_id: str, channel_id: str, plano: dict) -> dict:
    """Registra a adaptacao pretendida. Nao renderiza nada."""
    item = exigir_item(item_id)
    normalizado = validar_plano(plano)
    chave = chave_idempotencia(item_id, channel_id, normalizado)

    with conectar() as db:
        linha = db.execute(
            "SELECT * FROM import_adaptations WHERE idempotency_key=?", (chave,)
        ).fetchone()
    if linha:
        return dict(linha)

    stamp = agora()
    registro = inserir(
        "import_adaptations",
        {
            "item_id": item["id"],
            "channel_id": channel_id,
            "plan": json.dumps(normalizado, ensure_ascii=False),
            "status": "planned",
            "idempotency_key": chave,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    return obter("import_adaptations", registro["id"])


def _saida(adaptation_id: str) -> Path:
    raiz = Path(REPO_ROOT) / "botlive-import" / "data" / "outputs"
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz / f"{adaptation_id}.mp4"


def executar(adaptation_id: str) -> dict:
    """Renderiza a adaptacao e valida a saida.

    Falha de render marca a adaptacao como failed com o motivo - o item
    original nunca e alterado nem apagado.
    """
    adaptacao = obter("import_adaptations", adaptation_id)
    if not adaptacao:
        raise ImportError_("Adaptacao inexistente")
    if adaptacao["status"] == "rendered":
        return adaptacao

    item = exigir_item(adaptacao["item_id"])
    plano = json.loads(adaptacao["plan"])
    destino = _saida(adaptation_id)

    try:
        clipper = _legado("clipper")
        clipper.renderizar_layout(
            item["local_path"], destino, output_layout=plano["layout"], focus_x=plano["focus_x"]
        )

        credito = plano["brand"] or item["credit"]
        overlay = _legado("overlay_editor")
        config = overlay.OverlayConfig(
            title=plano["title"] or None,
            description=plano["description"] or None,
            brand=credito or None,
            cta=plano["cta"] or None,
            cta_seconds=plano["cta_seconds"],
        )
        if config.enabled:
            overlay.aplicar_overlay_no_video(destino, config, destino)

        validacao = clipper.validar_video_final(destino, require_audio=False)
        if not validacao.valid:
            raise ImportError_(f"Saida invalida: {validacao.reason}")
    except ImportError_:
        atualizar(
            "import_adaptations",
            adaptation_id,
            {"status": "failed", "error": "render recusado", "updated_at": agora()},
        )
        raise
    except Exception as erro:
        atualizar(
            "import_adaptations",
            adaptation_id,
            {"status": "failed", "error": str(erro)[:500], "updated_at": agora()},
        )
        raise ImportError_(f"Falha ao adaptar: {erro}") from erro

    from .library import sha256

    return atualizar(
        "import_adaptations",
        adaptation_id,
        {
            "output_path": str(destino),
            "output_sha256": sha256(destino),
            "width": validacao.width,
            "height": validacao.height,
            "duration_seconds": validacao.duration_seconds,
            "status": "rendered",
            "validation": json.dumps(
                {
                    "valid": True,
                    "width": validacao.width,
                    "height": validacao.height,
                    "has_audio": validacao.has_audio,
                },
                ensure_ascii=False,
            ),
            "error": "",
            "updated_at": agora(),
        },
    )
