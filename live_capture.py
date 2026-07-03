from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Optional

import imageio_ffmpeg

from live_buffer import _is_url, _resolve_stream_url, _tem_primeiro_frame
from runtime_paths import live_blocks_dir


# Tolerancia (segundos) entre o fim real de um bloco e o inicio do proximo
# antes de marcar descontinuidade. Cobre o jitter do relogio de parede e o
# corte em keyframe do segment muxer.
GAP_TOLERANCE_SECONDS = 1.5

# Um segmento util precisa de pelo menos isso de duracao real.
MIN_BLOCK_DURATION_SECONDS = 1.0

_OPENING_RE = re.compile(r"Opening '(?P<path>[^']+)' for writing")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SHOWINFO_PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class CapturedBlock:
    """Bloco de live capturado pelo produtor continuo.

    start_offset_seconds e a posicao REAL na live (relogio de parede desde o
    inicio da sessao), nao um multiplo nominal de block_seconds. Mantem os
    mesmos nomes de campos do LiveBlock legado para reutilizar os helpers de
    janela/concat do live_watcher.
    """

    path: Path
    block_index: int
    start_offset_seconds: float
    duration_seconds: float
    wall_start_utc: str
    discontinuity: bool


def medir_duracao_segundos(video_path: Path) -> Optional[float]:
    """Mede a duracao real de um arquivo pelo cabecalho que o ffmpeg reporta."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    match = _DURATION_RE.search(result.stderr or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _probe_seek_landing_seconds(video_path: Path, offset_seconds: float) -> Optional[float]:
    """Descobre em que instante REAL do arquivo um -ss com -c copy vai cair.

    Seek de entrada com copy so retoma em keyframe (rebobina ate varios
    segundos antes do offset pedido); sem essa sondagem a ancora da retomada
    ficaria adiantada em relacao ao conteudo. -copyts preserva o pts original
    do primeiro frame decodado, que e exatamente o ponto de retomada.
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-hide_banner",
        # -noaccurate_seek: sem ele o decode descartaria frames ate o alvo e
        # mediriamos o proprio offset; o -c copy da captura comeca no KEYFRAME.
        "-noaccurate_seek",
        "-ss",
        f"{offset_seconds:.2f}",
        "-copyts",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "showinfo",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    except Exception:
        return None
    match = _SHOWINFO_PTS_RE.search(result.stderr or "")
    if not match:
        return None
    return float(match.group(1))


def limpar_sessoes_antigas(max_age_hours: float = 48.0) -> int:
    """Remove sessoes orfas de live_blocks/ mais velhas que max_age_hours."""
    root = live_blocks_dir()
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for session_dir in root.iterdir():
        if not session_dir.is_dir():
            continue
        try:
            newest = max((item.stat().st_mtime for item in session_dir.iterdir()), default=session_dir.stat().st_mtime)
        except OSError:
            continue
        if newest < cutoff:
            shutil.rmtree(session_dir, ignore_errors=True)
            removed += 1
            print(f"[capture] sessao antiga removida: {session_dir.name}")
    return removed


