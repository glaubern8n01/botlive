"""Gera a matriz de decisao em Markdown.

  python botlive-media/mediastack/report.py > docs/STACK-MEDIA.md

O documento sai do codigo de proposito: matriz escrita a mao envelhece e passa
a mentir. Regerar depois de cada auditoria registrada.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mediastack import catalog, matrix, profiles  # noqa: E402


CABECALHO = (
    ("id", "Ferramenta"),
    ("capacidades", "Cobre"),
    ("prioridade_declarada", "Prioridade"),
    ("licenca", "Licença"),
    ("custo", "Custo"),
    ("vram_gb", "VRAM"),
    ("ram_gb", "RAM"),
    ("headless", "Headless"),
    ("api", "API"),
    ("cli", "CLI"),
    ("maturidade", "Maturidade"),
    ("auditoria", "Auditoria"),
)


def _valor(linha, chave):
    valor = linha.get(chave)
    if isinstance(valor, list):
        return ", ".join(valor) or "—"
    if valor is True:
        return "sim"
    if valor is False:
        return "não"
    return str(valor)


def markdown() -> str:
    resumo = matrix.resumo_auditoria()
    proposta = matrix.menor_conjunto()
    adotavel = matrix.menor_conjunto(somente_auditadas=True)

    partes = [
        "# Stack de mídia — matriz de decisão",
        "",
        "> Gerado por `botlive-media/mediastack/report.py`. Não editar à mão:",
        "> regenere depois de registrar cada auditoria.",
        "",
        "## Estado da auditoria",
        "",
        f"- Ferramentas no catálogo: **{resumo['total']}**",
        f"- Prontas para produção: **{len(resumo['prontas_para_producao'])}**",
        "",
    ]
    for nivel, itens in resumo["por_nivel"].items():
        partes.append(f"- {nivel}: {len(itens)} — {', '.join(itens)}")
    partes += [
        "",
        "Nenhum campo abaixo foi medido por mim. `não medido` quer dizer exatamente",
        "isso: ninguém rodou, leu a licença nem mediu VRAM. Não é zero, não é falso.",
        "",
        "## Matriz",
        "",
        "| " + " | ".join(rotulo for _, rotulo in CABECALHO) + " |",
        "|" + "|".join(["---"] * len(CABECALHO)) + "|",
    ]
    for linha in matrix.matriz():
        partes.append("| " + " | ".join(_valor(linha, chave) for chave, _ in CABECALHO) + " |")

    partes += [
        "",
        "## Proposta de menor conjunto (a validar)",
        "",
        f"Capacidades alvo: {', '.join(proposta['capacidades_alvo'])}",
        "",
        f"**Ferramentas propostas:** {', '.join(proposta['ferramentas'])}",
        "",
        "| Capacidade | Ferramenta proposta |",
        "|---|---|",
    ]
    for capacidade, ferramenta in proposta["cobertura"].items():
        partes.append(f"| {capacidade} | {ferramenta or '— sem candidato —'} |")

    partes += [
        "",
        f"Pronta para produção: **{'sim' if proposta['pronta_para_producao'] else 'não'}**",
        f" — falta auditar {len(proposta['nao_auditadas'])} ferramenta(s): "
        f"{', '.join(proposta['nao_auditadas']) or 'nenhuma'}.",
        "",
        f"Campos pendentes: {', '.join(proposta['campos_pendentes']) or 'nenhum'}",
        "",
        "## Stack adotável hoje (só auditadas)",
        "",
        f"Ferramentas: {', '.join(adotavel['ferramentas']) or '**nenhuma**'}",
        "",
        f"Capacidades ainda descobertas: {', '.join(adotavel['sem_cobertura']) or 'nenhuma'}",
        "",
        "## Perfis de hardware",
        "",
        "| Perfil | VRAM | RAM | Quando usar |",
        "|---|---|---|---|",
    ]
    for perfil in profiles.PERFIS.values():
        partes.append(
            f"| {perfil.nome} | {perfil.vram_gb} GB | {perfil.ram_gb} GB | {perfil.descricao} |"
        )

    partes += [
        "",
        "## Repositórios",
        "",
        "| Ferramenta | Repositório | O que se diz que ela faz |",
        "|---|---|---|",
    ]
    for item in catalog.todas():
        partes.append(f"| {item.id} | {item.repositorio} | {item.descricao_declarada} |")

    partes += [
        "",
        "A coluna acima é o que o documento do projeto **declara** sobre cada",
        "ferramenta — não é verificação. Auditar antes de instalar.",
        "",
    ]
    return "\n".join(partes)


if __name__ == "__main__":
    print(markdown())
