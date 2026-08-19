"""Isolamento dos testes: banco temporario, sessoes temporarias, flags limpas.

Nenhum teste pode tocar vexpublish.db real nem depender do ambiente da maquina.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vexpublish.core import models, store  # noqa: E402
from vexpublish.core.flags import PADROES  # noqa: E402
from vexpublish.sessions import vault  # noqa: E402


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "vexpublish.db")
    monkeypatch.setenv("VEXPUBLISH_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("VEXPUBLISH_LOG_SILENT", "true")
    for chave, valor in PADROES.items():
        monkeypatch.setenv(chave, valor)
    monkeypatch.setenv("VEXPUBLISH_BACKOFF_BASE_SECONDS", "30")
    monkeypatch.setenv("VEXPUBLISH_MAX_ATTEMPTS", "3")
    store.migrar()
    yield tmp_path


@pytest.fixture
def canal():
    return models.Channel(name="Canal Teste", niche="gta", platforms=["tiktok"]).salvar()


@pytest.fixture
def conta(canal):
    registro = models.Account(
        channel_id=canal["id"],
        platform="tiktok",
        handle="teste_handle",
        status="active",
    ).salvar()
    return store.obter("vexpublish_accounts", registro["id"])


@pytest.fixture
def midia(tmp_path):
    caminho = tmp_path / "corte.mp4"
    caminho.write_bytes(b"conteudo-de-video-fake")
    return str(caminho)


@pytest.fixture
def job(canal, conta, midia):
    return models.PublishJob(
        channel_id=canal["id"],
        platform="tiktok",
        account=conta["id"],
        media_path=midia,
        title="Titulo",
        caption="Legenda #gta6",
        hashtags=["#gta6"],
    ).criar()


@pytest.fixture
def sessao_valida(conta):
    vault.marcar(conta["id"], "tiktok", "valid")
    return conta
