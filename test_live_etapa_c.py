"""Testes unitarios da Etapa C (captura continua ao vivo).

Cobrem as pecas puras: refino de pico por audio (T6), divisao em sequencias
contiguas / escolha da sequencia do pico (base do concat consciente de
buraco) e limpeza de blocos por retencao. Rodar direto:

    python test_live_etapa_c.py
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg


def _check(label: str, condition: bool, details: str = "") -> None:
    status = "OK" if condition else "FALHOU"
    print(f"[{status}] {label}" + (f": {details}" if details else ""))
    if not condition:
        raise AssertionError(f"{label} | {details}")


# ---------------------------------------------------------------------------
# T6: refino de pico por audio
# ---------------------------------------------------------------------------

def _gerar_video_com_explosao(path: Path, duration: int = 40, burst_at: float = 23.0, burst_len: float = 0.4) -> None:
    """Video sintetico: tom baixo continuo + explosao de audio em burst_at."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    audio_expr = (
        f"0.02*sin(440*2*PI*t)"
        f"+if(between(t,{burst_at},{burst_at + burst_len}),0.8*sin(880*2*PI*t),0)"
    )
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=gray:s=320x240:r=10:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"aevalsrc='{audio_expr}':s=44100:d={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


def test_refino_pico() -> None:
    from highlight_detector import refinar_pico_por_audio

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "explosao.mp4"
        _gerar_video_com_explosao(video, duration=40, burst_at=23.0)

        refined = refinar_pico_por_audio(video, peak_seconds=15.0, search_radius_seconds=12.0)
        _check(
            "pico bruto 15s puxado para a explosao em 23s",
            abs(refined - 23.2) <= 0.6,
            f"refined={refined:.2f}s (esperado ~23.0-23.4s)",
        )

        refined_far = refinar_pico_por_audio(video, peak_seconds=38.0, search_radius_seconds=8.0)
        _check(
            "explosao fora do raio de busca NAO desloca o pico",
            abs(refined_far - 38.0) <= 0.01,
            f"refined={refined_far:.2f}s (esperado 38.0s)",
        )

    with tempfile.TemporaryDirectory() as tmp:
        flat = Path(tmp) / "morno.mp4"
        _gerar_video_com_explosao(flat, duration=30, burst_at=999.0)  # sem explosao dentro do arquivo
        refined_flat = refinar_pico_por_audio(flat, peak_seconds=12.0)
        _check(
            "audio sem transiente claro mantem o pico original",
            abs(refined_flat - 12.0) <= 0.01,
            f"refined={refined_flat:.2f}s (esperado 12.0s)",
        )


# ---------------------------------------------------------------------------
# Sequencias contiguas + escolha da sequencia do pico (concat com buraco)
# ---------------------------------------------------------------------------

@dataclass
class _FakeBlock:
    start_offset_seconds: float
    duration_seconds: float
    path: Path = field(default_factory=lambda: Path("fake.ts"))
    block_index: int = 0


def test_sequencias_contiguas() -> None:
    from live_watcher import _sequencia_com_pico, _sequencias_contiguas

    contiguos = [
        _FakeBlock(0.0, 45.0),
        _FakeBlock(45.0, 45.2),
        _FakeBlock(90.4, 44.8),
    ]
    runs = _sequencias_contiguas(contiguos)
    _check("blocos contiguos viram UMA sequencia", len(runs) == 1, f"runs={len(runs)}")

    com_buraco = [
        _FakeBlock(0.0, 45.0),
        _FakeBlock(45.0, 45.0),
        _FakeBlock(120.0, 45.0),  # buraco de 30s entre 90 e 120
        _FakeBlock(165.0, 45.0),
    ]
    runs = _sequencias_contiguas(com_buraco)
    _check("buraco de 30s divide em duas sequencias", len(runs) == 2, f"runs={len(runs)}")
    _check("primeira sequencia termina em 90s", len(runs[0]) == 2)
    _check("segunda sequencia comeca em 120s", runs[1][0].start_offset_seconds == 120.0)

    run = _sequencia_com_pico(com_buraco, peak_seconds=150.0)
    _check(
        "pico em 150s escolhe a sequencia depois do buraco",
        run is not None and run[0].start_offset_seconds == 120.0,
    )
    run_none = _sequencia_com_pico(com_buraco, peak_seconds=100.0)
    _check("pico dentro do buraco (100s) nao retorna sequencia", run_none is None)

    com_sobreposicao = [
        _FakeBlock(0.0, 45.0),
        _FakeBlock(45.0, 45.0),
        _FakeBlock(84.0, 45.0),  # retomada rebobinou 6s: sobrepoe 84-90
    ]
    runs = _sequencias_contiguas(com_sobreposicao)
    _check("sobreposicao de 6s tambem divide a sequencia", len(runs) == 2, f"runs={len(runs)}")


# ---------------------------------------------------------------------------
# Limpeza de blocos por retencao
# ---------------------------------------------------------------------------

def test_limpeza_retencao() -> None:
    from live_watcher import PendingPreview, _limpar_blocos_consumidos

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        blocks = []
        for index in range(6):
            path = tmp_path / f"block_{index:06d}.ts"
            path.write_bytes(b"x" * 1024)
            blocks.append(_FakeBlock(index * 45.0, 45.0, path=path, block_index=index))
        # now_live = 270s; retencao 100s => keep_after = 170s: blocos 0-2 velhos.
        pending = [
            PendingPreview(
                moment_id="m1",
                timestamp_seconds=80,
                event_start_seconds=68,
                event_end_seconds=113,
                block_timestamp_seconds=35,
                score=1.0,
                reason="teste",
                event_type="action",
                metadata={},
            )
        ]
        kept = _limpar_blocos_consumidos(blocks, pending, retention_seconds=100.0)
        kept_indices = sorted(item.block_index for item in kept)
        _check(
            "blocos velhos referenciados por pendente sobrevivem (1 e 2)",
            {1, 2}.issubset(set(kept_indices)),
            f"kept={kept_indices}",
        )
        _check(
            "bloco 0 (velho, sem referencia) apagado do disco",
            0 not in kept_indices and not (tmp_path / "block_000000.ts").exists(),
        )
        _check(
            "blocos recentes (3-5) intactos",
            {3, 4, 5}.issubset(set(kept_indices)) and all((tmp_path / f"block_{i:06d}.ts").exists() for i in (3, 4, 5)),
        )


if __name__ == "__main__":
    test_sequencias_contiguas()
    test_limpeza_retencao()
    test_refino_pico()
    print("\nTodas as verificacoes da Etapa C passaram.")
