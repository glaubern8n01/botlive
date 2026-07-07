from __future__ import annotations

import argparse
import copy
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import imageio_ffmpeg

# Consoles Windows (cp1252) nao encodam emoji; titulos de live com emoji
# derrubavam o scan inteiro num print. Nunca deixar print matar o pipeline.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

from clipper import preparar_pastas
from football_content_filter import classify_football_content
from gta_content_filter import classify_gta_content
from highlight_detector import detectar_melhores_momentos
from live_watcher import monitorar_live, monitorar_near_live
from moment_logger import salvar_momento
from overlay_editor import OverlayConfig
from post_live_processor import processar_pos_live
from runtime_paths import get_output_root, queue_file, run_logs_dir, set_output_root, set_output_tag, temp_dir
from source_downloader import resolver_fonte_video
from vod_scanner import scan_vod_completo


def _is_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "rtmp://", "m3u8://"))


def _publish_config_from_args(args: argparse.Namespace):
    """Monta a config da publicacao vertical. Sem --publish-vertical -> None,
    e o pipeline roda exatamente como hoje (o publisher nem e importado)."""
    if not args.publish_vertical:
        if args.post_youtube:
            raise SystemExit("--post-youtube requer --publish-vertical (o post usa o publish.json gerado por ele).")
        return None
    from publisher import PublishConfig

    social = None
    if args.post_youtube:
        from social_publisher import SocialConfig

        social = SocialConfig(
            redes=("youtube",),
            dry_run=args.post_dry_run,
            visibilidade=args.post_visibilidade,
            conta=args.post_conta,
        )

    return PublishConfig(
        enabled=True,
        nicho=args.content_filter if args.content_filter != "none" else None,
        credito_streamer=args.credito_streamer,
        credito_canal=args.credito_canal,
        social=social,
    )


def _overlay_from_args(args: argparse.Namespace) -> OverlayConfig:
    return OverlayConfig(
        title=args.titulo,
        description=args.descricao,
        brand=args.marca,
        cta=args.cta,
    )


def _extrair_trecho_para_classificacao(
    video_path: Path,
    center_seconds: int,
    window_seconds: int = 45,
) -> Optional[Path]:
    """Extrai um trecho curto e leve (sem audio, 320px) so para o filtro football.

    O filtro amostra ~10 frames do arquivo recebido; classificar o arquivo
    inteiro de um VOD longo nao diz nada sobre o lance. Aqui cada candidato
    ganha seu proprio trecho de ~45s ao redor do pico, como no scan-vod.
    """
    start = max(0, int(center_seconds) - window_seconds // 2)
    temp_dir().mkdir(parents=True, exist_ok=True)
    segment_path = temp_dir() / f"football_probe_{uuid4().hex[:8]}.mp4"
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start),
        "-i",
        str(video_path),
        "-t",
        str(window_seconds),
        "-an",
        "-vf",
        "scale=320:-2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        str(segment_path),
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    except Exception:
        segment_path.unlink(missing_ok=True)
        return None
    if result.returncode != 0 or not segment_path.exists() or segment_path.stat().st_size == 0:
        segment_path.unlink(missing_ok=True)
        return None
    return segment_path


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
        football_metadata: dict = {
            "content_filter": content_filter,
            "football_action": "save_ready",
            "football_label": "nao_avaliado",
        }
        if content_filter == "football":
            segment_path = _extrair_trecho_para_classificacao(
                Path(video_path),
                candidate.timestamp_seconds,
            )
            if segment_path is None:
                print(
                    "[vod-clips][football] falha ao extrair trecho para classificar "
                    f"t={candidate.timestamp_seconds}s; candidato ignorado."
                )
                continue
            try:
                football_result = classify_football_content(
                    segment_path,
                    strict=strict_football_filter,
                    score_base=candidate.score,
                    audio_score=candidate.audio_score,
                    candidate_motion_score=candidate.motion_score,
                    visual_change_score=candidate.brightness_score,
                )
            finally:
                segment_path.unlink(missing_ok=True)
            print(
                "[vod-clips][football] "
                f"t={candidate.timestamp_seconds}s type={football_result.content_type} "
                f"action={football_result.action} reason={football_result.reason}"
            )
            if football_result.action == "reject":
                print(f"[vod-clips] candidato rejeitado pelo filtro football: {candidate.timestamp_seconds}s")
                continue
            football_metadata = {
                "content_filter": "football",
                "event_type": football_result.content_type,
                "football_action": football_result.action,
                "football_label": football_result.content_type,
                "football_reason": football_result.reason,
                "football_score": football_result.football_confidence,
                "football_interview_penalty": football_result.interview_penalty,
                "football_studio_penalty": football_result.studio_penalty,
                "football_static_penalty": football_result.static_penalty,
            }
        elif content_filter == "gta":
            segment_path = _extrair_trecho_para_classificacao(
                Path(video_path),
                candidate.timestamp_seconds,
            )
            if segment_path is None:
                print(
                    "[vod-clips][gta] falha ao extrair trecho para classificar "
                    f"t={candidate.timestamp_seconds}s; candidato ignorado."
                )
                continue
            try:
                segment_start = max(0, int(candidate.timestamp_seconds) - 45 // 2)
                gta_result = classify_gta_content(
                    segment_path,
                    candidate_block_seconds=candidate.timestamp_seconds - segment_start,
                    score_base=candidate.score,
                )
            finally:
                segment_path.unlink(missing_ok=True)
            print(
                "[vod-clips][gta] "
                f"t={candidate.timestamp_seconds}s type={gta_result.content_type} "
                f"action={gta_result.action} reason={gta_result.reason}"
            )
            if gta_result.action == "reject":
                print(f"[vod-clips] candidato rejeitado pelo filtro gta: {candidate.timestamp_seconds}s")
                continue
            football_metadata = {
                "content_filter": "gta",
                "event_type": gta_result.content_type,
                "football_action": gta_result.action,
                "football_label": gta_result.content_type,
                "football_reason": gta_result.reason,
                "gta_motion_median": gta_result.game_motion_median,
                "gta_static_ui_ratio": gta_result.static_ui_ratio,
                "gta_audio_rms_mean": gta_result.audio_rms_mean,
                "gta_audio_transient": gta_result.audio_transient_ratio,
            }
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
    if saved == 0:
        print("[vod-clips] Nenhum candidato aprovado para essa sessao.")
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
        publish_config=_publish_config_from_args(args),
    )


