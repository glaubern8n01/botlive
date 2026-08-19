"""Adapters e sessoes: contrato, compatibilidade, captcha/2FA e bloqueios."""

from __future__ import annotations

from pathlib import Path

import pytest

from vexpublish import adapters
from vexpublish.adapters import base
from vexpublish.adapters.mock import MockAdapter
from vexpublish.core.errors import CodigoErro, VexPublishError
from vexpublish.sessions import vault


PLATAFORMAS = ("tiktok", "instagram", "youtube", "kwai")


def _ligar(monkeypatch, plataforma="tiktok", dry_run="true"):
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "true")
    monkeypatch.setenv(f"VEXPUBLISH_{plataforma.upper()}_ENABLED", "true")
    monkeypatch.setenv("VEXPUBLISH_DRY_RUN", dry_run)


def test_registro_cobre_as_quatro_plataformas():
    assert set(adapters.REGISTRO) == set(PLATAFORMAS)


def test_compatibilidade_declarada_bate_com_a_realidade():
    """YouTube tem login real ligado; os outros tres seguem sem nada testado."""
    atual = adapters.compatibilidade()
    assert atual["youtube"] == "PARCIAL"
    assert atual["tiktok"] == atual["instagram"] == atual["kwai"] == "NAO VALIDADO"


def test_nenhum_adapter_publica_de_verdade():
    """PARCIAL vale para login. Envio real continua nao existindo em nenhum."""
    assert all(x != "SIM" for x in adapters.compatibilidade().values())


@pytest.mark.parametrize("plataforma", ("tiktok", "instagram", "kwai"))
def test_publish_real_ainda_nao_existe(plataforma, job, conta):
    adapter = adapters.obter(plataforma)
    with pytest.raises(VexPublishError) as erro:
        adapter.publish(job, conta, {})
    assert erro.value.codigo == CodigoErro.MANUAL_ACTION_REQUIRED


def test_youtube_recusa_envio_sem_arquivo(job, conta):
    """Unico adapter com publish real: falha antes de tocar a rede."""
    adapter = adapters.obter("youtube")
    with pytest.raises(VexPublishError) as erro:
        adapter.publish(job, conta, {"video_path": "nao-existe.mp4"})
    assert erro.value.codigo == CodigoErro.VALIDATION_ERROR


def test_youtube_nasce_private():
    from vexpublish.adapters import youtube

    assert youtube._visibilidade(None) == "private"
    assert youtube._visibilidade("unlisted") == "unlisted"


def test_youtube_publico_exige_opt_in(monkeypatch):
    from vexpublish.adapters import youtube

    with pytest.raises(VexPublishError) as erro:
        youtube._visibilidade("public")
    assert "ALLOW_PUBLIC" in erro.value.mensagem
    monkeypatch.setenv("VEXPUBLISH_YOUTUBE_ALLOW_PUBLIC", "true")
    assert youtube._visibilidade("public") == "public"


def test_youtube_visibilidade_invalida_e_recusada():
    from vexpublish.adapters import youtube

    with pytest.raises(VexPublishError):
        youtube._visibilidade("secreto")


def test_youtube_tags_aceitam_json_e_respeitam_teto():
    from vexpublish.adapters import youtube

    assert youtube._tags('["#gta6", "#shorts", "#gta6"]') == ["gta6", "shorts"]
    assert youtube._tags(["x" * 500, "gta"]) == []


def test_adapter_desconhecido_e_recusado():
    with pytest.raises(VexPublishError):
        adapters.obter("orkut")


def test_midia_inexistente_reprova(job):
    with pytest.raises(VexPublishError) as erro:
        base.validar_midia({**job, "media_path": "nao-existe.mp4"})
    assert erro.value.codigo == CodigoErro.VALIDATION_ERROR


def test_midia_vazia_reprova(job, tmp_path):
    vazio = tmp_path / "vazio.mp4"
    vazio.write_bytes(b"")
    with pytest.raises(VexPublishError):
        base.validar_midia({**job, "media_path": str(vazio)})


def test_youtube_exige_titulo(job, conta):
    with pytest.raises(VexPublishError):
        adapters.obter("youtube").validate({**job, "title": "  "}, conta)


def test_kwai_documenta_ordem_de_investigacao(job, conta):
    payload = adapters.obter("kwai").prepare(job, conta)
    assert payload["rota_pretendida"] == "api-oficial"


