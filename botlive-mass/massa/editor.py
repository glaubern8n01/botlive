"""Edicao em massa com FFmpeg local.

Tudo acontece na maquina: o documento e explicito em nao mandar video para
nuvem so para editar. Usa o FFmpeg que o BotLive ja depende.

Regra que virou codigo: a saida vai SEMPRE para `editados/`, nunca por cima
do original em `downloads/`. Um lote mal configurado pode ser refeito porque
a fonte continua intacta.

A cadeia de filtros e montada em ordem fixa - trim, velocidade, enquadramento,
mockup, logo, CTA - porque a ordem muda o resultado: aplicar logo antes do
enquadramento faria a logo ser cortada junto com a imagem.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from . import projetos, templates
from .store import MassaError, agora, atualizar, conectar, contar, inserir, listar, obter


# Extensoes que o editor aceita como entrada ao varrer uma pasta local.
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg")

# Mockup pode ser imagem ou video com transparencia (webm/vp9 alpha, mov
# prores 4444). Video precisa de tratamento diferente: entra em loop e o
# overlay termina junto com o video de base, senao a saida ficaria infinita.
MOCKUP_VIDEO_EXT = (".webm", ".mov", ".mp4", ".mkv")

FFMPEG = os.getenv("MASS_FFMPEG", "ffmpeg")
TIMEOUT = int(os.getenv("MASS_EDIT_TIMEOUT", "1800"))
WORKERS = int(os.getenv("MASS_EDITOR_WORKERS", "2"))

# Margem da logo e do CTA em fracao da largura - respira sem colar na borda.
MARGEM = 0.04


def _posicao(nome: str, largura: int, altura: int, margem: int) -> str:
    """Coordenadas do overlay em expressao FFmpeg (w/h = tamanho do overlay)."""
    mapa = {
        "superior-esquerda": (f"{margem}", f"{margem}"),
        "superior-direita": (f"W-w-{margem}", f"{margem}"),
        "inferior-esquerda": (f"{margem}", f"H-h-{margem}"),
        "inferior-direita": (f"W-w-{margem}", f"H-h-{margem}"),
        "centro": ("(W-w)/2", "(H-h)/2"),
        "superior": ("(W-w)/2", f"{margem}"),
        "inferior": ("(W-w)/2", f"H-h-{margem}"),
    }
    return ":".join(mapa.get(nome, mapa["inferior-direita"]))


def _partes_enquadramento(modo: str, entrada_rotulo: str, largura: int, altura: int) -> list:
    """Grafo de filtros do enquadramento, ja com rotulos.

    crop: preenche e corta o excesso (perde borda, nao deforma)
    fit:  cabe inteiro com barra preta
    blur: cabe inteiro sobre fundo borrado da propria imagem

    O blur precisa de varias partes com rotulo (split/overlay), por isso a
    funcao devolve lista e nao uma cadeia unica separada por virgula.
    """
    if modo == "crop":
        return [f"[{entrada_rotulo}]scale={largura}:{altura}:"
                f"force_original_aspect_ratio=increase,crop={largura}:{altura}[base]"]
    if modo == "fit":
        return [f"[{entrada_rotulo}]scale={largura}:{altura}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2:black[base]"]
    return [
        f"[{entrada_rotulo}]split=2[bgsrc][fgsrc]",
        f"[bgsrc]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
        f"crop={largura}:{altura},boxblur=luma_radius=40:luma_power=2[bg]",
        f"[fgsrc]scale={largura}:{altura}:force_original_aspect_ratio=decrease[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]",
    ]


def mockup_e_video(caminho: str) -> bool:
    """Mockup em video (com alpha) x imagem estatica - muda o comando."""
    return Path(caminho or "").suffix.lower() in MOCKUP_VIDEO_EXT


def _escapar_texto(texto: str) -> str:
    """drawtext trata dois-pontos, aspa simples e barra invertida como sintaxe."""
    return (texto.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'"))


def duracao_de(caminho: Path) -> float:
    """Duracao pelo ffprobe. Precisa dela para cortar o fim sem adivinhar."""
    comando = [os.getenv("MASS_FFPROBE", "ffprobe"), "-v", "error",
               "-show_entries", "format=duration", "-of",
               "default=noprint_wrappers=1:nokey=1", str(caminho)]
    try:
        saida = subprocess.run(comando, capture_output=True, text=True,
                               check=True, timeout=60).stdout.strip()
        return float(saida)
    except Exception:
        return 0.0


def montar_comando(entrada: Path, saida: Path, template: dict,
                   amostra_segundos: float = 0, duracao: float = 0) -> list:
    """Monta a chamada do FFmpeg. Separado do render para poder ser testado.

    Ordem dos filtros e fixa e importa: velocidade -> enquadramento -> mockup
    -> logo -> CTA. Aplicar a logo antes do enquadramento faria ela ser
    cortada junto com a imagem.
    """
    largura, altura = templates.dimensoes(template)
    margem = int(largura * MARGEM)

    comando = [FFMPEG, "-y"]
    inicio = float(template.get("cortar_inicio") or 0)
    if inicio > 0:
        comando += ["-ss", str(inicio)]
    comando += ["-i", str(entrada)]

    indice = 1
    idx_mockup = idx_logo = None
    mock_video = bool(template.get("mockup_path")) and mockup_e_video(template["mockup_path"])
    if template.get("mockup_path"):
        # -stream_loop vale para a entrada seguinte: o mockup repete ate o
        # video de base acabar. Sem isso um mockup de 2s cobriria so o comeco.
        if mock_video:
            comando += ["-stream_loop", "-1"]
        comando += ["-i", str(template["mockup_path"])]
        idx_mockup = indice
        indice += 1
    if template.get("logo_path"):
        comando += ["-i", str(template["logo_path"])]
        idx_logo = indice
        indice += 1

    partes = []
    velocidade = float(template.get("velocidade") or 1.0)
    rotulo = "0:v"
    if velocidade != 1.0:
        partes.append(f"[0:v]setpts={1 / velocidade:.6f}*PTS[v_spd]")
        rotulo = "v_spd"

    partes += _partes_enquadramento(
        template.get("modo_horizontal") or "blur", rotulo, largura, altura
    )
    atual = "base"

    if idx_mockup is not None:
        opacidade = float(template.get("mockup_opacidade") or 1.0)
        partes.append(f"[{idx_mockup}:v]scale={largura}:{altura},format=rgba,"
                      f"colorchannelmixer=aa={opacidade}[mock]")
        # shortest=1 so no video: com a entrada em loop infinito, sem isso a
        # saida nunca terminaria. Imagem estatica nao precisa.
        fim_overlay = ":shortest=1" if mock_video else ""
        partes.append(f"[{atual}][mock]overlay=0:0{fim_overlay}[comock]")
        atual = "comock"

    if idx_logo is not None:
        escala = float(template.get("logo_escala") or 0.15)
        opacidade = float(template.get("logo_opacidade") or 0.9)
        partes.append(f"[{idx_logo}:v]scale={int(largura * escala)}:-1,format=rgba,"
                      f"colorchannelmixer=aa={opacidade}[logo]")
        pos = _posicao(template.get("logo_posicao") or "inferior-direita",
                       largura, altura, margem)
        partes.append(f"[{atual}][logo]overlay={pos}[cologo]")
        atual = "cologo"

    texto = (template.get("cta_texto") or "").strip()
    if texto:
        tamanho = int(largura * float(template.get("cta_tamanho") or 0.055))
        pos_nome = template.get("cta_posicao") or "inferior"
        y = {"superior": f"{margem}", "centro": "(h-text_h)/2"}.get(
            pos_nome, f"h-text_h-{margem}")
        partes.append(
            f"[{atual}]drawtext=text='{_escapar_texto(texto)}':fontcolor=white:"
            f"fontsize={tamanho}:borderw={max(2, tamanho // 12)}:bordercolor=black@0.9:"
            f"box=1:boxcolor=black@0.35:boxborderw={tamanho // 4}:"
            f"x=(w-text_w)/2:y={y}[final]"
        )
        atual = "final"

    comando += ["-filter_complex", ";".join(partes), "-map", f"[{atual}]"]

    audio = template.get("audio") or "manter"
    if audio == "remover":
        comando += ["-an"]
    else:
        filtros_audio = []
        if velocidade != 1.0:
            filtros_audio.append(f"atempo={velocidade}")
        volume = float(template.get("volume") or 1.0)
        if volume != 1.0:
            filtros_audio.append(f"volume={volume}")
        if audio == "normalizar":
            filtros_audio.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        comando += ["-map", "0:a?"]
        if filtros_audio:
            comando += ["-af", ",".join(filtros_audio)]
        comando += ["-c:a", "aac", "-b:a", "128k"]

    # Cortar o fim exige saber a duracao: -t recebe o que sobra depois dos
    # dois cortes. Sem duracao medida, o corte de fim e ignorado em vez de
    # gerar um video vazio.
    fim = float(template.get("cortar_fim") or 0)
    if amostra_segundos > 0:
        comando += ["-t", str(amostra_segundos)]
    elif fim > 0 and duracao > 0:
        restante = duracao - inicio - fim
        if restante <= 0:
            raise MassaError(
                f"cortes maiores que o video ({duracao:.1f}s): "
                f"inicio {inicio}s + fim {fim}s"
            )
        comando += ["-t", f"{restante / max(velocidade, 0.01):.3f}"]

    comando += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)]
    return comando


def enfileirar(projeto_id: str, template_id: str, entradas: list) -> dict:
    """Coloca arquivos na fila de edicao, um job por video."""
    projeto = projetos.exigir(projeto_id)
    templates.exigir(template_id)
    criados = []
    for entrada in entradas:
        caminho = Path(entrada)
        if not caminho.is_file():
            continue
        item = inserir("mass_edicoes", {
            "projeto_id": projeto["id"],
            "template_id": template_id,
            "entrada": str(caminho),
            "status": "queued",
            "created_at": agora(),
        })
        criados.append(item["id"])
    return {"enfileirados": len(criados), "ids": criados}


def enfileirar_baixados(projeto_id: str, template_id: str) -> dict:
    """Atalho do documento: [ADICIONAR TODOS AO EDITOR] apos o download."""
    baixados = listar("mass_downloads", 2000, "projeto_id=? AND status='completed'",
                      (projeto_id,))
    resultado = enfileirar(projeto_id, template_id, [x["arquivo"] for x in baixados if x["arquivo"]])
    # liga cada edicao ao download de origem, para o historico fechar
    for edicao_id, download in zip(resultado["ids"], baixados):
        atualizar("mass_edicoes", edicao_id, {"download_id": download["id"]})
    return resultado


def varrer_pasta(caminho: str, recursivo: bool = False) -> list:
    """Lista os videos de uma pasta local, em ordem de nome.

    Serve o caso do documento: editar em lote videos que o operador ja tem no
    disco, sem passar pelo downloader. Nao entra em `editados/` nem em
    `exports/` do proprio modulo - reprocessar a propria saida so geraria
    video sobre video.
    """
    pasta = Path(caminho or "")
    if not pasta.is_dir():
        raise MassaError(f"Pasta nao encontrada: {pasta}")
    padrao = "**/*" if recursivo else "*"
    ignoradas = {"editados", "exports", "previas"}
    achados = []
    for x in sorted(pasta.glob(padrao)):
        if not x.is_file() or x.suffix.lower() not in VIDEO_EXT:
            continue
        # so ignora subpasta DENTRO da escolhida - se o operador apontar
        # direto para `editados/`, e porque ele quer aquilo mesmo.
        if ignoradas & set(x.relative_to(pasta).parts[:-1]):
            continue
        achados.append(x)
    if not achados:
        raise MassaError(f"Nenhum video em {pasta} (aceito: {', '.join(VIDEO_EXT)})")
    return [str(x) for x in achados]


def enfileirar_pasta(projeto_id: str, template_id: str, caminho: str,
                     recursivo: bool = False) -> dict:
    """[SELECIONAR PASTA LOCAL] - varre e enfileira de uma vez."""
    entradas = varrer_pasta(caminho, recursivo)
    resultado = enfileirar(projeto_id, template_id, entradas)
    resultado["encontrados"] = len(entradas)
    resultado["pasta"] = str(Path(caminho))
    return resultado


def editar_item(edicao_id: str) -> dict:
    """Renderiza um item. Falha vira status + motivo, sem derrubar o lote."""
    item = obter("mass_edicoes", edicao_id)
    if not item:
        raise MassaError("Item de edicao inexistente")
    if item["status"] in {"completed", "cancelled"}:
        return item

    projeto = projetos.exigir(item["projeto_id"])
    template = templates.exigir(item["template_id"])
    entrada = Path(item["entrada"])
    if not entrada.is_file():
        return atualizar("mass_edicoes", edicao_id,
                         {"status": "failed", "erro": "arquivo de entrada sumiu"})

    # NUNCA por cima do original: saida sempre em editados/
    saida = projetos.pasta_de(projeto, "editados") / f"{entrada.stem}_editado.mp4"
    atualizar("mass_edicoes", edicao_id,
              {"status": "running", "tentativas": int(item["tentativas"]) + 1})

    try:
        comando = montar_comando(entrada, saida, template,
                                 duracao=duracao_de(entrada))
        processo = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return atualizar("mass_edicoes", edicao_id,
                         {"status": "failed", "erro": "tempo esgotado no render"})
    except FileNotFoundError:
        return atualizar("mass_edicoes", edicao_id,
                         {"status": "failed", "erro": "ffmpeg nao encontrado"})

    if processo.returncode != 0 or not saida.is_file():
        return atualizar("mass_edicoes", edicao_id, {
            "status": "failed",
            "erro": (processo.stderr or "")[-300:].strip() or "ffmpeg falhou",
        })

    largura, altura = templates.dimensoes(template)
    return atualizar("mass_edicoes", edicao_id, {
        "status": "completed", "saida": str(saida), "progresso": 1.0,
        "largura": largura, "altura": altura, "erro": "", "editado_em": agora(),
    })


def previa(entrada: str, template_id: str, segundos: float = 3.0) -> Path:
    """Amostra curta antes de processar o lote inteiro.

    O documento pede exatamente isso: nao renderizar 100 videos para descobrir
    que a logo ficou no lugar errado.
    """
    template = templates.exigir(template_id)
    origem = Path(entrada)
    if not origem.is_file():
        raise MassaError("Arquivo de entrada inexistente")
    destino = Path(__file__).resolve().parents[1] / "data" / "previas"
    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / f"previa_{origem.stem}_{template_id[:8]}.mp4"

    processo = subprocess.run(
        montar_comando(origem, saida, template, amostra_segundos=segundos),
        capture_output=True, text=True, timeout=300,
    )
    if processo.returncode != 0 or not saida.is_file():
        raise MassaError(f"previa falhou: {(processo.stderr or '')[-300:].strip()}")
    return saida


def rodar_fila(projeto_id: str, maximo: int = None) -> dict:
    """Processa itens da fila. `maximo` padrao vem de MASS_EDITOR_WORKERS."""
    projetos.exigir(projeto_id)
    limite = maximo or WORKERS
    with conectar() as db:
        linhas = db.execute(
            "SELECT * FROM mass_edicoes WHERE projeto_id=? AND status='queued' "
            "ORDER BY rowid LIMIT ?", (projeto_id, max(1, limite)),
        ).fetchall()
    processados = []
    for linha in linhas:
        resultado = editar_item(linha["id"])
        processados.append({"id": linha["id"], "status": resultado["status"],
                            "erro": resultado.get("erro", "")})
    return {"processados": len(processados), "itens": processados,
            "fila": contar("mass_edicoes", "projeto_id=?", (projeto_id,))}


def mudar_status(edicao_id: str, status: str) -> dict:
    permitidos = {"queued", "paused", "cancelled"}
    if status not in permitidos:
        raise MassaError(f"Status invalido: {status}. Use {sorted(permitidos)}")
    if not obter("mass_edicoes", edicao_id):
        raise MassaError("Item inexistente")
    campos = {"status": status}
    if status == "queued":
        campos["erro"] = ""
    return atualizar("mass_edicoes", edicao_id, campos)


def fila(projeto_id: str, limite: int = 500) -> dict:
    resumo = contar("mass_edicoes", "projeto_id=?", (projeto_id,))
    total = sum(resumo.values()) or 1
    return {
        "itens": listar("mass_edicoes", limite, "projeto_id=?", (projeto_id,)),
        "resumo": resumo,
        "progresso": round(resumo.get("completed", 0) / total, 3),
    }
