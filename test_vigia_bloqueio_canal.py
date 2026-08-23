"""A descoberta aberta nunca pode pegar um canal bloqueado.

Motivo real: bahiaqz entrou tres vezes pela descoberta (18, 20 e 22/08) e dois
cortes foram bloqueados globalmente por Content ID (Paramount, Rio Shore #407).
Desligar o canal em vigia_channels nao adiantava — aquilo so tirava da lista
manual, e a descoberta continuava pegando o mesmo streamer pela categoria.
"""

import os
import unittest
from unittest.mock import patch

import watcher
from watcher import Vigia, VigiaConfig


def _stream(login, stream_id, viewers=500, tags=None):
    return {"id": stream_id, "user_login": login, "viewer_count": viewers,
            "title": "GTA V RP", "tags": tags or ["Portugues"]}


class ApiFalsa:
    def __init__(self, streams):
        self.streams = streams

    def get_streams_by_game(self, *_args, **_kwargs):
        return self.streams

    def get_streams_by_logins(self, *_args, **_kwargs):
        return []


class BloqueioDeCanalTest(unittest.TestCase):
    def setUp(self):
        with patch.object(watcher, "TwitchHelix", lambda *a, **k: None):
            self.vigia = Vigia(dry_run=True)
        self.config = VigiaConfig(
            enabled=True, discovery_enabled=True, manual_channels_enabled=False,
            discovery_min_viewers=100, discovery_max_channels=3,
        )

    def _detectar(self, streams, bloqueados):
        self.vigia.api = ApiFalsa(streams)
        with patch.object(Vigia, "_canais_bloqueados", return_value=bloqueados):
            live_now, _ = self.vigia._detectar_lives(self.config)
        return {s["user_login"] for s in live_now.values()}

    def test_canal_bloqueado_fica_de_fora(self):
        pegos = self._detectar([_stream("bahiaqz", "1")], {"bahiaqz"})
        self.assertEqual(pegos, set())

    def test_bloqueio_nao_consome_vaga(self):
        """A vaga tem que sobrar para o proximo canal, senao 1 bloqueado
        derruba a colheita do ciclo inteiro."""
        streams = [_stream("bahiaqz", "1"), _stream("alanzoka", "2"), _stream("gaules", "3")]
        self.config = VigiaConfig(
            enabled=True, discovery_enabled=True, manual_channels_enabled=False,
            discovery_min_viewers=100, discovery_max_channels=2,
        )
        pegos = self._detectar(streams, {"bahiaqz"})
        self.assertEqual(pegos, {"alanzoka", "gaules"})

    def test_comparacao_ignora_maiuscula(self):
        pegos = self._detectar([_stream("BahiaQZ", "1")], {"bahiaqz"})
        self.assertEqual(pegos, set())

    def test_canal_liberado_continua_entrando(self):
        pegos = self._detectar([_stream("alanzoka", "2")], {"bahiaqz"})
        self.assertEqual(pegos, {"alanzoka"})


class ListaDeBloqueadosTest(unittest.TestCase):
    def setUp(self):
        with patch.object(watcher, "TwitchHelix", lambda *a, **k: None):
            self.vigia = Vigia(dry_run=True)

    def test_variavel_de_ambiente_entra_na_lista(self):
        with patch.dict(os.environ, {"BOTLIVE_CANAIS_BLOQUEADOS": " bahiaqz , Outro "}), \
             patch.object(Vigia, "_client", return_value=None):
            self.assertEqual(self.vigia._canais_bloqueados(), {"bahiaqz", "outro"})

    def test_sem_variavel_e_sem_banco_nao_bloqueia_ninguem(self):
        with patch.dict(os.environ, {"BOTLIVE_CANAIS_BLOQUEADOS": ""}), \
             patch.object(Vigia, "_client", return_value=None):
            self.assertEqual(self.vigia._canais_bloqueados(), set())

    def test_falha_de_leitura_mantem_o_ultimo_conjunto(self):
        """Esquecer um bloqueio por causa de erro de rede seria pior do que
        manter um bloqueio a mais por um ciclo."""
        self.vigia._bloqueados_cache = {"bahiaqz"}

        class ClienteQuebrado:
            def table(self, *_):
                raise RuntimeError("supabase fora do ar")

        with patch.dict(os.environ, {"BOTLIVE_CANAIS_BLOQUEADOS": ""}), \
             patch.object(Vigia, "_client", return_value=ClienteQuebrado()):
            self.assertEqual(self.vigia._canais_bloqueados(), {"bahiaqz"})


if __name__ == "__main__":
    unittest.main()
