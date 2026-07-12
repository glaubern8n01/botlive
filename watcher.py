from __future__ import annotations

"""Vigia automatico de canais Twitch (PLANO-VIGIA.md).

Orquestrador: NAO processa video. Observa a Twitch (Helix), decide o que fazer
e dispara SUBPROCESSOS `python main.py` nos modos ja validados. Estado vive na
tabela vigia_streams (Supabase) — restart-safe e com lock por unique(stream_id).

Escopo implementado (V3 + V4 + V5):
- descoberta manual (vigia_channels) e aberta (categoria por viewers);
- deteccao de inicio/fim de live; agendamento e disparo do reprocesso de VOD;
- disparo de live-clips (Etapa C) em lives ativas, com ancora capture_start_utc
  gravada no ledger para o dedup do V6; o job live NAO posta nada (previews);
- TRAVA de posts: orcamento diario max_posts_per_day respeitado ANTES de todo job;
- varredura de orfaos no boot e encerramento de captura zumbi pos-fim (grace);
- --vigia-dry-run: decide e loga tudo, nao dispara nada.

Pendente (por decisao de plano): V6 (dedup live x VOD) — vigia_clip_index ainda
nao e escrito; a ancora do V5 ja deixa o caminho pronto.
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from database import _get_client
from runtime_paths import get_output_root, run_logs_dir
from twitch_api import TwitchAPIError, TwitchHelix

REPO_DIR = Path(__file__).resolve().parent
CONFIG_TABLE = "vigia_config"
CHANNELS_TABLE = "vigia_channels"
STREAMS_TABLE = "vigia_streams"
UPLOAD_MARKER = "publicado ("  # linha do yt_publisher: "... publicado (unlisted): url"
END_MISS_CYCLES = 3  # ciclos consecutivos ausente antes de declarar fim de live
END_GRACE_SECONDS = 240  # apos o fim declarado, prazo para a captura live morrer sozinha


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass(frozen=True)
class VigiaConfig:
    enabled: bool = False
    manual_channels_enabled: bool = True
    discovery_enabled: bool = False
    live_mode_enabled: bool = False
    vod_mode_enabled: bool = True
    discovery_game: str = "Grand Theft Auto V"
    discovery_language: str = "pt"
    discovery_min_viewers: int = 100
    discovery_max_channels: int = 3
    poll_interval_seconds: int = 60
    max_concurrent_captures: int = 2
    max_concurrent_renders: int = 1
    vod_delay_minutes: int = 15
    vod_max_attempts: int = 6
    dedup_window_seconds: int = 60
    max_cortes_live: int = 3
    max_cortes_vod: int = 3
    clip_duration_seconds: int = 45
    content_filter: str = "gta"
    target_height: int = 720
    post_youtube_enabled: bool = False
    post_visibilidade: str = "unlisted"
    max_posts_per_day: int = 4
    credito_streamer: Optional[str] = None
    credito_canal: Optional[str] = "@GTA6brasilcortesoficial"

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "VigiaConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in row.items() if k in known and v is not None})


def _config_cache_file() -> Path:
    return get_output_root() / "vigia_config_cache.json"


class Vigia:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.api = TwitchHelix()
        self._running_vod_jobs: dict[str, tuple[subprocess.Popen, Path, str]] = {}
        self._running_live_jobs: dict[str, tuple[subprocess.Popen, Path, str]] = {}
        self._terminated_by_grace: set[str] = set()
        self._last_config: Optional[VigiaConfig] = None
        self._miss_counts: dict[str, int] = {}
        self._orphan_sweep_done = False

    # ------------------------------------------------------------- supabase

    def _client(self):
        client = _get_client()
        if client is None:
            print("[vigia][erro] ROBO_SUPABASE_URL/KEY ausentes; sem ledger nao ha vigia.")
        return client

    def load_config(self) -> Optional[VigiaConfig]:
        """Config do Supabase com cache em disco (Supabase fora nao para o vigia)."""
        client = self._client()
        if client is not None:
            try:
                response = client.table(CONFIG_TABLE).select("*").eq("id", 1).execute()
                if response.data:
                    config = VigiaConfig.from_row(response.data[0])
                    try:
                        _config_cache_file().write_text(
                            json.dumps(response.data[0], default=str), encoding="utf-8"
                        )
                    except OSError:
                        pass
                    self._last_config = config
                    return config
                print("[vigia][erro] vigia_config sem linha id=1; rode supabase/vigia_schema.sql.")
            except Exception as exc:
                print(f"[vigia] Supabase indisponivel para config ({exc}); usando cache.")
        if self._last_config is not None:
            return self._last_config
        cache = _config_cache_file()
        if cache.exists():
            try:
                config = VigiaConfig.from_row(json.loads(cache.read_text(encoding="utf-8")))
                self._last_config = config
                print("[vigia] config carregada do cache local.")
                return config
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return None

    def _manual_channels(self) -> Optional[list[str]]:
        """Lista manual. None = falha de leitura (diferente de lista vazia!).

        A distincao importa: com falha, o ciclo NAO pode concluir que os canais
        sairam do ar — senao marcariamos lives como encerradas por engano.
        """
        client = self._client()
        if client is None:
            return None
        try:
            response = (
                client.table(CHANNELS_TABLE)
                .select("login, priority")
                .eq("enabled", True)
                .order("priority")
                .limit(100)
                .execute()
            )
            return [row["login"] for row in (response.data or [])]
        except Exception as exc:
            print(f"[vigia] falha ao ler vigia_channels ({exc}); deteccao de fim pausada neste ciclo.")
            return None

    def _ledger_get(self, stream_id: str) -> Optional[dict[str, Any]]:
        client = self._client()
        if client is None:
            return None
        response = client.table(STREAMS_TABLE).select("*").eq("stream_id", stream_id).execute()
        return response.data[0] if response.data else None

    def _ledger_update(self, stream_id: str, patch: dict[str, Any]) -> None:
        client = self._client()
        if client is None:
            return
        patch = {**patch, "updated_at": _iso(_utc_now())}
        client.table(STREAMS_TABLE).update(patch).eq("stream_id", stream_id).execute()

    def _uploads_used_today(self) -> Optional[int]:
        """Soma uploads_done de hoje (UTC). None = nao deu pra apurar (trava fecha)."""
        client = self._client()
        if client is None:
            return None
        midnight = _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            response = (
                client.table(STREAMS_TABLE)
                .select("uploads_done")
                .gte("updated_at", _iso(midnight))
                .execute()
            )
            return sum(int(row.get("uploads_done") or 0) for row in (response.data or []))
        except Exception as exc:
            print(f"[vigia] falha ao apurar uploads do dia ({exc}); trava de post FECHADA.")
            return None

    # ----------------------------------------------------------- trava post

    def _post_allowed(self, config: VigiaConfig, uploads_expected: int) -> bool:
        """REGRA DE OURO: nunca postar sem orcamento diario apurado e suficiente.

        Qualquer duvida (config invalida, ledger inacessivel) => NAO posta.
        O job roda mesmo assim SEM --post-youtube: os cortes ficam prontos no
        disco com publish.json, postaveis depois.
        """
        if not config.post_youtube_enabled:
            return False
        try:
            budget = int(config.max_posts_per_day)
        except (TypeError, ValueError):
            print("[vigia][trava] max_posts_per_day invalido; post DESLIGADO neste job.")
            return False
        if budget <= 0:
            print("[vigia][trava] max_posts_per_day=0; post DESLIGADO neste job.")
            return False
        used = self._uploads_used_today()
        if used is None:
            return False
        if used + uploads_expected > budget:
            print(
                f"[vigia][trava] orcamento diario de posts esgotaria: usados={used} "
                f"+ previstos={uploads_expected} > teto={budget}. Job roda SEM post."
            )
            return False
        print(f"[vigia][trava] post liberado: usados={used} previstos={uploads_expected} teto={budget}")
        return True

    # ------------------------------------------------------------- descoberta

    def _detectar_lives(self, config: VigiaConfig) -> tuple[dict[str, dict[str, Any]], bool]:
        """Retorna (stream_id -> payload do Get Streams, visao_completa).

        visao_completa=False quando alguma fonte de verdade falhou; nesse caso o
        ciclo pula a deteccao de lives encerradas (ausencia nao e evidencia).
        """
        live_now: dict[str, dict[str, Any]] = {}
        complete = True

        if config.manual_channels_enabled:
            logins = self._manual_channels()
            if logins is None:
                complete = False
            elif logins:
                for stream in self.api.get_streams_by_logins(logins[:100]):
                    stream["_origin"] = "manual"
                    live_now[str(stream["id"])] = stream

        if config.discovery_enabled:
            streams = self.api.get_streams_by_game(
                config.discovery_game, language=config.discovery_language or None, first=100
            )
            picked = 0
            for stream in streams:  # ja vem ordenado por viewers desc
                if picked >= config.discovery_max_channels:
                    break
                if int(stream.get("viewer_count", 0)) < config.discovery_min_viewers:
                    break
                stream_id = str(stream["id"])
                if stream_id in live_now:
                    continue  # canal manual tem prioridade na origem
                stream["_origin"] = "discovery"
                live_now[stream_id] = stream
                picked += 1

        return live_now, complete

    # ------------------------------------------------------------------ ciclo

    def _registrar_novas(self, config: VigiaConfig, live_now: dict[str, dict[str, Any]]) -> None:
        client = self._client()
        if client is None:
            return
        for stream_id, stream in live_now.items():
            existing = self._ledger_get(stream_id)
            if existing is not None:
                if existing.get("ended_at"):
                    # Live "voltou" (queda breve marcada como fim): reabre e
                    # cancela o fluxo de VOD prematuro.
                    reopen: dict[str, Any] = {"ended_at": None}
                    if existing.get("vod_job_status") in {"waiting_vod", "vod_unavailable"}:
                        reopen["vod_job_status"] = "pending"
                        reopen["vod_attempts"] = 0
                    self._ledger_update(stream_id, reopen)
                    print(f"[vigia] live REABERTA: {stream['user_login']} stream_id={stream_id}")
                if existing.get("dry_run") and not self.dry_run:
                    # Linha criada num teste dry vira real: reabre o fluxo de VOD.
                    self._ledger_update(
                        stream_id,
                        {"dry_run": False, "vod_job_status": "pending" if config.vod_mode_enabled else "disabled"},
                    )
                    print(f"[vigia] stream {stream_id} ({stream['user_login']}): linha dry adotada como real.")
                continue
            row = {
                "stream_id": stream_id,
                "channel_login": stream["user_login"],
                "channel_user_id": str(stream.get("user_id") or ""),
                "origin": stream.get("_origin", "manual"),
                "started_at": stream.get("started_at"),
                "detected_at": _iso(_utc_now()),
                "live_job_status": "disabled",  # o despacho (_processar_lives) decide no mesmo ciclo
                "vod_job_status": "pending" if config.vod_mode_enabled else "disabled",
                "dry_run": self.dry_run,
            }
            try:
                client.table(STREAMS_TABLE).insert(row).execute()
            except Exception as exc:
                # unique(stream_id): outra instancia chegou primeiro — ok.
                print(f"[vigia] insert de {stream_id} ignorado ({exc}).")
                continue
            print(
                f"[vigia] LIVE detectada: {stream['user_login']} ({stream.get('_origin')}) "
                f"viewers={stream.get('viewer_count')} stream_id={stream_id}"
            )

    def _marcar_encerradas(self, live_now: dict[str, dict[str, Any]]) -> None:
        """Fim de live com tolerancia de END_MISS_CYCLES ciclos consecutivos.

        A Twitch some com uma live por 1-2 ciclos em reconexoes, e o VOD
        (archive) EXISTE E CRESCE durante a propria live — encerrar cedo demais
        dispararia o reprocesso de um VOD pela metade.
        """
        client = self._client()
        if client is None:
            return
        try:
            response = (
                client.table(STREAMS_TABLE)
                .select("stream_id, channel_login, vod_job_status")
                .is_("ended_at", "null")
                .execute()
            )
        except Exception as exc:
            print(f"[vigia] falha ao listar streams abertos ({exc}).")
            return
        for row in response.data or []:
            stream_id = row["stream_id"]
            if stream_id in live_now:
                self._miss_counts.pop(stream_id, None)
                continue
            misses = self._miss_counts.get(stream_id, 0) + 1
            self._miss_counts[stream_id] = misses
            if misses < END_MISS_CYCLES:
                print(
                    f"[vigia] {row['channel_login']} sumiu da lista ({misses}/{END_MISS_CYCLES} ciclos); aguardando confirmacao."
                )
                continue
            self._miss_counts.pop(stream_id, None)
            patch: dict[str, Any] = {"ended_at": _iso(_utc_now())}
            if row.get("vod_job_status") == "pending":
                patch["vod_job_status"] = "waiting_vod"
            self._ledger_update(stream_id, patch)
            print(f"[vigia] live encerrada: {row['channel_login']} stream_id={stream_id}")

    def _processar_vods(self, config: VigiaConfig) -> None:
        if not config.vod_mode_enabled:
            return
        client = self._client()
        if client is None:
            return
        try:
            response = (
                client.table(STREAMS_TABLE)
                .select("*")
                .eq("vod_job_status", "waiting_vod")
                .execute()
            )
        except Exception as exc:
            print(f"[vigia] falha ao listar VODs pendentes ({exc}).")
            return

        for row in response.data or []:
            if len(self._running_vod_jobs) >= config.max_concurrent_renders:
                print("[vigia] sem vaga de render neste ciclo; VODs restantes aguardam.")
                return
            if bool(row.get("dry_run")) != self.dry_run:
                continue  # linhas dry so andam em modo dry, e vice-versa
            ended_raw = row.get("ended_at")
            if not ended_raw:
                continue
            ended = datetime.fromisoformat(str(ended_raw).replace("Z", "+00:00"))
            if _utc_now() < ended + timedelta(minutes=config.vod_delay_minutes):
                continue
            attempts = int(row.get("vod_attempts") or 0)
            if attempts >= config.vod_max_attempts:
                self._ledger_update(row["stream_id"], {"vod_job_status": "vod_unavailable"})
                print(f"[vigia] VOD nao apareceu para stream {row['stream_id']}; desistindo.")
                continue

            vod_url = self._achar_vod(row)
            self._ledger_update(row["stream_id"], {"vod_attempts": attempts + 1})
            if vod_url is None:
                print(
                    f"[vigia] VOD de {row['channel_login']} (stream {row['stream_id']}) "
                    f"ainda nao disponivel (tentativa {attempts + 1}/{config.vod_max_attempts})."
                )
                continue
            self._disparar_vod_job(config, row, vod_url)

    def _achar_vod(self, row: dict[str, Any]) -> Optional[str]:
        user_id = row.get("channel_user_id") or self.api.get_user_id(row["channel_login"])
        if not user_id:
            return None
        for video in self.api.get_videos_archive(str(user_id), first=10):
            if str(video.get("stream_id") or "") == str(row["stream_id"]):
                return str(video["url"])
        return None

    # ------------------------------------------------------------- jobs LIVE

    def _processar_lives(self, config: VigiaConfig, live_now: dict[str, dict[str, Any]]) -> None:
        """Despacha live-clips (Etapa C) para lives ativas, com idempotencia.

        So despacha linhas em 'disabled'/'skipped_no_slot' — 'running/done/failed'
        nunca redespacham, entao nao ha como duplicar captura do mesmo stream.
        O job live NAO tem flag de post nenhuma: gera previews + momentos; quem
        posta continua sendo o fluxo VOD (trava de posts validada no V4).
        """
        if not config.live_mode_enabled:
            return
        for stream_id in live_now:
            row = self._ledger_get(stream_id)
            if row is None:
                continue
            if bool(row.get("dry_run")) != self.dry_run:
                continue
            if row.get("live_job_status") not in {"disabled", "skipped_no_slot"}:
                continue
            if len(self._running_live_jobs) >= config.max_concurrent_captures:
                if row.get("live_job_status") != "skipped_no_slot":
                    self._ledger_update(stream_id, {"live_job_status": "skipped_no_slot"})
                    print(f"[vigia] sem vaga de captura para {row['channel_login']}; tentando nos proximos ciclos.")
                continue
            self._disparar_live_job(config, row)

    def _disparar_live_job(self, config: VigiaConfig, row: dict[str, Any]) -> None:
        stream_id = str(row["stream_id"])
        session_id = f"vigia_{stream_id}_live"
        live_url = f"https://www.twitch.tv/{row['channel_login']}"
        command = [
            sys.executable,
            str(REPO_DIR / "main.py"),
            live_url,
            "--modo", "live-clips",
            "--session-id", session_id,
            "--content-filter", config.content_filter,
            "--max-cortes", str(config.max_cortes_live),
            "--output-layout", "original",
        ]

        if self.dry_run:
            print(f"[vigia][dry] dispararia LIVE job: {' '.join(command)}")
            self._ledger_update(
                stream_id,
                {"live_job_status": "done", "error_message": "dry_run: comando apenas logado"},
            )
            return

        # Ancora do dedup (V6): ts_vod ~= ts_live + (capture_start_utc - started_at).
        capture_start = _iso(_utc_now())
        run_logs_dir().mkdir(parents=True, exist_ok=True)
        log_path = run_logs_dir() / f"{session_id}.log"
        log_file = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            command, cwd=str(REPO_DIR), stdout=log_file, stderr=subprocess.STDOUT, text=True
        )
        log_file.close()
        self._running_live_jobs[stream_id] = (process, log_path, session_id)
        self._ledger_update(
            stream_id, {"live_job_status": "running", "capture_start_utc": capture_start}
        )
        print(
            f"[vigia] LIVE job iniciado: {row['channel_login']} pid={process.pid} "
            f"ancora={capture_start} log={log_path}"
        )

    def _encerrar_capturas_apos_fim(self) -> None:
        """Cinto de seguranca: live declarada encerrada mas captura ainda viva.

        O near-live termina sozinho quando o produtor seca; se nao terminar em
        END_GRACE_SECONDS apos o fim declarado, o vigia encerra o processo para
        nunca deixar captura zumbi re-tentando para sempre.
        """
        if not self._running_live_jobs:
            return
        client = self._client()
        if client is None:
            return
        for stream_id, (process, _log, _session) in list(self._running_live_jobs.items()):
            if process.poll() is not None:
                continue  # ja terminou; a colheita registra
            row = self._ledger_get(stream_id)
            ended_raw = (row or {}).get("ended_at")
            if not ended_raw:
                continue
            ended = datetime.fromisoformat(str(ended_raw).replace("Z", "+00:00"))
            if (_utc_now() - ended).total_seconds() < END_GRACE_SECONDS:
                continue
            print(f"[vigia] captura de {stream_id} viva {END_GRACE_SECONDS}s apos o fim; encerrando (terminate).")
            self._terminated_by_grace.add(stream_id)
            process.terminate()

    def _varrer_orfaos(self) -> None:
        """No boot: linhas 'running' sem processo em memoria sao de um vigia morto.

        Dentro do container, restart mata os subprocessos junto; marcar failed e
        deixar o fluxo VOD-depois cobrir o buraco e o caminho seguro.
        """
        client = self._client()
        if client is None:
            return
        try:
            for field in ("live_job_status", "vod_job_status"):
                rows = client.table(STREAMS_TABLE).select("stream_id").eq(field, "running").execute().data or []
                for row in rows:
                    self._ledger_update(
                        row["stream_id"],
                        {field: "failed", "error_message": "orphaned_restart: vigia reiniciou com job em andamento"},
                    )
                    print(f"[vigia] orfao de restart: {row['stream_id']} {field} running -> failed")
            self._orphan_sweep_done = True
        except Exception as exc:
            print(f"[vigia] varredura de orfaos falhou ({exc}); tentando no proximo ciclo.")

    # -------------------------------------------------------------- jobs VOD

    def _disparar_vod_job(self, config: VigiaConfig, row: dict[str, Any], vod_url: str) -> None:
        stream_id = str(row["stream_id"])
        session_id = f"vigia_{stream_id}_vod"
        uploads_expected = int(config.max_cortes_vod) * 2  # HD + vertical por corte
        post = self._post_allowed(config, uploads_expected)

        command = [
            sys.executable,
            str(REPO_DIR / "main.py"),
            vod_url,
            "--modo", "vod-clips",
            "--session-id", session_id,
            "--content-filter", config.content_filter,
            "--max-cortes", str(config.max_cortes_vod),
            "--clip-duration", str(config.clip_duration_seconds),
            "--target-height", str(config.target_height),
            "--output-layout", "original",
            "--publish-vertical",
        ]
        if post:
            command += [
                "--post-youtube",
                "--post-visibilidade", config.post_visibilidade,
                "--post-conta", "principal",
            ]
        credito = config.credito_streamer or f"@{row['channel_login']}"
        command += ["--credito-streamer", credito]
        if config.credito_canal:
            command += ["--credito-canal", config.credito_canal]

        if self.dry_run:
            print(f"[vigia][dry] dispararia VOD job: {' '.join(command)}")
            self._ledger_update(
                stream_id,
                {"vod_job_status": "done", "vod_url": vod_url, "error_message": "dry_run: comando apenas logado"},
            )
            return

        run_logs_dir().mkdir(parents=True, exist_ok=True)
        log_path = run_logs_dir() / f"{session_id}.log"
        log_file = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            command, cwd=str(REPO_DIR), stdout=log_file, stderr=subprocess.STDOUT, text=True
        )
        log_file.close()  # Popen herdou o handle; o nosso pode fechar
        self._running_vod_jobs[stream_id] = (process, log_path, session_id)
        self._ledger_update(stream_id, {"vod_job_status": "running", "vod_url": vod_url})
        print(f"[vigia] VOD job iniciado: {row['channel_login']} pid={process.pid} log={log_path}")

    def _colher_jobs(self) -> None:
        self._colher_de(self._running_vod_jobs, "vod_job_status", "VOD")
        self._colher_de(self._running_live_jobs, "live_job_status", "LIVE")

    def _colher_de(
        self,
        running: dict[str, tuple[subprocess.Popen, Path, str]],
        status_field: str,
        label: str,
    ) -> None:
        for stream_id in list(running):
            process, log_path, session_id = running[stream_id]
            if process.poll() is None:
                continue
            del running[stream_id]
            uploads = 0
            try:
                uploads = log_path.read_text(encoding="utf-8", errors="replace").count(UPLOAD_MARKER)
            except OSError:
                pass
            terminated_ok = stream_id in self._terminated_by_grace
            self._terminated_by_grace.discard(stream_id)
            if process.returncode == 0 or terminated_ok:
                patch: dict[str, Any] = {status_field: "done", "uploads_done": uploads}
                if terminated_ok:
                    patch["error_message"] = "encerrado pelo vigia apos fim da live (grace)"
                self._ledger_update(stream_id, patch)
                print(f"[vigia] {label} job concluido: stream {stream_id} uploads={uploads} (sessao {session_id})")
            else:
                self._ledger_update(
                    stream_id,
                    {
                        status_field: "failed",
                        "uploads_done": uploads,
                        "error_message": f"exit={process.returncode}; ver {log_path.name}",
                    },
                )
                print(f"[vigia] {label} job FALHOU (exit={process.returncode}): ver {log_path}")

    # ------------------------------------------------------------------- run

    def ciclo(self) -> int:
        """Um ciclo completo. Retorna o intervalo ate o proximo."""
        config = self.load_config()
        if config is None:
            print("[vigia] sem config (Supabase fora e sem cache). Tentando de novo em 60s.")
            return 60
        if not config.enabled:
            print("[vigia] enabled=false na vigia_config; dormindo.")
            return max(config.poll_interval_seconds, 30)

        if not self._orphan_sweep_done:
            self._varrer_orfaos()
        self._colher_jobs()
        try:
            live_now, visao_completa = self._detectar_lives(config)
        except TwitchAPIError as exc:
            print(f"[vigia] Helix indisponivel neste ciclo: {exc}")
            return max(config.poll_interval_seconds, 30)

        print(
            f"[vigia] ciclo: {len(live_now)} live(s) no alvo | "
            f"capturas: {len(self._running_live_jobs)} | renders: {len(self._running_vod_jobs)}"
        )
        self._registrar_novas(config, live_now)
        if visao_completa:
            self._marcar_encerradas(live_now)
        else:
            print("[vigia] visao incompleta das fontes; deteccao de fim adiada para o proximo ciclo.")
        self._processar_lives(config, live_now)
        self._encerrar_capturas_apos_fim()
        try:
            self._processar_vods(config)
        except TwitchAPIError as exc:
            print(f"[vigia] Helix falhou na busca de VOD: {exc}")
        return max(config.poll_interval_seconds, 30)


def run_vigia(dry_run: bool) -> None:
    modo = "DRY-RUN (nada e processado)" if dry_run else "REAL (dispara jobs live e de VOD)"
    print(f"[vigia] iniciando em modo {modo}. V6 (dedup) pendente por plano; job live nunca posta.")
    try:
        vigia = Vigia(dry_run=dry_run)
    except TwitchAPIError as exc:
        raise SystemExit(f"[vigia][erro] {exc}")
    while True:
        started = time.monotonic()
        try:
            interval = vigia.ciclo()
        except KeyboardInterrupt:
            print("[vigia] interrompido pelo usuario.")
            return
        except Exception as exc:  # ciclo nunca derruba o vigia
            print(f"[vigia][erro] ciclo falhou: {type(exc).__name__}: {exc}")
            interval = 60
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, interval - elapsed))
