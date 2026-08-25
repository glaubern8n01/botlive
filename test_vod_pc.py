"""VOD processado no PC: montagem do comando e escolha da fila.

O comando do vod-clips passou a ser montado por uma funcao so, usada pelo vigia
da VPS e pelo runner do PC. Estes testes travam o contrato: se alguem mexer nos
argumentos de um lado, o outro nao fica para tras em silencio.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "ops" / "local"))

from watcher import VigiaConfig, montar_comando_vod  # noqa: E402


def _config(**extra):
    base = dict(content_filter="gta", max_cortes_vod=3, clip_duration_seconds=60,
                target_height=720, dedup_window_seconds=60, post_visibilidade="unlisted",
                credito_streamer=None, credito_canal="@GTA6brasilcortesoficial")
    base.update(extra)
    return VigiaConfig(**base)


def _linha():
    return {"stream_id": "318700952310", "channel_login": "moitaofc"}


class TestComandoDoVod(unittest.TestCase):
    def test_argumentos_essenciais(self):
        comando = montar_comando_vod(_config(), _linha(), "https://twitch.tv/videos/1", False)
        self.assertIn("--modo", comando)
        self.assertEqual("vod-clips", comando[comando.index("--modo") + 1])
        self.assertEqual("vigia_318700952310_vod", comando[comando.index("--session-id") + 1])
        self.assertEqual("gta", comando[comando.index("--content-filter") + 1])
        self.assertIn("--publish-vertical", comando)

    def test_dedup_leva_o_stream_id(self):
        """V6: sem isto o VOD recorta o que a live ja cortou."""
        comando = montar_comando_vod(_config(), _linha(), "https://twitch.tv/videos/1", False)
        self.assertEqual("318700952310", comando[comando.index("--dedup-stream-id") + 1])

    def test_sem_postar_nao_manda_post_youtube(self):
        comando = montar_comando_vod(_config(), _linha(), "https://twitch.tv/videos/1", False)
        self.assertNotIn("--post-youtube", comando)

    def test_postando_manda_visibilidade_e_conta(self):
        comando = montar_comando_vod(_config(), _linha(), "https://twitch.tv/videos/1", True)
        self.assertIn("--post-youtube", comando)
        self.assertEqual("unlisted", comando[comando.index("--post-visibilidade") + 1])
        self.assertEqual("principal", comando[comando.index("--post-conta") + 1])

    def test_credito_cai_no_canal_quando_nao_configurado(self):
        comando = montar_comando_vod(_config(), _linha(), "https://twitch.tv/videos/1", False)
        self.assertEqual("@moitaofc", comando[comando.index("--credito-streamer") + 1])

    def test_credito_configurado_ganha(self):
        comando = montar_comando_vod(_config(credito_streamer="@outro"), _linha(),
                                     "https://twitch.tv/videos/1", False)
        self.assertEqual("@outro", comando[comando.index("--credito-streamer") + 1])


class TestFilaDoPc(unittest.TestCase):
    def _linhas(self, minutos_atras, dry=False):
        fim = datetime.now(timezone.utc) - timedelta(minutes=minutos_atras)
        return [{"stream_id": "1", "channel_login": "x", "ended_at": fim.isoformat(),
                 "dry_run": dry}]

    def _client(self, linhas):
        client = mock.MagicMock()
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = linhas
        return client

    def test_espera_o_vod_aparecer_na_twitch(self):
        """A Twitch demora a publicar o VOD; pegar cedo demais e tentativa
        perdida - o vigia sempre respeitou essa espera."""
        import vod_pc
        config = _config(vod_delay_minutes=15)
        self.assertEqual([], vod_pc.pendentes(self._client(self._linhas(5)), config))
        self.assertEqual(1, len(vod_pc.pendentes(self._client(self._linhas(20)), config)))

    def test_linha_de_teste_nao_e_processada(self):
        import vod_pc
        config = _config(vod_delay_minutes=15)
        self.assertEqual([], vod_pc.pendentes(self._client(self._linhas(60, dry=True)), config))

    def test_sem_ended_at_nao_entra(self):
        import vod_pc
        client = self._client([{"stream_id": "1", "channel_login": "x", "dry_run": False}])
        self.assertEqual([], vod_pc.pendentes(client, _config(vod_delay_minutes=15)))

    def test_a_posse_do_pc_e_reconhecivel(self):
        """A coluna vod_job_status tem CHECK no banco e recusa valor inventado,
        entao o estado e o "running" de sempre; quem diz que o job e deste PC e
        a marca no error_message."""
        import vod_pc
        self.assertEqual("running", vod_pc.EM_ANDAMENTO)
        self.assertTrue(vod_pc._marca_de_posse().startswith(vod_pc.MARCA_DO_PC))


if __name__ == "__main__":
    unittest.main()


class TestReivindicacaoAtomica(unittest.TestCase):
    """Sem o filtro por estado no UPDATE, dois PCs liam a mesma linha, os dois
    a marcavam como sua e o mesmo VOD saia cortado e postado duas vezes."""

    def _client(self, ganhou: bool):
        client = mock.MagicMock()
        cadeia = client.table.return_value.update.return_value.eq.return_value.eq.return_value
        cadeia.execute.return_value.data = [{"stream_id": "1"}] if ganhou else []
        return client

    def _rodar(self, client):
        import vod_pc
        linha = {"stream_id": "1", "channel_login": "x", "vod_attempts": 0}
        with mock.patch.object(vod_pc, "achar_vod", return_value="https://twitch.tv/videos/1"), \
             mock.patch.object(vod_pc, "pode_postar", return_value=False), \
             mock.patch.object(vod_pc.subprocess, "run") as rodou:
            resultado = vod_pc.processar(client, _config(post_youtube_enabled=False),
                                         linha, lambda *a: None)
        return resultado, rodou

    def test_quem_perde_a_disputa_nao_processa(self):
        resultado, rodou = self._rodar(self._client(ganhou=False))
        self.assertFalse(resultado)
        rodou.assert_not_called()

    def test_quem_ganha_processa(self):
        _resultado, rodou = self._rodar(self._client(ganhou=True))
        rodou.assert_called_once()

    def test_o_update_filtra_pelo_estado_esperado(self):
        client = self._client(ganhou=True)
        self._rodar(client)
        primeiro = client.table.return_value.update.return_value.eq
        segundo = primeiro.return_value.eq
        self.assertEqual(("stream_id", "1"), primeiro.call_args.args)
        self.assertEqual(("vod_job_status", "waiting_vod"), segundo.call_args.args)

class TestRecuperarJobPerdido(unittest.TestCase):
    """Se o PC desliga no meio de um VOD, a linha nao pode ficar presa em
    running_pc para sempre - nem o VOD ser cortado duas vezes."""

    def _linha(self, horas_atras):
        quando = datetime.now(timezone.utc) - timedelta(hours=horas_atras)
        return {"stream_id": "1", "error_message": f"running_pc@PC-DO-GLAUBER|{quando.isoformat()}"}

    def _client(self, linhas):
        client = mock.MagicMock()
        cadeia = client.table.return_value.select.return_value.eq.return_value.like.return_value
        cadeia.execute.return_value.data = linhas
        return client

    def test_job_recente_e_deixado_em_paz(self):
        import vod_pc
        self.assertEqual([], vod_pc.abandonados(self._client([self._linha(1)])))

    def test_job_sem_sinal_ha_horas_volta_para_a_fila(self):
        import vod_pc
        perdidos = vod_pc.abandonados(self._client([self._linha(9)]))
        self.assertEqual(1, len(perdidos))

    def test_volta_para_waiting_vod_e_nao_para_failed(self):
        """failed nunca mais e redespachado; o VOD ficaria perdido."""
        import vod_pc
        client = self._client([self._linha(9)])
        alvo = client.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value
        alvo.execute.return_value.data = [{}]
        vod_pc.devolver_abandonados(client, lambda *a: None)
        patch = client.table.return_value.update.call_args.args[0]
        self.assertEqual("waiting_vod", patch["vod_job_status"])

    def test_carimbo_ilegivel_nao_e_tocado(self):
        """Mexer numa linha que nao da para julgar poderia reprocessar um VOD
        que esta sendo cortado agora."""
        import vod_pc
        self.assertEqual([], vod_pc.abandonados(self._client([{"stream_id": "1",
                                                               "error_message": "sei la"}])))

    def test_marca_de_posse_tem_maquina_e_hora(self):
        import vod_pc
        marca = vod_pc._marca_de_posse()
        self.assertTrue(marca.startswith("running_pc@"))
        self.assertIsNotNone(vod_pc.visto_em({"error_message": marca}))


class TestAmbienteDoFilho(unittest.TestCase):
    """O main.py roda como outro processo: o remendo de TLS aplicado no
    vod_pc.py nao vale la. Sem isto, o VOD escolhia os cortes e morria no fim
    em CERTIFICATE_VERIFY_FAILED, jogando fora todo o trabalho."""

    def test_pyenv_entra_no_pythonpath(self):
        import vod_pc
        with mock.patch.object(vod_pc.Path, "is_dir", return_value=True), \
             mock.patch.dict(os.environ, {"BOTLIVE_PYENV": "X:/remendo", "PYTHONPATH": ""}, clear=False):
            self.assertTrue(vod_pc.ambiente_do_filho()["PYTHONPATH"].startswith("X:/remendo"))

    def test_pythonpath_existente_e_preservado(self):
        import vod_pc
        with mock.patch.object(vod_pc.Path, "is_dir", return_value=True), \
             mock.patch.dict(os.environ, {"BOTLIVE_PYENV": "X:/remendo", "PYTHONPATH": "Y:/antes"}, clear=False):
            caminho = vod_pc.ambiente_do_filho()["PYTHONPATH"]
        self.assertIn("X:/remendo", caminho)
        self.assertIn("Y:/antes", caminho)

    def test_ssl_cert_file_e_removido(self):
        """Apontar para um pacote com a CA do AVG nao resolve - o OpenSSL
        recusa o formato dela - e ainda atrapalha o truststore."""
        import vod_pc
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "C:/x.pem"}, clear=False):
            self.assertNotIn("SSL_CERT_FILE", vod_pc.ambiente_do_filho())


class TestLimpezaDeCache(unittest.TestCase):
    """Na VPS quem limpa o cache e o vigia, depois de colher o job. Aqui quem
    despacha e o runner, e o vigia nunca ve o job: sem limpeza, cada VOD deixa
    ~18 GB e a fila de 58 enche o disco na madrugada."""

    def test_apaga_so_a_pasta_da_sessao(self):
        import shutil
        import tempfile
        import vod_pc
        with tempfile.TemporaryDirectory() as raiz:
            base = Path(raiz) / "vod_blocks"
            minha = base / "vigia_123_vod"
            vizinha = base / "vigia_999_vod"
            for pasta in (minha, vizinha):
                pasta.mkdir(parents=True)
                (pasta / "bloco.mp4").write_bytes(b"x" * 100)
            with mock.patch.object(vod_pc, "Path", Path), \
                 mock.patch.dict("sys.modules", {"runtime_paths": mock.Mock(
                     vod_blocks_dir=lambda: base, live_blocks_dir=lambda: base)}):
                vod_pc.limpar_cache("vigia_123_vod", lambda *a: None)
            self.assertFalse(minha.exists())
            self.assertTrue(vizinha.exists(), "cache de outro job nao pode ser tocado")

    def test_falha_na_limpeza_nao_derruba_nada(self):
        import vod_pc
        with mock.patch.dict("sys.modules", {"runtime_paths": None}):
            vod_pc.limpar_cache("vigia_1_vod", lambda *a: None)  # nao pode levantar
