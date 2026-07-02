from __future__ import annotations

import argparse
from pathlib import Path

from clipper import preparar_pastas
from football_content_filter import classify_football_content
from highlight_detector import detectar_melhores_momentos
from live_watcher import monitorar_live, monitorar_near_live
from moment_logger import salvar_momento
from overlay_editor import OverlayConfig
from post_live_processor import processar_pos_live
from runtime_paths import get_output_root, queue_file, run_logs_dir, set_output_root, set_output_tag
from source_downloader import resolver_fonte_video
from vod_scanner import scan_vod_completo


def _is_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "rtmp://", "m3u8://"))


def _overlay_from_args(args: argparse.Namespace) -> OverlayConfig:
    return OverlayConfig(
        title=args.titulo,
        description=args.descricao,
        brand=args.marca,
        cta=args.cta,
    )


def _salvar_timestamps_arquivo_local(
    source: str,
    session_id: str,
    max_cortes: int,
    sample_every_seconds: int,
    analysis_window_seconds: int,
    min_gap_seconds: int,
    score_threshold: float,
    content_filter: str,
    strict_football_filter: bool,
) -> int:
    video_path = resolver_fonte_video(source)
    print(f"[vod-clips] Arquivo local para analise: {video_path}")

    football_metadata: dict = {
        "content_filter": content_filter,
        "football_action": "save_ready",
        "football_label": "nao_avaliado",
    }
    if content_filter == "football":
        football_result = classify_football_content(
            Path(video_path),
            strict=strict_football_filter,
        )
        football_metadata = {
            "content_filter": "football",
            "football_action": football_result.action,
            "football_label": football_result.content_type,
            "football_reason": football_result.reason,
            "football_score": football_result.football_confidence,
            "football_interview_penalty": football_result.interview_penalty,
            "football_studio_penalty": football_result.studio_penalty,
            "football_static_penalty": football_result.static_penalty,
        }
        print(
            "[vod-clips][football] "
            f"type={football_result.content_type} action={football_result.action} "
            f"reason={football_result.reason}"
        )
        if football_result.action == "reject":
            print("[vod-clips] Arquivo rejeitado pelo filtro football. Nenhum timestamp salvo.")
            return 0

    candidates = detectar_melhores_momentos(
        video_path=video_path,
        max_cortes=max_cortes,
        sample_every_seconds=sample_every_seconds,
        analysis_window_seconds=analysis_window_seconds,
        min_gap_seconds=min_gap_seconds,
        min_score=score_threshold,
    )
    saved = 0
    for index, candidate in enumerate(candidates, start=1):
        record = salvar_momento(
            source_url=source,
            timestamp_seconds=candidate.timestamp_seconds,
            score=candidate.score,
            reason=candidate.reason,
            session_id=session_id,
            block_index=index - 1,
            block_file=str(video_path),
            metadata={
                "mode": "vod_clips_local",
                "block_timestamp_seconds": candidate.timestamp_seconds,
                "audio_score": candidate.audio_score,
                "motion_score": candidate.motion_score,
                "brightness_score": candidate.brightness_score,
                "min_gap_seconds": min_gap_seconds,
                "strict_football_filter": strict_football_filter,
                **football_metadata,
            },
        )
        saved += 1
        print(f"[vod-clips] salvo {record.id}: {candidate.timestamp_seconds}s score={candidate.score}")
    return saved