class ContinuousCapture:
    """Produtor: UM ffmpeg persistente com -f segment gravando bloco atras de
    bloco sem fechar a entrada (zero buraco por construcao). Cada segmento
    fechado vira um CapturedBlock na fila, com tempo real por relogio de
    parede e duracao medida. Se o ffmpeg morrer, reconecta com backoff e
    marca a descontinuidade no proximo bloco.
    """

    def __init__(
        self,
        source_url: str,
        session_id: str,
        block_queue: "Queue[Optional[CapturedBlock]]",
        block_seconds: int = 45,
        max_blocks: Optional[int] = None,
        max_consecutive_failures: int = 5,
    ) -> None:
        self.source_url = source_url
        self.session_id = session_id
        self.block_queue = block_queue
        self.block_seconds = block_seconds
        self.max_blocks = max_blocks
        self.max_consecutive_failures = max_consecutive_failures

        self.session_dir = live_blocks_dir() / session_id
        self.manifest_path = self.session_dir / "manifest.jsonl"
        self.stop_event = threading.Event()

        self._thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._session_start_mono: Optional[float] = None
        self._emitted = 0
        self._next_segment_number = 0
        self._last_block_end: Optional[float] = None
        self._pending_run_anchor: Optional[float] = None

        local = Path(source_url)
        self._local_source: Optional[Path] = local if not _is_url(source_url) and local.is_file() else None

    # ------------------------------------------------------------------
    def start(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._session_start_mono = time.monotonic()
        self._manifest_append(
            {
                "event": "session_start",
                "session_id": self.session_id,
                "session_start_utc": datetime.now(timezone.utc).isoformat(),
                "block_seconds": self.block_seconds,
                "source": self.source_url,
            }
        )
        self._thread = threading.Thread(target=self._run, name=f"capture-{self.session_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    def _manifest_append(self, payload: dict) -> None:
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _elapsed(self) -> float:
        return time.monotonic() - (self._session_start_mono or time.monotonic())

    def _resolve_input(self) -> tuple[list[str], str]:
        """Retorna (argumentos de entrada do ffmpeg, descricao da fonte).

        Efeito colateral: define self._pending_run_anchor quando a posicao
        real de retomada e conhecida (arquivo local), para a corrida ancorar
        no CONTEUDO e nao no relogio (o -ss com copy rebobina ate keyframe).
        """
        self._pending_run_anchor = None
        if self._local_source is not None:
            # Arquivo local vira simulacao de live: -re le em velocidade real
            # e, apos reconexao, retoma na posicao "agora" (como uma live).
            args = ["-re"]
            offset = self._elapsed()
            if offset > 1.0:
                args += ["-ss", f"{offset:.2f}"]
                landing = _probe_seek_landing_seconds(self._local_source, offset)
                if landing is not None:
                    self._pending_run_anchor = landing
                    print(f"[capture] retomada: -ss {offset:.1f}s caiu no keyframe {landing:.2f}s")
            else:
                self._pending_run_anchor = 0.0
            args += ["-i", str(self._local_source)]
            return args, f"arquivo local (simulacao, offset={offset:.1f}s)"

        lowered = self.source_url.lower()
        if "youtube.com" in lowered or "youtu.be" in lowered or "twitch.tv" in lowered:
            stream_url = _resolve_stream_url(self.source_url)
            args = []
            if ".m3u8" in stream_url.lower():
                # Rejoina na borda da live (menor rebobinada possivel no HLS).
                args += ["-live_start_index", "-1"]
            args += ["-i", stream_url]
            return args, "URL resolvida via yt-dlp"
        return ["-i", self.source_url], "URL direta"

    def _launch_ffmpeg(self) -> subprocess.Popen:
        input_args, source_label = self._resolve_input()
        print(f"[capture] fonte: {source_label}")
        pattern = self.session_dir / "block_%06d.mp4"
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "info",
            "-nostats",
            *input_args,
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(self.block_seconds),
            "-reset_timestamps",
            "1",
            # MP4 fragmentado: legivel mesmo se o processo morrer no meio do
            # segmento (sem moov "orfao") e compativel com todo o pipeline,
            # que ja opera sobre mp4. TS quebrava a leitura do moviepy em
            # fontes 29.97fps (falha deterministica na 2a abertura).
            "-segment_format",
            "mp4",
            "-segment_format_options",
            "movflags=+frag_keyframe+empty_moov+default_base_moof",
            "-segment_start_number",
            str(self._next_segment_number),
            str(pattern),
        ]
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _emit_block(
        self,
        path: Path,
        start_seconds: float,
        wall_open_seconds: float,
        wall_open_utc: str,
    ) -> Optional[float]:
        """Fecha a contabilidade de um segmento terminado e o coloca na fila.

        start_seconds vem do cursor de midia da corrida (ancora de parede do
        primeiro segmento + duracoes medidas acumuladas): dentro de uma corrida
        do ffmpeg os segmentos sao contiguos POR CONSTRUCAO, entao o cursor e
        exato. O relogio de parede bruto de cada abertura fica no manifesto so
        para diagnostico (com -re/HLS o mux le adiantado e ele nao e confiavel
        como posicao).

        Retorna a duracao medida (para avancar o cursor) ou None se descartado.
        """
        duration = medir_duracao_segundos(path)
        if duration is None or duration < MIN_BLOCK_DURATION_SECONDS:
            print(f"[capture] segmento invalido/curto descartado: {path.name}")
            path.unlink(missing_ok=True)
            return None
        # O consumidor abre o bloco logo em seguida (moviepy); garante que o
        # primeiro frame ja e legivel antes de enfileirar. Uma unica
        # re-tentativa cobre corrida de flush/lock de escrita no Windows.
        for attempt in range(2):
            if _tem_primeiro_frame(path):
                break
            if attempt == 0:
                print(f"[capture] {path.name} ainda nao legivel; re-tentando em 1s...")
                time.sleep(1.0)
        else:
            print(f"[capture] segmento sem frame legivel descartado: {path.name}")
            path.unlink(missing_ok=True)
            return None

        index = int(path.stem.split("_")[-1])
        discontinuity = False
        if self._last_block_end is not None:
            gap = start_seconds - self._last_block_end
            # Positivo = buraco (conteudo perdido); negativo = sobreposicao
            # (retomada rebobinou). Os dois quebram a continuidade do concat.
            if abs(gap) > GAP_TOLERANCE_SECONDS:
                discontinuity = True
                kind = "buraco" if gap > 0 else "sobreposicao"
                print(f"[capture] descontinuidade ({kind} de {abs(gap):.1f}s) antes do bloco {index}")
        self._last_block_end = start_seconds + duration

        block = CapturedBlock(
            path=path,
            block_index=index,
            start_offset_seconds=round(start_seconds, 3),
            duration_seconds=round(duration, 3),
            wall_start_utc=wall_open_utc,
            discontinuity=discontinuity,
        )
        self._manifest_append(
            {
                "event": "block",
                "block_index": block.block_index,
                "path": str(block.path),
                "live_start_seconds": block.start_offset_seconds,
                "duration_seconds": block.duration_seconds,
                "wall_open_seconds": round(wall_open_seconds, 3),
                "wall_start_utc": block.wall_start_utc,
                "discontinuity": block.discontinuity,
            }
        )
        self.block_queue.put(block)
        self._emitted += 1
        print(
            f"[capture] bloco {block.block_index} pronto: t_live={block.start_offset_seconds:.1f}s "
            f"dur={block.duration_seconds:.1f}s{' [descontinuidade]' if discontinuity else ''}"
        )
        return duration

    def _run(self) -> None:
        failures = 0
        try:
            while not self.stop_event.is_set():
                if self.max_blocks is not None and self._emitted >= self.max_blocks:
                    break
                try:
                    process = self._launch_ffmpeg()
                except Exception as exc:
                    failures += 1
                    print(f"[capture] falha ao abrir fonte ({failures}/{self.max_consecutive_failures}): {exc}")
                    if failures >= self.max_consecutive_failures:
                        break
                    time.sleep(min(30, 2**failures))
                    continue

                self._process = process
                launched_at = time.monotonic()
                emitted_this_run = self._consume_segments(process)
                returncode = process.wait()
                self._process = None

                if self.stop_event.is_set():
                    break
                if self.max_blocks is not None and self._emitted >= self.max_blocks:
                    break
                if self._local_source is not None and returncode == 0:
                    # Fim do arquivo local: fim da simulacao.
                    break

                lasted = time.monotonic() - launched_at
                if emitted_this_run == 0 and lasted < self.block_seconds:
                    failures += 1
                    print(
                        f"[capture] ffmpeg caiu sem produzir bloco (code={returncode}, "
                        f"{lasted:.0f}s) — tentativa {failures}/{self.max_consecutive_failures}"
                    )
                    if failures >= self.max_consecutive_failures:
                        break
                    time.sleep(min(30, 2**failures))
                else:
                    failures = 0
                    print(f"[capture] ffmpeg encerrou (code={returncode}); reconectando...")
        finally:
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            self._manifest_append({"event": "session_end", "blocks_emitted": self._emitted})
            self.block_queue.put(None)
            print(f"[capture] produtor encerrado. blocos emitidos: {self._emitted}")

    def _consume_segments(self, process: subprocess.Popen) -> int:
        """Le o stderr do ffmpeg; cada 'Opening ... for writing' fecha o
        segmento anterior. Retorna quantos blocos foram emitidos nesta corrida.

        Posicao na live: o relogio de parede ancora so o PRIMEIRO segmento da
        corrida; dali em diante um cursor avanca pela duracao medida de cada
        segmento (dentro de uma corrida nao existe buraco por construcao).
        O wall bruto de cada abertura nao serve como posicao porque o mux le
        adiantado do throttle (-re/burst de HLS).
        """
        emitted = 0
        run_cursor: Optional[float] = None
        open_path: Optional[Path] = None
        open_wall: float = 0.0
        open_utc: str = ""

        assert process.stderr is not None
        for line in process.stderr:
            match = _OPENING_RE.search(line)
            if not match:
                continue
            now_wall = self._elapsed()
            now_utc = datetime.now(timezone.utc).isoformat()
            if run_cursor is None:
                # Ancora da corrida: posicao real conhecida (retomada de
                # arquivo local sondada no keyframe) ou relogio de parede.
                run_cursor = self._pending_run_anchor if self._pending_run_anchor is not None else now_wall
            if open_path is not None:
                duration = self._emit_block(open_path, run_cursor, open_wall, open_utc)
                if duration is not None:
                    emitted += 1
                    run_cursor += duration
            open_path = Path(match.group("path"))
            open_wall = now_wall
            open_utc = now_utc
            self._next_segment_number = int(open_path.stem.split("_")[-1]) + 1
            if self.stop_event.is_set() or (self.max_blocks is not None and self._emitted >= self.max_blocks):
                process.terminate()
                break

        process.wait()
        # O segmento que estava aberto quando o ffmpeg terminou tambem conta.
        if open_path is not None and open_path.exists() and run_cursor is not None:
            if self.max_blocks is None or self._emitted < self.max_blocks:
                if self._emit_block(open_path, run_cursor, open_wall, open_utc) is not None:
                    emitted += 1
            else:
                open_path.unlink(missing_ok=True)
        return emitted
