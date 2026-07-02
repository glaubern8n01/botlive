"""Teste leve do filtro de futebol, sem baixar video nem abrir arquivo.

Usa classify_football_metrics diretamente com metricas simuladas para cada
categoria (active_play, pregame, studio, VAR/grafico, torcida/estadio) e
confirma que o modo --strict-football-filter nunca deixa passar cortes que
nao sejam lance ativo para "ready".

Rodar com: python test_football_content_filter.py
"""

from __future__ import annotations

from football_content_filter import classify_football_metrics

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str) -> None:
    status = "OK" if condition else "FALHOU"
    print(f"[{status}] {label}: {detail}")
    if not condition:
        FAILURES.append(f"{label}: {detail}")


def main() -> None:
    active_play = classify_football_metrics(
        green_ratio=0.22,
        skin_ratio=0.02,
        white_ratio=0.03,
        brightness=0.4,
        contrast=0.09,
        distributed_motion=0.25,
        scoreboard=True,
        strict=True,
        score_base=0.8,
        audio_score=0.75,
        candidate_motion_score=0.7,
        visual_change_score=0.5,
    )
    check(
        "lance ativo forte (strict) vira save_ready",
        active_play.category == "active_play" and active_play.action == "save_ready",
        f"category={active_play.category} action={active_play.action} active_play_score={active_play.active_play_score}",
    )

    pregame_static = classify_football_metrics(
        green_ratio=0.42,
        skin_ratio=0.01,
        white_ratio=0.02,
        brightness=0.5,
        contrast=0.09,
        distributed_motion=0.045,
        scoreboard=False,
        strict=True,
        score_base=0.5,
        audio_score=0.2,
        candidate_motion_score=0.1,
        visual_change_score=0.25,
    )
    check(
        "estadio/pre-jogo parado (strict) nunca vira save_ready",
        pregame_static.action != "save_ready",
        f"category={pregame_static.category} action={pregame_static.action} pregame_score={pregame_static.pregame_score}",
    )

    pregame_pan = classify_football_metrics(
        green_ratio=0.40,
        skin_ratio=0.01,
        white_ratio=0.02,
        brightness=0.5,
        contrast=0.05,
        distributed_motion=0.85,
        scoreboard=False,
        strict=True,
        score_base=0.6,
        audio_score=0.3,
        candidate_motion_score=0.2,
        visual_change_score=0.3,
    )
    check(
        "pan de camera pelo estadio inteiro (strict) nunca vira save_ready",
        pregame_pan.action != "save_ready",
        f"category={pregame_pan.category} action={pregame_pan.action} pregame_score={pregame_pan.pregame_score}",
    )

    studio = classify_football_metrics(
        green_ratio=0.02,
        skin_ratio=0.15,
        white_ratio=0.0,
        brightness=0.4,
        contrast=0.09,
        distributed_motion=0.05,
        scoreboard=False,
        strict=True,
        score_base=0.5,
        audio_score=0.4,
        candidate_motion_score=0.1,
        visual_change_score=0.1,
    )
    check(
        "estudio/entrevista/painel (strict) vira reject",
        studio.category == "studio_or_commentary" and studio.action == "reject",
        f"category={studio.category} action={studio.action} studio_score={studio.studio_score}",
    )

    var_graphics = classify_football_metrics(
        green_ratio=0.01,
        skin_ratio=0.01,
        white_ratio=0.05,
        brightness=0.5,
        contrast=0.15,
        distributed_motion=0.05,
        scoreboard=True,
        strict=True,
        score_base=0.5,
        audio_score=0.3,
        candidate_motion_score=0.05,
        visual_change_score=0.25,
    )
    check(
        "tela de VAR/grafico/patrocinador (strict) nunca vira save_ready",
        var_graphics.action != "save_ready",
        f"category={var_graphics.category} action={var_graphics.action} var_graphics_score={var_graphics.var_graphics_score}",
    )

    crowd_only = classify_football_metrics(
        green_ratio=0.03,
        skin_ratio=0.02,
        white_ratio=0.0,
        brightness=0.5,
        contrast=0.08,
        distributed_motion=0.5,
        scoreboard=False,
        strict=True,
        score_base=0.5,
        audio_score=0.8,
        candidate_motion_score=0.6,
        visual_change_score=0.5,
    )
    check(
        "torcida/estadio sem jogada (strict) vira reject",
        crowd_only.category == "crowd_or_stadium_only" and crowd_only.action == "reject",
        f"category={crowd_only.category} action={crowd_only.action} crowd_only_score={crowd_only.crowd_only_score}",
    )

    borderline_kwargs = dict(
        green_ratio=0.16,
        skin_ratio=0.05,
        white_ratio=0.015,
        brightness=0.4,
        contrast=0.07,
        distributed_motion=0.14,
        scoreboard=False,
        score_base=0.35,
        audio_score=0.35,
        candidate_motion_score=0.3,
        visual_change_score=0.2,
    )
    strict_borderline = classify_football_metrics(strict=True, **borderline_kwargs)
    loose_borderline = classify_football_metrics(strict=False, **borderline_kwargs)
    check(
        "strict e mais conservador que o modo normal no mesmo caso limitrofe",
        strict_borderline.action != "save_ready" and loose_borderline.action == "save_ready",
        f"strict={strict_borderline.action} normal={loose_borderline.action} active_play_score={strict_borderline.active_play_score}",
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} verificacao(oes) falharam:")
        for failure in FAILURES:
            print(f" - {failure}")
        raise SystemExit(1)
    print("Todas as verificacoes passaram.")


if __name__ == "__main__":
    main()
