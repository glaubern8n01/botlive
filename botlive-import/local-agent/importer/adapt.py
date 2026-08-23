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
    "capa",
    "narracao",
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
        # Capa e narracao sao desta operacao, nao do pipeline de cortes de
        # live: la o audio do streamer e o conteudo e a capa ja e outra
        # coisa. Aqui, em material importado, os dois fazem sentido.
        "capa": bool(plano.get("capa", True)),
        "narracao": bool(plano.get("narracao", False)),
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


def _media_local():
    """Carrega os executores locais de imagem/voz (Pillow e Piper).

    Import tardio e por caminho: o modulo de midia vive em botlive-media/ e
    nao pode virar dependencia dura da importacao. Sem ele, capa e narracao
    simplesmente nao saem - o resto da adaptacao continua.
    """
    raiz = REPO_ROOT / "botlive-media"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from mediastack.executors import imagem_local, voz_local

    return imagem_local, voz_local


def _gerar_extras(plano: dict, video: Path, adaptation_id: str) -> dict:
    """Capa e narracao do material adaptado. Nenhuma das duas e obrigatoria:
    falha aqui vira registro de erro, nunca derruba a adaptacao pronta."""
    extras = {"cover_path": "", "narration_path": "", "extras_error": ""}
    if not (plano.get("capa") or plano.get("narracao")):
        return extras

    try:
        imagem_local, voz_local = _media_local()
    except Exception as erro:
        extras["extras_error"] = f"midia local indisponivel: {erro}"
        return extras

    pasta = Path(video).parent
    problemas = []

    if plano.get("capa"):
        try:
            frame = pasta / f"{adaptation_id}_frame.jpg"
            fundo = None
            try:
                imagem_local.frame_do_video(video, frame, segundo=1.0)
                fundo = frame
            except Exception:
                pass
            capa = imagem_local.Capa(
                titulo=plano.get("title") or "",
                subtitulo=plano.get("brand") or "",
                selo=plano.get("cta") or "",
                formato="vertical" if plano["layout"].startswith("vertical") else "horizontal",
                fundo=fundo,
            ).render(pasta / f"{adaptation_id}_capa.jpg")
            extras["cover_path"] = str(capa)
            if fundo:
                Path(fundo).unlink(missing_ok=True)
        except Exception as erro:
            problemas.append(f"capa: {erro}")

    if plano.get("narracao"):
        texto = (plano.get("description") or plano.get("title") or "").strip()
        if not texto:
            problemas.append("narracao: sem texto para narrar")
        else:
            try:
                extras["narration_path"] = str(
                    voz_local.Narracao(texto).render(pasta / f"{adaptation_id}_narracao.wav")
                )
            except Exception as erro:
                problemas.append(f"narracao: {erro}")

    extras["extras_error"] = "; ".join(problemas)
    return extras


def _ffmpeg() -> str:
    import os

    return os.getenv("IMPORT_FFMPEG", "ffmpeg")


def _sonda(caminho: Path) -> dict:
    """Medidas da parte de video. Sem elas nao da para juntar intro e outro."""
    import os
    import subprocess

    comando = [
        os.getenv("IMPORT_FFPROBE", "ffprobe"), "-v", "error",
        "-show_streams", "-show_format", "-of", "json", str(caminho),
    ]
    dados = json.loads(subprocess.run(comando, capture_output=True, text=True,
                                      check=True, timeout=120).stdout)
    streams = dados.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    fps = video.get("r_frame_rate") or "30/1"
    try:
        num, den = fps.split("/")
        fps_valor = round(float(num) / float(den or 1), 3) or 30
    except Exception:
        fps_valor = 30
    return {
        "largura": int(video.get("width") or 0),
        "altura": int(video.get("height") or 0),
        "fps": fps_valor,
        "tem_audio": any(s.get("codec_type") == "audio" for s in streams),
        "duracao": float(dados.get("format", {}).get("duration") or 0),
    }


def _escapar_para_filtro(caminho: Path) -> str:
    """O filtro `subtitles` do FFmpeg le o caminho como expressao.

    Dois-pontos separa opcoes e barra invertida escapa - num caminho do Windows
    ambos aparecem. Sem isto, `C:\\videos\\x.srt` vira opcao invalida e o render
    inteiro falha por causa da legenda.
    """
    texto = str(caminho).replace("\\", "/")
    return texto.replace(":", "\\:").replace("'", "\\'")


