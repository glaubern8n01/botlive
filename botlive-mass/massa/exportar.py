"""Exportacao: abrir a pasta, gerar ZIP, mandar para a fila de postagem.

O ZIP nasce em `exports/`, separado dos editados, para nao virar entrada do
proprio editor numa rodada seguinte.
"""

from __future__ import annotations

import os
import zipfile
from datetime import datetime
from pathlib import Path

from . import projetos
from .store import MassaError, agora, auditar, listar


LIMITE_ZIP_GB = float(os.getenv("MASS_ZIP_MAX_GB", "8"))


def editados(projeto_id: str) -> list:
    """Arquivos prontos do projeto, na ordem em que foram editados."""
    itens = listar("mass_edicoes", 2000, "projeto_id=? AND status='completed'", (projeto_id,))
    return [x["saida"] for x in itens if x["saida"] and Path(x["saida"]).is_file()]


def gerar_zip(projeto_id: str, nome: str | None = None) -> dict:
    """Junta os editados num ZIP. Nao inclui original nem arquivo de trabalho."""
    projeto = projetos.exigir(projeto_id)
    arquivos = editados(projeto_id)
    if not arquivos:
        raise MassaError("Nenhum video editado para exportar")

    total = sum(Path(x).stat().st_size for x in arquivos)
    if total > LIMITE_ZIP_GB * 1024 ** 3:
        raise MassaError(
            f"lote de {total / 1024 ** 3:.1f} GB acima do limite de {LIMITE_ZIP_GB} GB. "
            "Exporte em partes ou use a pasta direto."
        )

    destino = projetos.pasta_de(projeto, "exports")
    rotulo = nome or f"conteudo-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    caminho = destino / f"{rotulo}.zip"

    # ZIP_STORED: video ja e comprimido, deflate so gastaria CPU sem ganho.
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_STORED) as pacote:
        for arquivo in arquivos:
            pacote.write(arquivo, Path(arquivo).name)

    auditar("export.zip", "projeto", projeto_id,
            {"arquivos": len(arquivos), "bytes": caminho.stat().st_size})
    return {
        "zip": str(caminho),
        "arquivos": len(arquivos),
        "tamanho_mb": round(caminho.stat().st_size / 1024 ** 2, 1),
        "gerado_em": agora(),
    }


def resumo(projeto_id: str) -> dict:
    projeto = projetos.exigir(projeto_id)
    arquivos = editados(projeto_id)
    pasta_exports = projetos.pasta_de(projeto, "exports")
    return {
        "pasta_editados": str(projetos.pasta_de(projeto, "editados")),
        "pasta_exports": str(pasta_exports),
        "prontos": len(arquivos),
        "tamanho_mb": round(sum(Path(x).stat().st_size for x in arquivos) / 1024 ** 2, 1),
        "zips": sorted(p.name for p in pasta_exports.glob("*.zip")),
    }
