"""VOD processado no PC: montagem do comando e escolha da fila.

O comando do vod-clips passou a ser montado por uma funcao so, usada pelo vigia
da VPS e pelo runner do PC. Estes testes travam o contrato: se alguem mexer nos
argumentos de um lado, o outro nao fica para tras em silencio.
"""

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

    def test_estado_proprio_nao_colide_com_a_varredura_de_orfaos(self):
        """O vigia da VPS marca como failed toda linha em 'running' quando
        reinicia. Um job saudavel aqui nao pode cair nessa rede."""
        import vod_pc
        self.assertNotEqual("running", vod_pc.EM_ANDAMENTO)


if __name__ == "__main__":
    unittest.main()
