from __future__ import annotations

import argparse

from clipper import preparar_pastas
from live_watcher import monitorar_live
from overlay_editor import OverlayConfig
from post_live_processor import processar_pos_live


def _overlay_from_args(args: argparse.Namespace) -> OverlayConfig:
    return OverlayConfig(
        title=args.titulo,
        description=args.descricao,
        brand=args.marca,
        cta=args.cta,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Robo autonomo de cortes dark 9:16 sem chat.")
    parser.add_argument("source", help="URL da live/video ou caminho de um arquivo local.")
    parser.add_argument("--modo", choices=["atual", "live", "pos-live"], default="atual")
    parser.add_argument("--max-cortes", type=int, default=8, help="Quantidade maxima de cortes.")
    parser.add_argument("--sample-every-seconds", type=int, default=3)
    parser.add_argument("--analysis-window-seconds", type=int, default=6)
    parser.add_argument("--min-gap-seconds", type=int, default=45)
    parser.add_argument("--block-seconds", type=int, default=45)
    parser.add_argument("--usar-momentos-salvos", action="store_true")
    parser.add_argument("--session-id", default=None, help="Identificador da sessao live para salvar/filtrar timestamps.")
    parser.add_argument("--vod-offset-seconds", type=int, default=0)
    parser.add_argument("--score-threshold", type=float, default=0.62)
    parser.add_argument("--max-blocks", type=int, default=None, help="Opcional para testes do modo live.")
    parser.add_argument("--titulo", default=None, help="Titulo opcional no topo do corte.")
    parser.add_argument("--descricao", default=None, help="Descricao curta opcional na tela.")
    parser.add_argument("--marca", default=None, help="Marca/nome do perfil opcional.")
    parser.add_argument("--cta", default=None, help="CTA opcional nos segundos finais.")
    args = parser.parse_args()

    preparar_pastas()

    if args.modo == "live":
        monitorar_live(
            source_url=args.source,
            block_seconds=args.block_seconds,
            max_cortes=args.max_cortes,
            session_id=args.session_id,
            score_threshold=args.score_threshold,
            sample_every_seconds=args.sample_every_seconds,
            analysis_window_seconds=args.analysis_window_seconds,
            max_blocks=args.max_blocks,
        )
        return

    # "atual" e "pos-live" compartilham o mesmo pipeline estavel.
    # Sem --modo, o comportamento continua sendo preparar fonte, analisar e gerar cortes.
    processar_pos_live(
        source=args.source,
        max_cortes=args.max_cortes,
        usar_momentos_salvos=args.usar_momentos_salvos if args.modo == "pos-live" else False,
        session_id=args.session_id if args.modo == "pos-live" else None,
        vod_offset_seconds=args.vod_offset_seconds if args.modo == "pos-live" else 0,
        sample_every_seconds=args.sample_every_seconds,
        analysis_window_seconds=args.analysis_window_seconds,
        min_gap_seconds=args.min_gap_seconds,
        overlay_config=_overlay_from_args(args),
    )
    print("[sistema] Finalizado.")


if __name__ == "__main__":
    main()
