"""Fase 4: API local de canais, contas, fila e comparacao."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vexpublish.api import app
from vexpublish.core import models, store


ADMIN = {"X-VexPublish-Token": "admin-vex"}
LEITOR = {"X-VexPublish-Token": "reviewer-vex"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("BOTLIVE_MULTICHANNEL_ENABLED", "true")
    monkeypatch.setenv("VEXPUBLISH_ADMIN_TOKEN", "admin-vex")
    monkeypatch.setenv("VEXPUBLISH_OPERATOR_TOKEN", "operator-vex")
    monkeypatch.setenv("VEXPUBLISH_REVIEWER_TOKEN", "reviewer-vex")
    return TestClient(app)


def _canal(cliente, nome="Marca Teste"):
    resposta = cliente.post(
        "/vexpublish/v1/channels",
        headers=ADMIN,
        json={"name": nome, "niche": "gta", "platforms": ["tiktok"]},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _conta(cliente, channel_id, handle="@marca_teste"):
    resposta = cliente.post(
        "/vexpublish/v1/accounts",
        headers=ADMIN,
        json={"channel_id": channel_id, "platform": "tiktok", "handle": handle},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_health_e_publico_e_mostra_o_que_esta_liberado(cliente):
    dados = cliente.get("/vexpublish/v1/health").json()
    assert dados["dry_run"] is True
    assert dados["enabled"] is False
    assert dados["publicacao_real_liberada"] == {
        "tiktok": False,
        "instagram": False,
        "youtube": False,
        "kwai": False,
    }
    assert dados["adapters"]["kwai"] == "NAO"  # investigado em 22/08, sem rota


def test_modulo_desligado_esconde_rotas(cliente, monkeypatch):
    monkeypatch.setenv("BOTLIVE_MULTICHANNEL_ENABLED", "false")
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "false")
    assert cliente.get("/vexpublish/v1/channels", headers=ADMIN).status_code == 404


def test_sem_token_nao_le_nada(cliente):
    assert cliente.get("/vexpublish/v1/channels").status_code == 401


def test_papel_sem_permissao_nao_escreve(cliente):
    resposta = cliente.post(
        "/vexpublish/v1/channels", headers=LEITOR, json={"name": "Proibido", "platforms": []}
    )
    assert resposta.status_code == 403


def test_cria_edita_e_pausa_canal(cliente):
    canal = _canal(cliente)
    assert canal["slug"] == "marca-teste"
    assert canal["status"] == "paused"

    editado = cliente.put(
        f"/vexpublish/v1/channels/{canal['id']}",
        headers=ADMIN,
        json={"name": "Marca Teste", "niche": "futebol", "platforms": ["tiktok", "youtube"]},
    ).json()
    assert editado["niche"] == "futebol"
    assert "youtube" in editado["platforms"]

    ativado = cliente.post(
        f"/vexpublish/v1/channels/{canal['id']}/status?ativo=true", headers=ADMIN
    ).json()
    assert ativado["status"] == "active"
    pausado = cliente.post(
        f"/vexpublish/v1/channels/{canal['id']}/status?ativo=false", headers=ADMIN
    ).json()
    assert pausado["status"] == "paused"


def test_plataforma_invalida_e_recusada(cliente):
    resposta = cliente.post(
        "/vexpublish/v1/channels", headers=ADMIN, json={"name": "Ruim", "platforms": ["orkut"]}
    )
    assert resposta.status_code == 422


def test_conta_nasce_inativa_e_com_sessao_registrada(cliente):
    canal = _canal(cliente)
    conta = _conta(cliente, canal["id"])
    assert conta["status"] == "inactive"
    sessoes = cliente.get("/vexpublish/v1/sessions", headers=ADMIN).json()["items"]
    assert sessoes[0]["state"] == "missing"
    assert "storage_path" not in sessoes[0]


def test_limites_sao_por_conta(cliente):
    canal = _canal(cliente)
    conta = _conta(cliente, canal["id"])
    atualizada = cliente.put(
        f"/vexpublish/v1/accounts/{conta['id']}/limits",
        headers=ADMIN,
        json={"max_posts_per_day": 12, "minimum_interval_minutes": 40, "allowed_hours": [9, 18]},
    ).json()
    assert atualizada["max_posts_per_day"] == 12
    assert atualizada["allowed_hours"] == "[9, 18]"


def test_hora_invalida_no_limite_e_recusada(cliente):
    canal = _canal(cliente)
    conta = _conta(cliente, canal["id"])
    resposta = cliente.put(
        f"/vexpublish/v1/accounts/{conta['id']}/limits",
        headers=ADMIN,
        json={"allowed_hours": [99]},
    )
    assert resposta.status_code == 422


def test_conta_em_canal_inexistente_e_recusada(cliente):
    resposta = cliente.post(
        "/vexpublish/v1/accounts",
        headers=ADMIN,
        json={"channel_id": "fantasma", "platform": "tiktok", "handle": "@x"},
    )
    assert resposta.status_code == 404


def test_aprovar_nao_publica(cliente, midia):
    canal = _canal(cliente)
    conta = _conta(cliente, canal["id"])
    job = models.PublishJob(
        channel_id=canal["id"], platform="tiktok", account=conta["id"], media_path=midia
    ).criar()

    aprovado = cliente.post(f"/vexpublish/v1/jobs/{job['id']}/approve", headers=ADMIN).json()
    assert aprovado["status"] == "approved"
    enfileirado = cliente.post(f"/vexpublish/v1/jobs/{job['id']}/queue", headers=ADMIN).json()
    assert enfileirado["status"] == "pending"
    assert enfileirado["published_url"] == ""
    assert store.obter("vexpublish_jobs", job["id"])["posted_at"] is None


def test_fila_recusa_job_sem_aprovacao(cliente, midia):
    canal = _canal(cliente)
    conta = _conta(cliente, canal["id"])
    job = models.PublishJob(
        channel_id=canal["id"], platform="tiktok", account=conta["id"], media_path=midia
    ).criar()
    assert cliente.post(f"/vexpublish/v1/jobs/{job['id']}/queue", headers=ADMIN).status_code == 422


def test_comparacao_lista_canais(cliente):
    primeiro = _canal(cliente, "Marca Um")
    _canal(cliente, "Marca Dois")
    cliente.post(
        "/vexpublish/v1/metrics",
        headers=ADMIN,
        json={"channel_id": primeiro["id"], "platform": "tiktok", "views": 500, "revenue": 3.2},
    )
    comparacao = cliente.get("/vexpublish/v1/compare", headers=ADMIN).json()
    assert comparacao["totais"]["canais"] == 2
    assert comparacao["canais"][0]["slug"] == "marca-um"
    assert "marca-dois" in comparacao["canais_sem_metricas"]


def test_resumo_e_historico_do_canal(cliente, midia):
    canal = _canal(cliente)
    conta = _conta(cliente, canal["id"])
    models.PublishJob(
        channel_id=canal["id"], platform="tiktok", account=conta["id"], media_path=midia
    ).criar()
    resumo = cliente.get(f"/vexpublish/v1/channels/{canal['id']}", headers=ADMIN).json()
    assert resumo["fila"]["draft"] == 1
    historico = cliente.get(f"/vexpublish/v1/channels/{canal['id']}/history", headers=ADMIN).json()
    assert len(historico["items"]) == 1


def test_canal_inexistente_devolve_404(cliente):
    assert cliente.get("/vexpublish/v1/channels/fantasma", headers=ADMIN).status_code == 404
