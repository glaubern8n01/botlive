"""Fase 9: quotas globais, doctor e comportamento em escala.

Os testes de performance medem e reportam, mas so afirmam limites folgados.
Assert apertado em tempo de maquina vira teste instavel - o que importa aqui
e que o custo nao exploda com o volume, nao o milissegundo exato.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from vexpublish.adapters.mock import MockAdapter
from vexpublish.core import analytics, doctor, models, quotas, store
from vexpublish.queue import jobs


def _canal(nome):
    registro = models.Channel(name=nome, platforms=["tiktok"], status="active").salvar()
    return store.obter("vexpublish_channels", registro["id"])


def _conta(channel_id, handle):
    registro = models.Account(
        channel_id=channel_id, platform="tiktok", handle=handle, status="active"
    ).salvar()
    return store.obter("vexpublish_accounts", registro["id"])


def _job(canal, conta, midia, sufixo, pronto=True):
    registro = models.PublishJob(
        channel_id=canal["id"],
        platform="tiktok",
        account=conta["id"],
        media_path=f"{midia}-{sufixo}",
        requires_approval=False,
    ).criar()
    if pronto:
        models.liberar_para_fila(registro["id"])
    return registro


# --- Quotas globais --------------------------------------------------------


def test_quotas_nascem_sem_teto_menos_o_disco():
    atual = quotas.limites()
    assert atual["max_jobs_per_hour"] == 0
    assert atual["max_queue_depth"] == 0
    assert atual["max_publishing"] == 0
    assert atual["min_free_disk_gb"] == 5.0


def test_disco_cheio_para_a_fila_inteira(job, sessao_valida, monkeypatch):
    models.aprovar(job["id"])
    models.liberar_para_fila(job["id"])
    monkeypatch.setattr(quotas, "disco_livre_gb", lambda caminho=None: 0.5)
    permitido, motivo = quotas.verificar()
    assert permitido is False
    assert motivo == "disco_cheio"
    assert jobs.reivindicar("worker-a") is None
    assert store.obter("vexpublish_jobs", job["id"])["status"] == "pending"


def test_disco_nao_medido_nao_bloqueia(monkeypatch):
    monkeypatch.setattr(quotas, "disco_livre_gb", lambda caminho=None: -1.0)
    assert quotas.verificar()[0] is True


def test_teto_por_hora_bloqueia(canal, conta, midia, monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_MAX_JOBS_PER_HOUR", "2")
    for sufixo in range(2):
        registro = _job(canal, conta, midia, f"h{sufixo}", pronto=False)
        store.atualizar(
            "vexpublish_jobs", registro["id"], {"status": "posted", "posted_at": store.agora()}
        )
    permitido, motivo = quotas.verificar()
    assert permitido is False
    assert motivo == "teto_por_hora"


def test_publicacao_antiga_nao_conta_no_teto_por_hora(canal, conta, midia, monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_MAX_JOBS_PER_HOUR", "1")
    antigo = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    registro = _job(canal, conta, midia, "antigo", pronto=False)
    store.atualizar("vexpublish_jobs", registro["id"], {"status": "posted", "posted_at": antigo})
    assert quotas.verificar()[0] is True


def test_fila_cheia_recusa_producao_nova(canal, conta, midia, monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_MAX_QUEUE_DEPTH", "2")
    for sufixo in range(2):
        _job(canal, conta, midia, f"f{sufixo}")
    permitido, motivo = quotas.aceita_novo_job()
    assert permitido is False
    assert motivo == "fila_cheia"


def test_estado_de_quota_lista_bloqueios(monkeypatch):
    monkeypatch.setattr(quotas, "disco_livre_gb", lambda caminho=None: 0.1)
    assert "disco_cheio" in quotas.estado()["bloqueios"]


# --- Doctor ----------------------------------------------------------------


def test_diagnostico_roda_todas_as_checagens():
    resultado = doctor.diagnostico()
    nomes = {x["check"] for x in resultado["checagens"]}
    assert nomes == {
        "dependencias", "banco", "jobs_travados", "sessoes", "storage", "filas", "configuracao"
    }


def test_banco_migrado_passa():
    assert next(x for x in doctor.diagnostico()["checagens"] if x["check"] == "banco")["status"] == "ok"


def test_dependencia_ausente_e_alerta_e_nao_erro(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda nome: None)
    checagem = doctor.dependencias()
    assert checagem["status"] == "alerta"
    assert doctor.diagnostico()["ok"] is True


def test_disco_abaixo_do_minimo_e_erro(monkeypatch):
    monkeypatch.setattr(quotas, "disco_livre_gb", lambda caminho=None: 0.2)
    assert doctor.storage()["status"] == "erro"
    resultado = doctor.diagnostico()
    assert resultado["ok"] is False
    assert "storage" in resultado["resumo"]["erros"]


def test_job_travado_vira_alerta(job, sessao_valida):
    models.aprovar(job["id"])
    models.liberar_para_fila(job["id"])
    jobs.reivindicar("worker-lento")
    antigo = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store.atualizar("vexpublish_jobs", job["id"], {"heartbeat_at": antigo, "locked_at": antigo})
    checagem = doctor.jobs_travados()
    assert checagem["status"] == "alerta"
    assert checagem["detalhe"]["quantidade"] == 1


def test_sessao_em_acao_manual_aparece_no_doctor(conta):
    from vexpublish.sessions import vault

    vault.marcar(conta["id"], "tiktok", "manual_required")
    assert doctor.sessoes()["status"] == "alerta"


def test_configuracao_declara_publicacao_bloqueada():
    checagem = doctor.configuracao()
    assert checagem["detalhe"]["plataformas_liberadas_para_publicacao_real"] == []
    assert checagem["detalhe"]["dry_run"] is True


def test_taxa_de_falha_alta_vira_alerta(canal, conta, midia):
    for sufixo in range(3):
        registro = _job(canal, conta, midia, f"x{sufixo}", pronto=False)
        store.atualizar(
            "vexpublish_jobs",
            registro["id"],
            {"status": "failed", "last_error_code": "UPLOAD_FAILED"},
        )
    checagem = doctor.filas()
    assert checagem["status"] == "alerta"
    assert checagem["detalhe"]["taxa_de_falha"] == 1.0


# --- Escala ----------------------------------------------------------------


def test_muitos_canais_e_contas_ficam_isolados(midia):
    canais = [_canal(f"Canal {indice}") for indice in range(5)]
    for indice, canal in enumerate(canais):
        for conta_indice in range(3):
            conta = _conta(canal["id"], f"@c{indice}_{conta_indice}")
            _job(canal, conta, midia, f"{indice}-{conta_indice}", pronto=False)

    comparacao = analytics.comparar_canais()
    assert comparacao["totais"]["canais"] == 5
    for linha in comparacao["canais"]:
        assert linha["contas"] == 3
        assert linha["fila"]["draft"] == 3


def test_fila_com_volume_nao_entrega_job_duas_vezes(midia, sessao_valida, canal, conta, monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "true")
    monkeypatch.setenv("VEXPUBLISH_TIKTOK_ENABLED", "true")
    total = 40
    for sufixo in range(total):
        _job(canal, conta, midia, f"v{sufixo}")

    vistos, adapter = [], MockAdapter()
    while True:
        reivindicado = jobs.reivindicar(f"worker-{len(vistos) % 3}")
        if not reivindicado:
            break
        vistos.append(reivindicado["id"])
        jobs.executar(reivindicado, adapter=adapter)

    assert len(vistos) == total
    assert len(set(vistos)) == total  # nenhum job processado duas vezes
    assert "publish" not in adapter.chamadas  # dry-run seguiu valendo


def test_custo_da_selecao_nao_explode_com_volume(canal, conta, midia):
    """A consulta de elegiveis e limitada: 20x mais jobs nao custa 20x mais."""
    for sufixo in range(20):
        _job(canal, conta, midia, f"p{sufixo}")
    inicio = time.perf_counter()
    jobs.elegiveis()
    pequeno = time.perf_counter() - inicio

    for sufixo in range(20, 400):
        _job(canal, conta, midia, f"p{sufixo}")
    inicio = time.perf_counter()
    resultado = jobs.elegiveis()
    grande = time.perf_counter() - inicio

    assert len(resultado) == 50  # limite da consulta, nao o tamanho da fila
    assert grande < max(pequeno * 8, 0.5)


def test_resumo_da_fila_traz_quotas(job):
    resumo = jobs.resumo()
    assert "quotas" in resumo
    assert "limites" in resumo["quotas"]
    assert resumo["por_status"]["draft"] == 1
