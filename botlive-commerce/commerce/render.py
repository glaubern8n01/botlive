"""Renderiza o criativo aprovado em MP4 vertical. Local, sem API paga.

Era o buraco do modulo: o Commerce Studio montava roteiro, gancho, QA de claims
e o pacote da live - e nao saia video nenhum. Sem isto o operador nao tinha o
que postar, e o pipeline comercial parava no papel.

O que entra no video
--------------------
  imagens do produto (as que TEM direito declarado na biblioteca)
  + narracao do roteiro (Piper, CPU)
  + gancho no comeco e CTA no fim
  = MP4 1080x1920

Sem foto de produto na biblioteca, entra o card grafico do modulo de midia.
Nunca uma foto inventada: imagem falsa de produto e propaganda enganosa, nao
criativo - a mesma regra que ja vale no CardProduto.

Nada de geracao por difusao aqui. Foi medido (docs/AUDITORIA-FERRAMENTAS-MIDIA.md):
a maquina tem RX 580 de 4 GB fora do CUDA e do ROCm, e a VPS nao tem GPU. O que
roda de verdade e composicao com FFmpeg e Pillow - e e o suficiente para video
de afiliado, que e foto de produto, texto e voz.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .store import CommerceError, RAIZ, agora, atualizar, listar, obter


LARGURA, ALTURA = 1080, 1920
FFMPEG = os.getenv("COMMERCE_FFMPEG", "ffmpeg")
SEGUNDOS_DO_GANCHO = 3.0
SEGUNDOS_DO_CTA = 4.0
# Video de afiliado curto demais nao vende e longo demais ninguem ve.
DURACAO_MINIMA = 8.0
DURACAO_MAXIMA = float(os.getenv("COMMERCE_RENDER_MAX_SEGUNDOS", "90"))


def pasta_de_saida() -> Path:
    destino = Path(os.getenv("COMMERCE_RENDER_DIR", RAIZ / "data" / "renders"))
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _media_local():
    """Carrega os executores locais de imagem e voz.

    Import tardio e por caminho: botlive-media nao pode virar dependencia dura
    do commerce - sem ele o resto do modulo continua funcionando.
    """
    raiz = RAIZ.parent / "botlive-media"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from mediastack.executors import imagem_local, voz_local

    return imagem_local, voz_local


def _escapar(texto: str) -> str:
    """drawtext trata dois-pontos, aspa e barra invertida como sintaxe."""
    return texto.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def imagens_do_produto(product_id: str, limite: int = 6) -> list:
    """Fotos com direito declarado. Asset sem direito nao entra - regra do modulo."""
    assets = listar("commerce_assets", 100, where="product_id=? AND kind=?",
                    params=(product_id, "imagem"))
    caminhos = []
    for asset in assets:
        caminho = Path(asset["path"])
        if caminho.is_file() and (asset["rights"] or "").strip():
            caminhos.append(caminho)
    return caminhos[:limite]


def texto_narrado(criativo: dict) -> str:
    """Gancho + roteiro + CTA, nesta ordem. Nada e reescrito aqui."""
    partes = [criativo.get("hook") or "", criativo.get("script") or "", criativo.get("cta") or ""]
    return " ".join(x.strip() for x in partes if x and x.strip())


def montar_comando(imagens: list, narracao: Path | None, saida: Path,
                   gancho: str, cta: str, duracao: float) -> list:
    """Monta a chamada do FFmpeg. Separado do render para poder ser testado.

    Cada imagem fica no ar por uma fatia igual da narracao. O gancho aparece nos
    primeiros segundos e o CTA nos ultimos - `enable=between(t,...)` liga e
    desliga o texto sem precisar cortar o video em pedacos.
    """
    if not imagens:
        raise CommerceError("Sem imagem para renderizar")

    por_imagem = max(1.5, duracao / len(imagens))
    comando = [FFMPEG, "-y"]
    for imagem in imagens:
        comando += ["-loop", "1", "-t", f"{por_imagem:.3f}", "-i", str(imagem)]
    if narracao:
        comando += ["-i", str(narracao)]

    partes = []
    for indice, _ in enumerate(imagens):
        # zoompan da um respiro de movimento: imagem parada por 15s parece erro.
        partes.append(
            f"[{indice}:v]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=decrease,"
            f"pad={LARGURA}:{ALTURA}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
            f"zoompan=z='min(zoom+0.0008,1.12)':d={int(por_imagem * 30)}:"
            f"s={LARGURA}x{ALTURA}:fps=30[v{indice}]"
        )
    entradas = "".join(f"[v{i}]" for i in range(len(imagens)))
    partes.append(f"{entradas}concat=n={len(imagens)}:v=1:a=0[base]")

    atual = "base"
    tamanho_texto = int(LARGURA * 0.062)
    if gancho.strip():
        partes.append(
            f"[{atual}]drawtext=text='{_escapar(gancho.strip())}':fontcolor=white:"
            f"fontsize={tamanho_texto}:borderw=4:bordercolor=black@0.85:"
            f"box=1:boxcolor=black@0.45:boxborderw=20:x=(w-text_w)/2:y=h*0.12:"
            f"enable='between(t,0,{SEGUNDOS_DO_GANCHO})'[comgancho]"
        )
        atual = "comgancho"
    if cta.strip():
        inicio_cta = max(0.0, duracao - SEGUNDOS_DO_CTA)
        partes.append(
            f"[{atual}]drawtext=text='{_escapar(cta.strip())}':fontcolor=white:"
            f"fontsize={tamanho_texto}:borderw=4:bordercolor=black@0.85:"
            f"box=1:boxcolor=black@0.55:boxborderw=20:x=(w-text_w)/2:y=h*0.82:"
            f"enable='between(t,{inicio_cta:.2f},{duracao:.2f})'[final]"
        )
        atual = "final"

    comando += ["-filter_complex", ";".join(partes), "-map", f"[{atual}]"]
    if narracao:
        comando += ["-map", f"{len(imagens)}:a", "-c:a", "aac", "-b:a", "128k", "-shortest"]
    comando += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)]
    return comando


def renderizar(creative_id: str, exigir_aprovacao: bool | None = None) -> dict:
    """Gera o MP4 do criativo. Falha vira erro legivel, nunca arquivo pela metade."""
    criativo = obter("commerce_creatives", creative_id)
    if not criativo:
        raise CommerceError("Criativo inexistente")

    if exigir_aprovacao is None:
        exigir_aprovacao = os.getenv("COMMERCE_RENDER_EXIGE_APROVACAO", "true").lower() == "true"
    if exigir_aprovacao and criativo["status"] != "approved":
        raise CommerceError(
            f"Criativo em {criativo['status']}: so renderiza depois do QA e da aprovacao humana"
        )

    produto = obter("commerce_products", criativo["product_id"])
    if not produto:
        raise CommerceError("Produto do criativo sumiu")

    imagem_local, voz_local = _media_local()
    saida = pasta_de_saida() / f"{creative_id}.mp4"
    trabalho = pasta_de_saida() / creative_id
    trabalho.mkdir(parents=True, exist_ok=True)

    imagens = imagens_do_produto(produto["id"])
    if not imagens:
        # Sem foto com direito declarado, o card grafico entra no lugar - e o
        # video sai dizendo o que e, em vez de inventar uma foto.
        card = imagem_local.CardProduto(
            titulo=produto["title"],
            preco=f"R$ {float(produto['price'] or 0):.2f}".replace(".", ",") if produto.get("price") else "",
            cta=criativo.get("cta") or "",
            marca=produto.get("brand") or "",
            formato="vertical",
        ).render(trabalho / "card.jpg")
        imagens = [Path(card)]

    narracao = None
    duracao = max(DURACAO_MINIMA, len(imagens) * 3.0)
    texto = texto_narrado(criativo)
    aviso_voz = ""
    if texto:
        try:
            narracao = voz_local.Narracao(texto).render(trabalho / "narracao.wav")
            duracao = voz_local.Narracao(texto).duracao(narracao)
        except Exception as erro:
            aviso_voz = f"narracao indisponivel: {erro}"
            narracao = None
    duracao = min(max(duracao, DURACAO_MINIMA), DURACAO_MAXIMA)

    comando = montar_comando(imagens, narracao, saida, criativo.get("hook") or "",
                             criativo.get("cta") or "", duracao)
    processo = subprocess.run(comando, capture_output=True, text=True, timeout=1800)
    if processo.returncode != 0 or not saida.exists():
        saida.unlink(missing_ok=True)
        raise CommerceError(f"FFmpeg recusou o render: {(processo.stderr or '')[-300:].strip()}")

    # output_path e a coluna que existe para isso desde a Fase 7 e estava vazia:
    # o modulo nunca tinha produzido arquivo nenhum para guardar ali.
    qa = json.loads(criativo.get("qa") or "{}")
    qa["render"] = {
        "arquivo": str(saida),
        "bytes": saida.stat().st_size,
        "duracao": round(duracao, 2),
        "imagens": len(imagens),
        "com_narracao": bool(narracao),
        "aviso": aviso_voz,
        "em": agora(),
    }
    atualizar("commerce_creatives", creative_id, {
        "output_path": str(saida),
        "qa": json.dumps(qa, ensure_ascii=False),
        "updated_at": agora(),
    })

    return {
        "creative_id": creative_id,
        "arquivo": str(saida),
        "bytes": saida.stat().st_size,
        "duracao": round(duracao, 2),
        "imagens": len(imagens),
        "narracao": bool(narracao),
        "aviso": aviso_voz,
    }
