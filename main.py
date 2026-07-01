from __future__ import annotations

import argparse

from clipper import preparar_pastas
from live_watcher import monitorar_live
from overlay_editor import OverlayConfig
from post_live_processor import processar_pos_live
from vod_scanner import scan_vod_completo


def _overlay_from_args(args: argparse.Namespace) -> OverlayConfig:
    return OverlayConfig(
        title=args.titulo,
        description=args.descricao,
        brand=args.marca,
        cta=args.cta,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Robo autonomo de cortes dark para lives e VODs.")
    parser.add_argument("source", help="URL da live/video ou caminho de um arquivo local.")
    parser.add_argument("--modo", choices=["atual", "live", "pos-live", "scan-vod"], default="atual")
    parser.add_argument("--max-cortes", type=int, default=8, help="Quantidade maxima de cortes.")
    parser.add_argument("--sample-every-seconds", type=int, default=3)
    parser.add_argument("--analysis-window-seconds", type=int, default=6)
    parser.add_argument("--min-gap-seconds", type=int, default=120)
    parser.add_argument("--block-seconds", type=int, default=45)
    parser.add_argument("--clip-duration", type=int, default=60, help="Duracao final aproximada de cada corte em segundos.")
    parser.add_argument("--pre-roll-seconds", type=int, default=None, help="Segundos antes do pico que entram no corte.")
    parser.add_argument("--post-roll-seconds", type=int, default=None, help="Segundos depois do pico que entram no corte.")
    parser.add_argument(
        "--target-height",
        type=int,
        default=None,
        help="Altura maxima desejada para baixar trechos finais do VOD original, ex: 720 ou 1080.",
    )
    parser.add_argument(
        "--render-source",
        choices=["auto", "vod", "cache"],
        default="auto",
        help="Fonte do render pos-live: auto usa VOD original quando --target-height e informado; vod forca VOD; cache usa blocos locais.",
    )
    parser.add_argument(
        "--prefer-final-render-from-source",
        action="store_true",
        help="Atalho para preferir o VOD original como fonte dos cortes finais pos-live.",
    )
    parser.add_argument(
        "--output-layout",
        choices=["original", "vertical-fit", "vertical-crop"],
        default="original",
        help="Layout final: original preserva o video, vertical-fit encaixa em 1080x1920 sem crop, vertical-crop corta 9:16.",
    )
    parser.add_argument("--keep-intermediate", action="store_true", help="Mantem arquivos intermediarios como corte sem overlay.")
    parser.add_argument("--usar-momentos-salvos", action="store_true")
    parser.add_argument("--session-id", default=None, help="Identificador da sessao live para salvar/filtrar timestamps.")
    parser.add_argument("--vod-offset-seconds", type=int, default=0)
    parser.add_argument("--score-threshold", type=float, default=0.62)
    parser.add_argument("--max-blocks", type=int, default=None, help="Opcional para limitar blocos nos modos live/scan-vod.")
    parser.add_argument(
        "--content-filter",
        choices=["none", "football"],
        default="none",
        help="Filtro simples de conteudo para scan-vod. football prioriza blocos com campo/jogo.",
    )
    parser.add_argument(
        "--strict-football-filter",
        action="store_true",
        help="No scan-vod com football, rejeita entrevista/estudio/tela parada antes de salvar timestamp.",
    )
    parser.add_argument(
        "--focus-final-minutes",
        type=int,
        default=None,
        help="No scan-vod, analisa apenas os ultimos N minutos do VOD mantendo timestamps reais.",
    )
    parser.add_argument("--start-seconds", type=int, default=None, help="No scan-vod, inicia a analise neste segundo do VOD.")
    parser.add_argument("--end-seconds", type=int, default=None, help="No scan-vod, encerra a analise neste segundo do VOD.")
    parser.add_argument(
        "--max-scan-blocks",
        type=int,
        default=None,
        help="No scan-vod, limita quantos blocos serao analisados para teste rapido.",
    )
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

    if args.modo == "scan-vod":
        if not args.session_id:
            raise SystemExit("--session-id e obrigatorio no modo scan-vod.")
        scan_vod_completo(
            source_url=args.source,
            session_id=args.session_id,
            block_seconds=args.block_seconds,
            max_cortes=args.max_cortes,
            score_threshold=args.score_threshold,
            min_gap_seconds=args.min_gap_seconds,
            sample_every_seconds=args.sample_every_seconds,
            analysis_window_seconds=args.analysis_window_seconds,
            max_blocks=args.max_blocks,
            content_filter=args.content_filter,
            focus_final_minutes=args.focus_final_minutes,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
            max_scan_blocks=args.max_scan_blocks,
            strict_football_filter=args.strict_football_filter,
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
        clip_duration=args.clip_duration,
        pre_roll_seconds=args.pre_roll_seconds,
        post_roll_seconds=args.post_roll_seconds,
        overlay_config=_overlay_from_args(args),
        output_layout=args.output_layout,
        keep_intermediate=args.keep_intermediate,
        target_height=args.target_height,
        render_source="vod" if args.prefer_final_render_from_source else args.render_source,
    )
    print("[sistema] Finalizado.")


if __name__ == "__main__":
    main()