def _ler_lista_links(caminho: str) -> list[str]:
    """Le o arquivo de lote: um link por linha; linhas vazias e comentarios (#) sao ignorados."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        raise SystemExit(f"--lista-links: arquivo nao encontrado: {caminho}")
    links: list[str] = []
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        links.append(linha)
    if not links:
        raise SystemExit(f"--lista-links: nenhum link valido em {caminho}")
    return links


def _processar_lote(args: argparse.Namespace) -> None:
    """Roda o pipeline completo para cada link da lista, em sequencia.

    Falha em um link nao derruba o lote: registra o motivo e segue pro proximo.
    Cada link ganha um session-id proprio (sufixo -NN) para os timestamps salvos
    de um link nunca vazarem no render do outro.
    """
    links = _ler_lista_links(args.lista_links)
    base_session = args.session_id or datetime.now().strftime("lote-%Y%m%d-%H%M%S")
    total = len(links)
    resultados: list[tuple[str, str, str, float]] = []

    for indice, link in enumerate(links, start=1):
        print("\n" + "=" * 72)
        print(f"[lote] Link {indice}/{total}: {link}")
        print("=" * 72)
        link_args = copy.copy(args)
        link_args.source = link
        link_args.session_id = f"{base_session}-{indice:02d}"
        print(f"[lote] session-id deste link: {link_args.session_id}")
        inicio = time.monotonic()
        try:
            _executar_pipeline(link_args)
        except KeyboardInterrupt:
            raise
        except SystemExit as exc:
            motivo = str(exc.code) if exc.code is not None else "SystemExit"
            resultados.append((link, "falha", motivo, time.monotonic() - inicio))
            print(f"[lote] Link {indice}/{total} FALHOU: {motivo}")
        except Exception as exc:
            motivo = f"{type(exc).__name__}: {exc}"
            resultados.append((link, "falha", motivo, time.monotonic() - inicio))
            print(f"[lote] Link {indice}/{total} FALHOU: {motivo}")
        else:
            resultados.append((link, "ok", "", time.monotonic() - inicio))
            print(f"[lote] Link {indice}/{total} concluido.")

    sucesso = sum(1 for _, status, _, _ in resultados if status == "ok")
    falhas = total - sucesso
    print("\n" + "=" * 72)
    print(f"[lote] RESUMO: {total} link(s) processado(s) | {sucesso} ok | {falhas} falha(s)")
    print("=" * 72)
    for indice, (link, status, motivo, duracao) in enumerate(resultados, start=1):
        marcador = "OK   " if status == "ok" else "FALHA"
        linha = f"[lote]   {indice:02d}. {marcador} {duracao:6.1f}s  {link}"
        if motivo:
            linha += f"  -> {motivo}"
        print(linha)


def main() -> None:
    parser = argparse.ArgumentParser(description="Robo autonomo de cortes dark para lives e VODs.")
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="URL da live/video ou caminho de um arquivo local. Opcional apenas com --lista-links.",
    )
    parser.add_argument(
        "--lista-links",
        default=None,
        help="Arquivo texto com um link por linha (aceita comentarios com #). Processa cada link "
        "em sequencia com o pipeline completo; falha em um link nao interrompe os demais. "
        "Com --session-id, cada link recebe o sufixo -01, -02...",
    )
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
        choices=["none", "football", "gta"],
        default="none",
        help="Filtro de conteudo por nicho. football prioriza lance de jogo; "
        "gta separa acao (ready) / conversa animada (needs_review) / morto (reject).",
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
    parser.add_argument(
        "--publish-vertical",
        action="store_true",
        help="OPT-IN: apos cada corte concluido, gera versao vertical 9:16 legendada + publish.json. "
        "Sem essa flag, o pipeline roda exatamente como hoje.",
    )
    parser.add_argument(
        "--post-youtube",
        action="store_true",
        help="OPT-IN: apos o publish.json de cada corte, posta horizontal + vertical no YouTube "
        "(YouTube Data API v3, gratuita). Requer --publish-vertical.",
    )
    parser.add_argument(
        "--post-dry-run",
        action="store_true",
        help="Simula o auto-post: grava o bloco 'postagens' no publish.json sem subir nada.",
    )
    parser.add_argument(
        "--post-visibilidade",
        choices=["private", "unlisted", "public"],
        default="unlisted",
        help="Visibilidade do video postado. Padrao: unlisted (nao listado), seguro para teste.",
    )
    parser.add_argument(
        "--post-conta",
        default="principal",
        help="Nome da conta autorizada no YouTube (token em .tokens/youtube/<conta>.json).",
    )
    parser.add_argument(
        "--credito-streamer",
        default=None,
        help="@ do streamer na tarja de baixo do vertical (ex: @paulinho).",
    )
    parser.add_argument(
        "--credito-canal",
        default=None,
        help="Canal proprio na tarja de baixo. Sem esse valor, usa o default do nicho (--content-filter).",
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
    parser.add_argument(
        "--live-retention-seconds",
        type=int,
        default=900,
        help="Idade maxima (segundos) de um bloco de live no disco antes de ser apagado no modo "
        "near-live continuo. Piso automatico: maior janela de clipe + 2 blocos. Padrao: 900 (15 min).",
    )
    parser.add_argument(
        "--no-peak-refine",
        action="store_true",
        help="Desliga o refino fino do pico pela explosao de audio no modo near-live.",
    )
    args = parser.parse_args()

    if args.lista_links and args.source:
        parser.error("use o source posicional OU --lista-links, nao os dois ao mesmo tempo.")
    if not args.lista_links and not args.source:
        parser.error("informe a URL/arquivo (source) ou --lista-links arquivo.txt.")

    set_output_root(args.output_root)
    set_output_tag(args.output_tag)
    preparar_pastas()
    print(f"[paths] output_root={get_output_root()}")
    print(f"[paths] fila_local={queue_file()}")
    print(f"[paths] run_logs={run_logs_dir()}")

    if args.lista_links:
        _processar_lote(args)
        return

    _executar_pipeline(args)


def _executar_pipeline(args: argparse.Namespace) -> None:
    """Pipeline completo para UM link, identico ao fluxo de sempre.

    O modo lote (--lista-links) chama esta funcao uma vez por link; o modo de
    link unico chega aqui direto do main sem nenhuma mudanca de comportamento.
    """
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
            retention_seconds=args.live_retention_seconds,
            refine_peak=not args.no_peak_refine,
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
        publish_config=_publish_config_from_args(args),
    )
    print("[sistema] Finalizado.")


if __name__ == "__main__":
    main()
