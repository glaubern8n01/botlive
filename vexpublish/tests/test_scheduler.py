"""Scheduler: janela de horario, intervalo minimo e teto diario por conta."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vexpublish.accounts import registry
from vexpublish.core import models, store
from vexpublish.queue import jobs
from vexpublish.scheduler import planner


def _publicado(conta, midia, quando, sufixo):
    """Cria um job ja concluido para alimentar os contadores da conta."""
    registro = models.PublishJob(
        channel_id=conta["channel_id"],
        platform=conta["platform"],
        account=conta["id"],
        media_path=f"{midia}-{sufixo}",
        requires_approval=False,
    ).criar()
    store.atualizar(
        "vexpublish_jobs",
        registro["id"],
        {"status": "posted", "posted_at": quando.isoformat()},
    )
    return registro


def test_conta_sem_limite_publica_agora(conta):
    assert planner.pode_publicar_agora(conta) == (True, "")


def test_conta_inativa_nao_publica(conta):
    registry.pausar(conta["id"])
    pausada = store.obter("vexpublish_accounts", conta["id"])
    permitido, motivo = planner.pode_publicar_agora(pausada)
    assert permitido is False
    assert motivo == "conta_inativa"


def test_fora_da_janela_de_horario(conta):
    agora = datetime.now(timezone.utc)
    proibida = (agora.hour + 3) % 24
    registry.definir_limites(conta["id"], allowed_hours=[proibida])
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    permitido, motivo = planner.pode_publicar_agora(ajustada, agora)
    assert permitido is False
    assert motivo == "fora_da_janela"


def test_dentro_da_janela_de_horario(conta):
    agora = datetime.now(timezone.utc)
    registry.definir_limites(conta["id"], allowed_hours=[agora.hour])
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    assert planner.pode_publicar_agora(ajustada, agora)[0] is True


def test_intervalo_minimo_bloqueia(conta, midia):
    registry.definir_limites(conta["id"], minimum_interval_minutes=60)
    _publicado(conta, midia, datetime.now(timezone.utc) - timedelta(minutes=10), "a")
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    permitido, motivo = planner.pode_publicar_agora(ajustada)
    assert permitido is False
    assert motivo == "intervalo_minimo"


def test_intervalo_minimo_libera_apos_espera(conta, midia):
    registry.definir_limites(conta["id"], minimum_interval_minutes=30)
    _publicado(conta, midia, datetime.now(timezone.utc) - timedelta(minutes=90), "b")
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    assert planner.pode_publicar_agora(ajustada)[0] is True


def test_teto_diario_bloqueia(conta, midia):
    # Momento fixo no meio do dia: perto da meia-noite o teto reseta, e o
    # teste nao pode depender da hora em que a suite roda.
    referencia = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    registry.definir_limites(conta["id"], max_posts_per_day=2)
    _publicado(conta, midia, referencia - timedelta(minutes=30), "c")
    _publicado(conta, midia, referencia - timedelta(minutes=20), "d")
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    permitido, motivo = planner.pode_publicar_agora(ajustada, referencia)
    assert permitido is False
    assert motivo == "teto_diario"


def test_teto_diario_reseta_no_dia_seguinte(conta, midia):
    referencia = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    registry.definir_limites(conta["id"], max_posts_per_day=2)
    _publicado(conta, midia, referencia - timedelta(days=1), "e1")
    _publicado(conta, midia, referencia - timedelta(days=1, minutes=10), "e2")
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    assert planner.pode_publicar_agora(ajustada, referencia)[0] is True


def test_proximo_horario_respeita_intervalo(conta, midia):
    registry.definir_limites(conta["id"], minimum_interval_minutes=45)
    ultima = datetime.now(timezone.utc) - timedelta(minutes=5)
    _publicado(conta, midia, ultima, "e")
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    assert planner.proximo_horario(ajustada) >= ultima + timedelta(minutes=45)


def test_proximo_horario_cai_na_hora_permitida(conta):
    agora = datetime.now(timezone.utc)
    alvo = (agora.hour + 5) % 24
    registry.definir_limites(conta["id"], allowed_hours=[alvo])
    ajustada = store.obter("vexpublish_accounts", conta["id"])
    assert planner.proximo_horario(ajustada, agora).hour == alvo


def test_job_bloqueado_por_limite_e_adiado_sem_gastar_tentativa(job, conta, midia):
    registry.definir_limites(conta["id"], minimum_interval_minutes=120)
    _publicado(conta, midia, datetime.now(timezone.utc) - timedelta(minutes=5), "f")
    models.aprovar(job["id"])
    models.liberar_para_fila(job["id"])
    assert jobs.reivindicar("worker-a") is None
    adiado = store.obter("vexpublish_jobs", job["id"])
    assert adiado["status"] == "pending"
    assert adiado["attempts"] == 0
    assert adiado["run_after"] is not None
