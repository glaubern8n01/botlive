"""Fila do VexPublish: lock, execucao, retry com backoff e recuperacao.

Um PublishJob nunca pode rodar duas vezes. Duas defesas cobrem isso:
  - idempotency_key unica no banco, checada na criacao (core/models.py);
  - claim atomico com BEGIN IMMEDIATE que so muda o job se ele ainda estiver
    no estado esperado, marcando worker_id e locked_at.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import adapters
from ..accounts import registry
from ..core import models, obs, quotas, store
from ..core.errors import CodigoErro, VexPublishError
from ..core.flags import carregar
from ..scheduler import planner


ESTADOS_ELEGIVEIS = ("pending", "scheduled", "retry")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _backoff(tentativa: int) -> str:
    flags = carregar()
    espera = min(flags.backoff_base_seconds * (2 ** max(tentativa - 1, 0)), flags.backoff_max_seconds)
    return (_agora() + timedelta(seconds=espera)).isoformat()


def elegiveis(limite: int = 50) -> list:
    """Jobs prontos para rodar: fora de agendamento futuro e fora de backoff."""
    agora = _agora().isoformat()
    with store.conectar() as db:
        linhas = db.execute(
            "SELECT * FROM vexpublish_jobs "
            "WHERE status IN ('pending','scheduled','retry') "
            "AND (run_after IS NULL OR run_after<=?) "
            "AND (scheduled_at IS NULL OR scheduled_at<=?) "
            "ORDER BY COALESCE(scheduled_at, created_at) LIMIT ?",
            (agora, agora, limite),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def reivindicar(worker_id: str) -> dict | None:
    """Pega o proximo job respeitando quota global e limites da conta.

    A quota global vem primeiro de proposito: disco cheio ou teto por hora
    param a fila inteira, e nao adianta olhar conta por conta antes disso.
    """
    permitido, motivo = quotas.verificar()
    if not permitido:
        obs.registrar("fila.bloqueada", "skip", motivo=motivo, quota=True)
        return None

    for candidato in elegiveis():
        conta = store.obter("vexpublish_accounts", candidato["account"])
        if not conta:
            marcar_falha(candidato, CodigoErro.VALIDATION_ERROR, "Conta removida")
            continue
        permitido, motivo = planner.pode_publicar_agora(conta)
        if not permitido:
            adiar(candidato, motivo, conta)
            continue

        stamp = store.agora()
        with store.conectar() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                resultado = db.execute(
                    "UPDATE vexpublish_jobs SET status='publishing',worker_id=?,locked_at=?,"
                    "heartbeat_at=?,attempts=attempts+1,updated_at=? "
                    "WHERE id=? AND status=? AND worker_id IS NULL",
                    (worker_id, stamp, stamp, stamp, candidato["id"], candidato["status"]),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        if not resultado.rowcount:
            continue  # outro worker chegou antes

        store.registrar_evento(
            candidato["id"],
            "job.publishing",
            "ok",
            from_status=candidato["status"],
            to_status="publishing",
            detail={"worker_id": worker_id},
        )
        return store.obter("vexpublish_jobs", candidato["id"])
    return None


def batida(job_id: str, worker_id: str) -> None:
    with store.conectar() as db:
        db.execute(
            "UPDATE vexpublish_jobs SET heartbeat_at=?,updated_at=? "
            "WHERE id=? AND worker_id=? AND status='publishing'",
            (store.agora(), store.agora(), job_id, worker_id),
        )


def adiar(job: dict, motivo: str, conta: dict) -> dict:
    """Limite da conta atingido: empurra o job sem gastar tentativa."""
    proximo = planner.proximo_horario(conta).isoformat()
    with store.conectar() as db:
        db.execute(
            "UPDATE vexpublish_jobs SET run_after=?,updated_at=? WHERE id=? AND status=?",
            (proximo, store.agora(), job["id"], job["status"]),
        )
    store.registrar_evento(
        job["id"], "job.adiado", "ok", detail={"motivo": motivo, "run_after": proximo}
    )
    obs.registrar(
        "job.adiado",
        "skip",
        job_id=job["id"],
        channel_id=job["channel_id"],
        platform=job["platform"],
        account=conta.get("handle"),
        motivo=motivo,
    )
    return store.obter("vexpublish_jobs", job["id"])


def marcar_sucesso(job: dict, resultado: dict) -> dict:
    """So chega aqui com evidencia de conclusao, ou em dry-run explicito."""
    if resultado.get("dry_run"):
        atualizado = models.mudar_status(
            job["id"],
            "posted",
            worker_id=None,
            posted_at=store.agora(),
            published_url="",
            last_error="dry-run: nada foi publicado",
        )
    else:
        atualizado = models.mudar_status(
            job["id"],
            "posted",
            worker_id=None,
            posted_at=store.agora(),
            published_url=resultado.get("url", ""),
            last_error="",
            last_error_code=None,
        )
    obs.registrar(
        "job.posted",
        "ok",
        job_id=job["id"],
        channel_id=job["channel_id"],
        platform=job["platform"],
        dry_run=bool(resultado.get("dry_run")),
    )
    return atualizado


def marcar_falha(job: dict, codigo: str, mensagem: str) -> dict:
    """Decide entre retry com backoff e falha definitiva."""
    tentativas = int(job.get("attempts") or 0)
    maximo = int(job.get("max_attempts") or carregar().max_attempts)
    repetivel = codigo not in {
        CodigoErro.LOGIN_REQUIRED,
        CodigoErro.MANUAL_ACTION_REQUIRED,
        CodigoErro.VALIDATION_ERROR,
        CodigoErro.PLATFORM_CHANGED,
    }
    atual = store.obter("vexpublish_jobs", job["id"]) or job

    if repetivel and tentativas < maximo:
        destino = "retry" if atual["status"] == "publishing" else atual["status"]
        campos = {
            "worker_id": None,
            "run_after": _backoff(tentativas),
            "last_error_code": codigo,
            "last_error": mensagem[:500],
        }
        atualizado = (
            models.mudar_status(job["id"], "retry", **campos)
            if atual["status"] == "publishing"
            else store.atualizar("vexpublish_jobs", job["id"], campos)
        )
    else:
        campos = {"worker_id": None, "last_error_code": codigo, "last_error": mensagem[:500]}
        atualizado = (
            models.mudar_status(job["id"], "failed", **campos)
            if atual["status"] in {"publishing", "retry"}
            else store.atualizar("vexpublish_jobs", job["id"], campos)
        )

    obs.registrar(
        "job.falha",
        "error",
        job_id=job["id"],
        channel_id=job["channel_id"],
        platform=job["platform"],
        error_code=codigo,
        tentativas=tentativas,
        maximo=maximo,
    )
    return atualizado


def executar(job: dict, adapter=None) -> dict:
    """Roda um job ja reivindicado. Nunca chama publish em dry-run."""
    conta = store.obter("vexpublish_accounts", job["account"])
    if not conta:
        return marcar_falha(job, CodigoErro.VALIDATION_ERROR, "Conta removida")
    try:
        adapter = adapter or adapters.obter(job["platform"])
        resultado = adapters.executar(adapter, job, conta)
    except VexPublishError as erro:
        return marcar_falha(job, erro.codigo, erro.mensagem)
    except Exception as erro:  # falha inesperada nao pode derrubar o worker
        return marcar_falha(job, CodigoErro.UNKNOWN, str(erro))
    return marcar_sucesso(job, resultado)


def recuperar_orfaos() -> int:
    """Worker morto no meio: devolve o job para retry sem duplicar publicacao."""
    flags = carregar()
    corte = (_agora() - timedelta(seconds=flags.orphan_seconds)).isoformat()
    total = 0
    with store.conectar() as db:
        linhas = db.execute(
            "SELECT id, attempts, max_attempts FROM vexpublish_jobs "
            "WHERE status='publishing' AND COALESCE(heartbeat_at, locked_at) < ?",
            (corte,),
        ).fetchall()
    for linha in linhas:
        job = store.obter("vexpublish_jobs", linha["id"])
        marcar_falha(job, CodigoErro.UNKNOWN, "worker_orfao")
        total += 1
    return total


def resumo() -> dict:
    with store.conectar() as db:
        linhas = db.execute(
            "SELECT status, COUNT(*) AS total FROM vexpublish_jobs GROUP BY status"
        ).fetchall()
    return {
        "por_status": {linha["status"]: int(linha["total"]) for linha in linhas},
        "contas": registry.resumo(),
        "adapters": adapters.compatibilidade(),
        "quotas": quotas.estado(),
    }
