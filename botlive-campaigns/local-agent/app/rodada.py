"""Uma rodada completa de campanha, do inicio ao fim, sob demanda.

O worker faz isso sozinho a cada 10 minutos. Este modulo existe para o caso em
que voce quer UMA campanha, AGORA, e quer ver cada etapa acontecendo:

    python -m app.rodada "Juninho"
    python -m app.rodada "Juninho" --cortes 3 --minutos-de-live 10

Faz o caminho inteiro: busca na fonte (gravando uma janela se ela estiver ao
vivo), transcreve, escolhe os trechos pela fala, renderiza o vertical, queima o
selo que a campanha exige e roda as regras. Nada e publicado - o corte para na
revisao, que e onde o projeto sempre quis que parasse.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from . import engine, fala, fontes, media, selo
from .rules import evaluate, summary
from .store import get, rows


def achar_campanha(termo: str) -> dict:
    termo = (termo or "").strip().lower()
    candidatas = [c for c in rows("campaign_campaigns", 200, 0)
                  if termo in c["name"].lower() or c["id"].startswith(termo)]
    if not candidatas:
        raise SystemExit(f"Nenhuma campanha bate com {termo!r}")
    ativas = [c for c in candidatas if c["status"] == "active"]
    # Ha dezenas de rascunhos catalogados com nomes parecidos; a ativa ganha.
    return (ativas or candidatas)[0]


def capturar(campanha: dict, log) -> list:
    materiais = []
    for fonte in rows("campaign_sources", 50, 0,
                      "campaign_id=? AND enabled=1", (campanha["id"],)):
        log(f"fonte {fonte['network']}: {fonte['url']}")
        resultado = fontes.buscar(fonte["id"])
        if resultado["materiais"]:
            for material in resultado["materiais"]:
                tamanho = os.path.getsize(material["local_path"]) / 1e6
                log(f"   baixado: {material['name'][:60]} ({tamanho:.0f} MB)")
            materiais.extend(resultado["materiais"])
        else:
            log(f"   {resultado['motivo']}")
    return materiais


def cortar(campanha: dict, material: dict, quantos: int, log) -> list:
    regras = json.loads(campanha["rules"])
    hashtags = json.loads(campanha["hashtags"])
    mencoes = json.loads(campanha["mentions"])
    legenda = " ".join(hashtags + mencoes)

    log("transcrevendo e escolhendo pelos trechos falados...")
    janelas = fala.detectar(material["local_path"], max_candidates=quantos,
                            min_gap_seconds=60, janela_min=20,
                            janela_max=float(campanha.get("max_duration") or 60))
    if not janelas:
        log("sem fala reconhecida - material mudo segue pelo detector de movimento")
        return []
    log(f"{len(janelas)} trecho(s)")

    campanha = {**campanha, "rules": regras, "hashtags": hashtags, "mentions": mencoes}
    prontos = []
    for indice, janela in enumerate(janelas, 1):
        saida = (media.output_root() / campanha["id"] /
                 f"{material['id'][:8]}-{indice:02d}.mp4")
        log(f"[{indice}] {janela['inicio']:.0f}s-{janela['fim']:.0f}s "
            f"score={janela['score']} :: {janela['texto'][:90]}")
        render = engine.render(material["local_path"], saida, janela["inicio"],
                               janela["fim"], os.getenv("CAMPAIGNS_LAYOUT", "vertical-crop"),
                               legenda, "", " ".join(mencoes), regras.get("cta", ""))
        render["selo"] = selo.aplicar(render["path"], regras.get("selo") or {})
        if render["selo"]["aplicado"]:
            render["sha256"] = media.sha256(render["path"])
            log(f"    selo: {render['selo']['tipo']}")
        candidato = {"source_start": janela["inicio"], "source_end": janela["fim"],
                     "caption": legenda, "material_id": material["id"]}
        checks = evaluate(campanha, candidato, {**render, "authorized": 1, "duplicate_of": None})
        estado = summary(checks)
        log(f"    {render['width']}x{render['height']} "
            f"{render['duration_seconds']:.0f}s -> regras: {estado}")
        for check in checks:
            if check["status"] == "rejected":
                log(f"      REPROVADO {check['rule_key']}: {check['reason']}")
        prontos.append({"arquivo": render["path"], "estado": estado, "legenda": legenda})
    return prontos


def main(argv=None):
    parser = argparse.ArgumentParser(description="Roda uma campanha de ponta a ponta")
    parser.add_argument("campanha", help="parte do nome ou do id")
    parser.add_argument("--cortes", type=int, default=1)
    parser.add_argument("--minutos-de-live", type=int, default=0,
                        help="quanto gravar quando a fonte estiver ao vivo")
    parser.add_argument("--material", default="", help="usa material ja baixado, sem buscar")
    args = parser.parse_args(argv)

    if args.minutos_de_live:
        os.environ["CAMPAIGNS_LIVE_MINUTOS"] = str(args.minutos_de_live)
        fontes.MINUTOS_DE_LIVE = args.minutos_de_live

    inicio = time.time()

    def log(*mensagem):
        print(f"[{int(time.time() - inicio):5d}s]", *mensagem, flush=True)

    campanha = achar_campanha(args.campanha)
    log(f"campanha: {campanha['name']} ({campanha['id'][:8]})")

    if args.material:
        materiais = [get("campaign_materials", args.material)]
    else:
        materiais = capturar(campanha, log)
    if not materiais or not materiais[0]:
        log("nada novo para cortar")
        return 1

    prontos = cortar(campanha, materiais[0], args.cortes, log)
    for item in prontos:
        log(f"PRONTO [{item['estado']}] {item['arquivo']}")
        log(f"   legenda: {item['legenda']}")
    return 0 if prontos else 1


if __name__ == "__main__":
    raise SystemExit(main())
