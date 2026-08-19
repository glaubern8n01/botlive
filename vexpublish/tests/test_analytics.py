"""Fase 4: snapshots de metrica e comparacao entre canais."""

from __future__ import annotations

import pytest

from vexpublish.core import analytics, models, store
from vexpublish.core.errors import VexPublishError


def _canal(nome, status="active"):
    registro = models.Channel(name=nome, niche="gta", platforms=["tiktok"], status=status).salvar()
    return store.obter("vexpublish_channels", registro["id"])


def _conta(channel_id, handle):
    registro = models.Account(
        channel_id=channel_id, platform="tiktok", handle=handle, status="active"
    ).salvar()
    return store.obter("vexpublish_accounts", registro["id"])


def _job_postado(channel_id, conta, midia, sufixo):
    registro = models.PublishJob(
        channel_id=channel_id,
        platform="tiktok",
        account=conta["id"],
        media_path=f"{midia}-{sufixo}",
        requires_approval=False,
    ).criar()
    store.atualizar(
        "vexpublish_jobs", registro["id"], {"status": "posted", "posted_at": store.agora()}
    )
    return registro


def test_canal_novo_nao_inventa_metrica(canal):
    resumo = analytics.resumo_canal(canal["id"])
    assert resumo["publicados"] == 0
    assert resumo["views"] == 0
    assert resumo["sem_metricas"] is True
    assert resumo["taxa_sucesso"] is None


def test_snapshot_alimenta_o_resumo(canal):
    analytics.registrar_snapshot(canal["id"], "tiktok", views=1200, retention=0.42, revenue=15.5)
    analytics.registrar_snapshot(canal["id"], "tiktok", views=800, retention=0.58, revenue=4.5)
    resumo = analytics.resumo_canal(canal["id"])
    assert resumo["views"] == 2000
    assert resumo["receita"] == 20.0
    assert resumo["retencao_media"] == 0.5
    assert resumo["amostras"] == 2
    assert resumo["sem_metricas"] is False


def test_snapshot_recusa_valores_impossiveis(canal):
    with pytest.raises(VexPublishError):
        analytics.registrar_snapshot(canal["id"], "tiktok", views=-1)
    with pytest.raises(VexPublishError):
        analytics.registrar_snapshot(canal["id"], "tiktok", retention=1.7)
    with pytest.raises(VexPublishError):
        analytics.registrar_snapshot(canal["id"], "orkut", views=1)
    with pytest.raises(VexPublishError):
        analytics.registrar_snapshot("canal-fantasma", "tiktok", views=1)


def test_frequencia_e_taxa_de_sucesso(canal, conta, midia):
    for sufixo in range(3):
        _job_postado(canal["id"], conta, midia, sufixo)
    falho = models.PublishJob(
        channel_id=canal["id"],
        platform="tiktok",
        account=conta["id"],
        media_path=f"{midia}-falho",
        requires_approval=False,
    ).criar()
    store.atualizar(
        "vexpublish_jobs", falho["id"], {"status": "failed", "last_error_code": "UPLOAD_FAILED"}
    )

    resumo = analytics.resumo_canal(canal["id"], dias=30)
    assert resumo["publicados"] == 3
    assert resumo["falhas"] == 1
    assert resumo["taxa_sucesso"] == 0.75
    assert resumo["frequencia_por_dia"] == 0.1
    assert resumo["falhas_por_codigo"]["UPLOAD_FAILED"] == 1


def test_comparacao_ordena_por_views(midia):
    fraco = _canal("Canal Fraco")
    forte = _canal("Canal Forte")
    analytics.registrar_snapshot(fraco["id"], "tiktok", views=10)
    analytics.registrar_snapshot(forte["id"], "tiktok", views=9000)
    comparacao = analytics.comparar_canais()
    assert [x["slug"] for x in comparacao["canais"]][0] == "canal-forte"
    assert comparacao["totais"]["views"] == 9010
    assert comparacao["totais"]["canais"] == 2


def test_comparacao_aponta_quem_esta_sem_dados():
    _canal("Com Dados")
    sem = _canal("Sem Dados")
    analytics.registrar_snapshot(
        store.listar("vexpublish_channels", where="slug=?", params=("com-dados",))[0]["id"],
        "tiktok",
        views=5,
    )
    comparacao = analytics.comparar_canais()
    assert "sem-dados" in comparacao["canais_sem_metricas"]
    assert "com-dados" not in comparacao["canais_sem_metricas"]
    assert sem["status"] == "active"


def test_comparacao_pode_esconder_pausados():
    _canal("Ativo Um")
    _canal("Pausado Um", status="paused")
    assert len(analytics.comparar_canais()["canais"]) == 2
    somente_ativos = analytics.comparar_canais(incluir_pausados=False)
    assert [x["slug"] for x in somente_ativos["canais"]] == ["ativo-um"]


def test_canais_sao_isolados(canal, conta, midia):
    outro = _canal("Outro Canal")
    _conta(outro["id"], "@outro_handle")
    _job_postado(canal["id"], conta, midia, "x")
    assert analytics.resumo_canal(canal["id"])["publicados"] == 1
    assert analytics.resumo_canal(outro["id"])["publicados"] == 0


def test_historico_traz_jobs_do_canal(canal, conta, midia):
    _job_postado(canal["id"], conta, midia, "h1")
    _job_postado(canal["id"], conta, midia, "h2")
    historico = analytics.historico_canal(canal["id"])
    assert len(historico) == 2
    assert all(x["channel_id"] == canal["id"] for x in historico)


def test_resumo_conta_plataformas_e_contas_ativas(canal, conta):
    models.Account(
        channel_id=canal["id"], platform="youtube", handle="@yt", status="inactive"
    ).salvar()
    resumo = analytics.resumo_canal(canal["id"])
    assert resumo["contas"] == 2
    assert resumo["contas_ativas"] == 1
    assert resumo["plataformas"] == ["tiktok", "youtube"]