def _processar_vod_clips(args: argparse.Namespace) -> None:
    if not args.session_id:
        raise SystemExit("--session-id e obrigatorio no modo vod-clips.")

    if _is_url(args.source):
        print("[vod-clips] Etapa 1/2: scan-vod para salvar timestamps.")
        selected = scan_vod_completo(
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
        saved_count = len(selected)
    else:
        print("[vod-clips] Etapa 1/2: analise de arquivo local para salvar timestamps.")
        saved_count = _salvar_timestamps_arquivo_local(
            source=args.source,
            session_id=args.session_id,
            max_cortes=args.max_cortes,
            sample_every_seconds=args.sample_every_seconds,
            analysis_window_seconds=args.analysis_window_seconds,
            min_gap_seconds=args.min_gap_seconds,
            score_threshold=args.score_threshold,
            content_filter=args.content_filter,
            strict_football_filter=args.strict_football_filter,
        )
    if saved_count <= 0:
        print("[vod-clips] Nenhum timestamp salvo. Render final ignorado.")
        return

    print("[vod-clips] Etapa 2/2: render final HD a partir dos timestamps salvos.")
    processar_pos_live(
        source=args.source,
        max_cortes=args.max_cortes,
        usar_momentos_salvos=True,
        session_id=args.session_id,
        vod_offset_seconds=args.vod_offset_seconds,
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
        smart_event_window=args.smart_event_window,
        no_multi_event_clips=args.no_multi_event_clips,
        max_clip_duration=args.max_clip_duration,
        min_event_separation=args.min_event_separation,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Robo autonomo de cortes dark para lives e VODs.")
    parser.add_argument("source", help="URL da live/video ou caminho de um arquivo local.")
    parser.add_argument(
        "--modo",
        choices=["atual", "live", "near-live", "live-clips", "pos-live", "final-hd", "scan-vod", "vod-clips"],
        default="atual",
    )
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
    parser.add_argument(
        "--output-root",
        default=None,
        help="Pasta base para cache, cortes, fila_local.jsonl e run_logs. Padrao: D:/robo-cortes-dark.",
    )
    parser.add_argument(
        "--output-tag",
        default=None,
        help="Sufixo opcional nas subpastas de cortes (ex.: smart -> live_preview_smart, ready_hd_smart), "
        "para testar lado a lado sem sobrescrever cortes existentes.",
    )
    parser.add_argument(
        "--smart-event-window",
        action="store_true",
        help="Ativa janela de corte adaptativa por event_type (pre/post-roll ajustados) e impede "
        "que dois lances fortes caiam no mesmo corte (inclui --no-multi-event-clips).",
    )
    parser.add_argument(
        "--no-multi-event-clips",
        action="store_true",
        help="Encurta o corte se outro evento forte cair dentro da janela, para nunca juntar dois "
        "lances no mesmo mp4. Ativado automaticamente por --smart-event-window.",
    )
    parser.add_argument(
        "--max-clip-duration",
        type=int,
        default=50,
        help="Duracao maxima do corte com janela inteligente, em segundos. Padrao: 50 (futebol).",
    )
    parser.add_argument(
        "--min-event-separation",
        type=int,
        default=8,
        help="Distancia minima (segundos) entre o fim/inicio de um corte e o pico do evento vizinho, "
        "usada pela janela inteligente para nunca juntar dois lances.",
    )
    args = parser.parse_args()

    set_output_root(args.output_root)
    set_output_tag(args.output_tag)
    preparar_pastas()
    print(f"[paths] output_root={get_output_root()}")
    print(f"[paths] fila_local={queue_file()}")
    print(f"[paths] run_logs={run_logs_dir()}")

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

    if args.modo in {"near-live", "live-clips"}:
        monitorar_near_live(
            source_url=args.source,
            block_seconds=args.block_seconds,
            max_cortes=args.max_cortes,
            session_id=args.session_id,
            score_threshold=args.score_threshold,
            sample_every_seconds=args.sample_every_seconds,
            analysis_window_seconds=args.analysis_window_seconds,
            max_blocks=args.max_blocks,
            pre_roll_seconds=args.pre_roll_seconds,
            post_roll_seconds=args.post_roll_seconds,
            output_layout=args.output_layout,
            content_filter=args.content_filter,
            strict_football_filter=args.strict_football_filter,
            smart_event_window=args.smart_event_window,
            no_multi_event_clips=args.no_multi_event_clips,
            max_clip_duration=args.max_clip_duration,
            min_event_separation=args.min_event_separation,
        )
        return

    if args.modo == "vod-clips":
        _processar_vod_clips(args)
        print("[sistema] Finalizado.")
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

    # "atual", "pos-live" e "final-hd" compartilham o mesmo pipeline estavel.
    # Sem --modo, o comportamento continua sendo preparar fonte, analisar e gerar cortes.
    if args.modo == "final-hd" and not args.session_id:
        raise SystemExit("--session-id e obrigatorio no modo final-hd.")
    usar_momentos_salvos = args.usar_momentos_salvos if args.modo in {"pos-live", "final-hd"} else False
    if args.modo == "final-hd":
        usar_momentos_salvos = True
    processar_pos_live(
        source=args.source,
        max_cortes=args.max_cortes,
        usar_momentos_salvos=usar_momentos_salvos,
        session_id=args.session_id if args.modo in {"pos-live", "final-hd"} else None,
        vod_offset_seconds=args.vod_offset_seconds if args.modo in {"pos-live", "final-hd"} else 0,
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
        smart_event_window=args.smart_event_window,
        no_multi_event_clips=args.no_multi_event_clips,
        max_clip_duration=args.max_clip_duration,
        min_event_separation=args.min_event_separation,
    )
    print("[sistema] Finalizado.")


if __name__ == "__main__":
    main()
