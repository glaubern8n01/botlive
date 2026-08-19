"""Entidades, flags, idempotencia, aprovacao e maquina de estados."""

from __future__ import annotations

import pytest

from vexpublish.core import flags, models, obs, store
from vexpublish.core.errors import CodigoErro, VexPublishError, transicao_valida


def test_flags_nascem_desligadas_e_em_dry_run():
    atual = flags.carregar()
    assert atual.enabled is False
    assert atual.dry_run is True
    assert atual.auto_publish is False
    assert atual.require_approval is True
    assert all(not atual.plataforma_ativa(p) for p in flags.PLATAFORMAS)
    assert atual.pode_publicar_de_verdade("tiktok") is False


def test_publicacao_real_exige_tres_condicoes(monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "true")
    assert flags.carregar().pode_publicar_de_verdade("tiktok") is False
    monkeypatch.setenv("VEXPUBLISH_TIKTOK_ENABLED", "true")
    assert flags.carregar().pode_publicar_de_verdade("tiktok") is False
    monkeypatch.setenv("VEXPUBLISH_DRY_RUN", "false")
    assert flags.carregar().pode_publicar_de_verdade("tiktok") is True


def test_job_repetido_nao_duplica(canal, conta, midia):
    primeiro = models.PublishJob(
        channel_id=canal["id"], platform="tiktok", account=conta["id"], media_path=midia
    ).criar()
    segundo = models.PublishJob(
        channel_id=canal["id"], platform="tiktok", account=conta["id"], media_path=midia
    ).criar()
    assert primeiro["id"] == segundo["id"]
    assert len(store.listar("vexpublish_jobs")) == 1


def test_agendamento_diferente_gera_job_diferente(canal, conta, midia):
    primeiro = models.PublishJob(
        channel_id=canal["id"], platform="tiktok", account=conta["id"], media_path=midia
    ).criar()
    segundo = models.PublishJob(
        channel_id=canal["id"],
        platform="tiktok",
        account=conta["id"],
        media_path=midia,
        scheduled_at="2026-09-01T12:00:00+00:00",
    ).criar()
    assert primeiro["id"] != segundo["id"]


def test_job_nasce_em_draft_com_aprovacao_obrigatoria(job):
    assert job["status"] == "draft"
    assert job["requires_approval"] == 1
    assert job["dry_run"] == 1


def test_fila_recusa_job_sem_aprovacao(job):
    with pytest.raises(VexPublishError) as erro:
        models.liberar_para_fila(job["id"])
    assert erro.value.codigo == CodigoErro.VALIDATION_ERROR


def test_aprovacao_libera_para_pending(job):
    models.aprovar(job["id"])
    liberado = models.liberar_para_fila(job["id"])
    assert liberado["status"] == "pending"


def test_job_agendado_vai_para_scheduled(canal, conta, midia):
    agendado = models.PublishJob(
        channel_id=canal["id"],
        platform="tiktok",
        account=conta["id"],
        media_path=midia,
        scheduled_at="2026-09-01T12:00:00+00:00",
    ).criar()
    models.aprovar(agendado["id"])
    assert models.liberar_para_fila(agendado["id"])["status"] == "scheduled"


def test_transicao_invalida_e_recusada(job):
    assert transicao_valida("draft", "posted") is False
    with pytest.raises(VexPublishError):
        models.mudar_status(job["id"], "posted")


def test_job_terminal_nao_revive(job):
    models.cancelar(job["id"], "teste")
    with pytest.raises(VexPublishError):
        models.mudar_status(job["id"], "pending")


def test_conta_de_outra_plataforma_e_recusada(canal, conta, midia):
    with pytest.raises(VexPublishError):
        models.PublishJob(
            channel_id=canal["id"], platform="youtube", account=conta["id"], media_path=midia
        ).criar()


def test_plataforma_desconhecida_e_recusada(canal, conta, midia):
    with pytest.raises(VexPublishError):
        models.PublishJob(
            channel_id=canal["id"], platform="orkut", account=conta["id"], media_path=midia
        ).criar()


def test_limite_por_conta_nao_e_fixo(canal):
    registro = models.Account(
        channel_id=canal["id"],
        platform="youtube",
        handle="outra",
        max_posts_per_day=7,
        minimum_interval_minutes=45,
        allowed_hours=[9, 20],
    ).salvar()
    salvo = store.obter("vexpublish_accounts", registro["id"])
    assert salvo["max_posts_per_day"] == 7
    assert salvo["minimum_interval_minutes"] == 45
    assert salvo["allowed_hours"] == "[9, 20]"


def test_hora_invalida_e_recusada(canal):
    with pytest.raises(VexPublishError):
        models.Account(
            channel_id=canal["id"], platform="tiktok", handle="x", allowed_hours=[25]
        ).salvar()


def test_log_nao_vaza_segredo():
    registro = obs.evento(
        "adapter.login",
        "ok",
        platform="tiktok",
        cookie="abc123",
        access_token="xyz",
        detalhe_aninhado={"session_id": "s-1", "publico": "ok"},
    )
    texto = str(registro)
    assert "abc123" not in texto
    assert "xyz" not in texto
    assert "s-1" not in texto
    assert "ok" in texto


def test_evento_tem_todos_os_campos_obrigatorios():
    registro = obs.evento("job.posted", "ok", job_id="1", channel_id="2", platform="tiktok")
    for campo in obs.CAMPOS:
        assert campo in registro


def test_codigo_de_erro_desconhecido_vira_unknown():
    registro = obs.evento("x", "error", error_code="EXPLODIU")
    assert registro["error_code"] == "UNKNOWN"
    assert VexPublishError("EXPLODIU").codigo == CodigoErro.UNKNOWN