def test_modulo_desligado_bloqueia_execucao(job, conta):
    with pytest.raises(VexPublishError) as erro:
        base.executar(MockAdapter(), job, conta)
    assert erro.value.codigo == CodigoErro.VALIDATION_ERROR
    assert "VEXPUBLISH_ENABLED" in erro.value.mensagem


def test_plataforma_desligada_bloqueia_execucao(job, conta, monkeypatch):
    monkeypatch.setenv("VEXPUBLISH_ENABLED", "true")
    with pytest.raises(VexPublishError) as erro:
        base.executar(MockAdapter(), job, conta)
    assert "TIKTOK" in erro.value.mensagem


def test_dry_run_para_antes_do_publish(job, conta, monkeypatch):
    _ligar(monkeypatch, dry_run="true")
    adapter = MockAdapter()
    resultado = base.executar(adapter, job, conta)
    assert resultado["dry_run"] is True
    assert "publish" not in adapter.chamadas


def test_adapter_sem_evidencia_nao_conta_como_publicado(job, conta, monkeypatch):
    _ligar(monkeypatch, dry_run="false")

    class SemEvidencia(MockAdapter):
        def publish(self, job, conta, payload):
            self.chamadas.append("publish")
            return {}

    with pytest.raises(VexPublishError) as erro:
        base.executar(SemEvidencia(), {**job, "dry_run": 0}, conta)
    assert erro.value.codigo == CodigoErro.UPLOAD_FAILED


def test_sessao_fica_fora_do_repositorio(conta, tmp_path):
    sessao = vault.registrar(conta["id"], "tiktok")
    caminho = Path(sessao["storage_path"])
    assert caminho.exists()
    assert str(tmp_path) in str(caminho)


def test_captcha_exige_acao_humana(conta):
    with pytest.raises(VexPublishError) as erro:
        vault.exigir_acao_manual(conta["id"], "tiktok", "captcha")
    assert erro.value.codigo == CodigoErro.MANUAL_ACTION_REQUIRED
    assert vault.obter(conta["id"], "tiktok")["state"] == "manual_required"


def test_sessao_em_acao_manual_interrompe_execucao(job, conta, monkeypatch):
    _ligar(monkeypatch)
    vault.marcar(conta["id"], "tiktok", "manual_required")
    with pytest.raises(VexPublishError) as erro:
        base.executar(MockAdapter(), job, conta)
    assert erro.value.codigo == CodigoErro.MANUAL_ACTION_REQUIRED


def test_sessao_nunca_provada_passa_por_login(job, conta, monkeypatch):
    """Mesmo com o adapter dizendo 'valid', sessao no cofre como missing exige prova."""
    _ligar(monkeypatch)
    adapter = MockAdapter()  # check_session devolve 'valid'
    assert vault.registrar(conta["id"], "tiktok")["state"] == "missing"
    resultado = base.executar(adapter, job, conta)
    assert "login" in adapter.chamadas
    assert resultado["passos"] == ["check_session", "login", "validate", "prepare"]
    assert vault.obter(conta["id"], "tiktok")["state"] == "valid"


def test_sessao_ja_provada_nao_refaz_login(job, conta, monkeypatch):
    _ligar(monkeypatch)
    vault.marcar(conta["id"], "tiktok", "valid")
    adapter = MockAdapter()
    resultado = base.executar(adapter, job, conta)
    assert "login" not in adapter.chamadas
    assert resultado["passos"] == ["check_session", "validate", "prepare"]


def test_passos_relatados_sao_os_que_rodaram(job, conta, monkeypatch):
    """O log nao pode declarar passo que nao aconteceu."""
    _ligar(monkeypatch)
    vault.marcar(conta["id"], "tiktok", "valid")
    adapter = MockAdapter()
    resultado = base.executar(adapter, job, conta)
    assert resultado["passos"] == [x for x in adapter.chamadas if x in resultado["passos"]]
    assert "publish" not in resultado["passos"]


def test_sessao_ausente_dispara_login(job, conta, monkeypatch):
    _ligar(monkeypatch)

    class SemSessao(MockAdapter):
        def check_session(self, conta, sessao):
            self.chamadas.append("check_session")
            return "missing"

    adapter = SemSessao()
    base.executar(adapter, job, conta)
    assert "login" in adapter.chamadas


def test_login_nao_implementado_pede_login(conta):
    with pytest.raises(VexPublishError) as erro:
        adapters.obter("instagram").login(conta, {})
    assert erro.value.codigo == CodigoErro.LOGIN_REQUIRED
