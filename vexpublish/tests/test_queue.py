"""Fila: lock, dry-run, retry com backoff, teto de tentativas e orfaos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vexpublish.adapters.mock import MockAdapter
from vexpublish.core import models, store
from vexpublish.core.errors import CodigoErro
from vexpublish.queue import jobs


def _pronto(job_id: str) -> dict:
    models.aprovar(job_id)
    return models.liberar_para_fila(job_id)


def _ligar_plataforma(monkeypatch, dry_run="true"):
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "true")
    monkeypatch.setenv("VEXPUBLISH_TIKTOK_ENABLED", "true")
    monkeypatch.setenv("VEXPUBLISH_DRY_RUN", dry_run)


def test_job_em_draft_nao_e_elegivel(job):
    assert jobs.elegiveis() == []


def test_job_aprovado_entra_na_fila(job):
    _pronto(job["id"])
    assert [item["id"] for item in jobs.elegiveis()] == [job["id"]]


def test_apenas_um_worker_pega_o_job(job, sessao_valida):
    _pronto(job["id"])
    primeiro = jobs.reivindicar("worker-a")
    segundo = jobs.reivindicar("worker-b")
    assert primeiro is not None
    assert segundo is None
    assert primeiro["status"] == "publishing"
    assert primeiro["attempts"] == 1


def test_dry_run_nao_chama_publish(job, sessao_valida, monkeypatch):
    _ligar_plataforma(monkeypatch, dry_run="true")
    _pronto(job["id"])
    reivindicado = jobs.reivindicar("worker-a")
    adapter = MockAdapter()
    final = jobs.executar(reivindicado, adapter=adapter)
    assert "publish" not in adapter.chamadas
    assert adapter.chamadas == ["check_session", "validate", "prepare"]
    assert final["status"] == "posted"
    assert final["published_url"] == ""
    assert "dry-run" in final["last_error"]


def test_publicacao_real_so_com_tudo_ligado(job, sessao_valida, monkeypatch):
    _ligar_plataforma(monkeypatch, dry_run="false")
    # job foi criado com dry_run=1; publicacao real exige job liberado tambem
    store.atualizar("vexpublish_jobs", job["id"], {"dry_run": 0})
    _pronto(job["id"])
    reivindicado = jobs.reivindicar("worker-a")
    adapter = MockAdapter()
    final = jobs.executar(reivindicado, adapter=adapter)
    assert "publish" in adapter.chamadas
    assert final["status"] == "posted"
    assert final["published_url"].startswith("https://")
    assert final["posted_at"]


def test_job_marcado_dry_run_ignora_flag_real(job, sessao_valida, monkeypatch):
    _ligar_plataforma(monkeypatch, dry_run="false")
    _pronto(job["id"])
    reivindicado = jobs.reivindicar("worker-a")
    adapter = MockAdapter()
    jobs.executar(reivindicado, adapter=adapter)
    assert "publish" not in adapter.chamadas


def test_plataforma_desligada_bloqueia(job, sessao_valida, monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "true")
    _pronto(job["id"])
    reivindicado = jobs.reivindicar("worker-a")
    final = jobs.executar(reivindicado, adapter=MockAdapter())
    assert final["status"] == "failed"
    assert final["last_error_code"] == CodigoErro.VALIDATION_ERROR


def test_erro_de_rede_vira_retry_com_backoff(job, sessao_valida, monkeypatch):
    _ligar_plataforma(monkeypatch, dry_run="false")
    store.atualizar("vexpublish_jobs", job["id"], {"dry_run": 0})
    _pronto(job["id"])
    reivindicado = jobs.reivindicar("worker-a")
    final = jobs.executar(reivindicado, adapter=MockAdapter(falhar_com=CodigoErro.NETWORK_ERROR))
    assert final["status"] == "retry"
    assert final["last_error_code"] == CodigoErro.NETWORK_ERROR
    assert final["worker_id"] is None
    assert datetime.fromisoformat(final["run_after"]) > datetime.now(timezone.utc)


def test_acao_manual_nao_repete(job, sessao_valida, monkeypatch):
    _ligar_plataforma(monkeypatch, dry_run="false")
    store.atualizar("vexpublish_jobs", job["id"], {"dry_run": 0})
    _pronto(job["id"])
    reivindicado = jobs.reivindicar("worker-a")
    final = jobs.executar(
        reivindicado, adapter=MockAdapter(falhar_com=CodigoErro.MANUAL_ACTION_REQUIRED)
    )
    assert final["status"] == "failed"
    assert final["attempts"] == 1


def test_teto_de_tentativas_encerra_em_failed(job, sessao_valida, monkeypatch):
    _ligar_plataforma(monkeypatch, dry_run="false")
    store.atualizar("vexpublish_jobs", job["id"], {"dry_run": 0})
    _pronto(job["id"])
    adapter = MockAdapter(falhar_com=CodigoErro.NETWORK_ERROR)
    for tentativa in range(1, 4):
        reivindicado = jobs.reivindicar(f"worker-{tentativa}")
        assert reivindicado is not None, f"tentativa {tentativa} nao reivindicou"
        final = jobs.executar(reivindicado, adapter=adapter)
        store.atualizar("vexpublish_jobs", job["id"], {"run_after": None})
    assert final["status"] == "failed"
    assert final["attempts"] == 3
    assert jobs.reivindicar("worker-4") is None


def test_backoff_cresce_e_respeita_teto(monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_BACKOFF_BASE_SECONDS", "10")
    monkeypatch.setenv("VEXPUBLISH_BACKOFF_MAX_SECONDS", "40")
    agora = datetime.now(timezone.utc)
    esperas = [
        (datetime.fromisoformat(jobs._backoff(tentativa)) - agora).total_seconds()
        for tentativa in (1, 2, 3, 9)
    ]
    assert esperas[0] < esperas[1] < esperas[2]
    assert esperas[3] <= 41


def test_worker_orfao_volta_para_retry(job, sessao_valida):
    _pronto(job["id"])
    jobs.reivindicar("worker-morto")
    antigo = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store.atualizar("vexpublish_jobs", job["id"], {"heartbeat_at": antigo, "locked_at": antigo})
    assert jobs.recuperar_orfaos() == 1
    recuperado = store.obter("vexpublish_jobs", job["id"])
    assert recuperado["status"] == "retry"
    assert recuperado["worker_id"] is None


def test_batida_mantem_job_vivo(job, sessao_valida):
    _pronto(job["id"])
    jobs.reivindicar("worker-a")
    anterior = store.obter("vexpublish_jobs", job["id"])["heartbeat_at"]
    store.atualizar("vexpublish_jobs", job["id"], {"heartbeat_at": "2020-01-01T00:00:00+00:00"})
    jobs.batida(job["id"], "worker-a")
    assert store.obter("vexpublish_jobs", job["id"])["heartbeat_at"] > "2020-01-01"
    assert anterior


def test_resumo_agrega_status_contas_e_adapters(job):
    dados = jobs.resumo()
    assert dados["por_status"]["draft"] == 1
    assert "tiktok" in dados["contas"]
    assert dados["adapters"]["kwai"] == "NAO"  # investigado em 22/08, sem rota