def queimar_legendas(video: Path, adaptation_id: str) -> dict:
    """Transcreve a fala e queima a legenda no video.

    Usa o mesmo faster-whisper que o pipeline ja roda na CPU. O SRT fica ao
    lado do video: serve para conferir o texto e para plataformas que aceitam
    legenda como arquivo.

    Falhar aqui NAO derruba a adaptacao - o video sem legenda continua valido.
    """
    import subprocess

    resultado = {"subtitle_path": "", "subtitle_error": ""}
    try:
        sys.path.insert(0, str(REPO_ROOT)) if str(REPO_ROOT) not in sys.path else None
        from transcriber import escrever_srt, transcrever_com_tempos

        falas = transcrever_com_tempos(video)
        if not falas:
            resultado["subtitle_error"] = "nenhuma fala reconhecida no material"
            return resultado

        srt = escrever_srt(falas, video.parent / f"{adaptation_id}.srt")
        temporario = video.parent / f"{adaptation_id}_legendado.mp4"
        estilo = "FontSize=18,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Alignment=2,MarginV=60"
        comando = [
            _ffmpeg(), "-y", "-i", str(video),
            "-vf", f"subtitles='{_escapar_para_filtro(srt)}':force_style='{estilo}'",
            "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            str(temporario),
        ]
        processo = subprocess.run(comando, capture_output=True, text=True, timeout=1800)
        if processo.returncode != 0 or not temporario.exists():
            resultado["subtitle_error"] = (processo.stderr or "")[-200:].strip() or "ffmpeg recusou a legenda"
            temporario.unlink(missing_ok=True)
            return resultado

        temporario.replace(video)
        resultado["subtitle_path"] = str(srt)
    except Exception as erro:
        resultado["subtitle_error"] = str(erro)[:200]
    return resultado


def juntar_intro_outro(video: Path, plano: dict, adaptation_id: str) -> dict:
    """Cola intro e/ou outro no material adaptado.

    Cada parte e normalizada para a resolucao e o fps do video principal antes
    do concat - o filtro exige isso, e um outro em 720p num video 1080x1920
    quebraria a montagem.

    Parte sem faixa de audio ganha silencio da propria duracao: sem isso o
    concat com audio falha e o lote inteiro para por causa de uma vinheta muda.
    """
    import subprocess

    resultado = {"intro_outro_error": ""}
    intro = Path(plano["intro_path"]) if plano.get("intro_path") else None
    outro = Path(plano["outro_path"]) if plano.get("outro_path") else None
    if not intro and not outro:
        return resultado

    try:
        principal = _sonda(video)
        largura, altura = principal["largura"], principal["altura"]
        fps = principal["fps"]
        partes = [p for p in (intro, video, outro) if p]

        entradas, filtros, rotulos = [], [], []
        silencios = []
        for indice, parte in enumerate(partes):
            medida = _sonda(parte)
            entradas += ["-i", str(parte)]
            filtros.append(
                f"[{indice}:v]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{indice}]"
            )
            if medida["tem_audio"]:
                filtros.append(f"[{indice}:a]aresample=async=1,aformat=sample_rates=44100:channel_layouts=stereo[a{indice}]")
                rotulos.append((f"v{indice}", f"a{indice}"))
            else:
                silencios.append((indice, medida["duracao"] or 1.0))
                rotulos.append((f"v{indice}", f"mudo{indice}"))

        base_silencio = len(partes)
        for posicao, (indice, duracao) in enumerate(silencios):
            entradas += ["-f", "lavfi", "-t", f"{duracao:.3f}",
                         "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            filtros.append(f"[{base_silencio + posicao}:a]aformat=sample_rates=44100:channel_layouts=stereo[mudo{indice}]")

        cadeia = "".join(f"[{v}][{a}]" for v, a in rotulos)
        filtros.append(f"{cadeia}concat=n={len(partes)}:v=1:a=1[vfinal][afinal]")

        destino = video.parent / f"{adaptation_id}_completo.mp4"
        comando = [
            _ffmpeg(), "-y", *entradas,
            "-filter_complex", ";".join(filtros),
            "-map", "[vfinal]", "-map", "[afinal]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destino),
        ]
        processo = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
        if processo.returncode != 0 or not destino.exists():
            resultado["intro_outro_error"] = (processo.stderr or "")[-200:].strip() or "ffmpeg recusou a montagem"
            destino.unlink(missing_ok=True)
            return resultado
        destino.replace(video)
    except Exception as erro:
        resultado["intro_outro_error"] = str(erro)[:200]
    return resultado


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
    if adaptacao["status"] not in {"planned", "render_queued", "failed"}:
        raise ImportError_(
            f"Adaptacao em {adaptacao['status']} nao pode ser renderizada de novo"
        )

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

        # Legenda antes da montagem: o SRT tem os tempos do material adaptado,
        # e colar a intro primeiro empurraria todas as falas para frente.
        acabamento = {}
        if plano.get("subtitles"):
            acabamento.update(queimar_legendas(destino, adaptation_id))
        acabamento.update(juntar_intro_outro(destino, plano, adaptation_id))

        # Valida depois do acabamento: intro e outro mudam duracao e podem
        # mudar dimensao, entao validar antes conferiria outro arquivo.
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

    extras = _gerar_extras(plano, destino, adaptation_id)
    # Legenda e vinheta sao acabamento: falha nelas vira aviso ao lado do
    # video pronto, nunca adaptacao perdida.
    avisos = [extras.get("extras_error", ""), acabamento.get("subtitle_error", ""),
              acabamento.get("intro_outro_error", "")]
    extras["extras_error"] = "; ".join(x for x in avisos if x)

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
                    # Acabamento entra aqui e nao em coluna propria: banco ja em
                    # producao, e ALTER TABLE por causa de dois campos opcionais
                    # nao se paga.
                    "subtitle_path": acabamento.get("subtitle_path", ""),
                },
                ensure_ascii=False,
            ),
            "error": "",
            "updated_at": agora(),
            **extras,
        },
    )
