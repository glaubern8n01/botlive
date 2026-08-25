"""Travas de recurso do vigia: colheita de orfaos e teto de threads.

Vem do incidente de 24/08/2026, em que a Hostinger ligou "Limitacao de CPU" na
VPS. O diagnostico achou tres coisas somadas: 56 processos zumbi, encode usando
todos os nucleos e um job de VOD rodando ha 28 horas.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clipper
import watcher


class TestTetoDeThreads(unittest.TestCase):
    def test_padrao_deixa_metade_da_maquina_livre(self):
        """os.cpu_count() entregava a maquina inteira para um encode."""
        with mock.patch.dict(os.environ, {"BOTLIVE_FFMPEG_THREADS": ""}, clear=False), \
             mock.patch.object(clipper.os, "cpu_count", return_value=4):
            self.assertEqual(2, clipper._threads_do_encode())

    def test_nunca_devolve_zero(self):
        with mock.patch.dict(os.environ, {"BOTLIVE_FFMPEG_THREADS": ""}, clear=False), \
             mock.patch.object(clipper.os, "cpu_count", return_value=1):
            self.assertEqual(1, clipper._threads_do_encode())

    def test_variavel_manda(self):
        with mock.patch.dict(os.environ, {"BOTLIVE_FFMPEG_THREADS": "3"}, clear=False):
            self.assertEqual(3, clipper._threads_do_encode())

    def test_variavel_invalida_cai_no_padrao(self):
        with mock.patch.dict(os.environ, {"BOTLIVE_FFMPEG_THREADS": "abacaxi"}, clear=False), \
             mock.patch.object(clipper.os, "cpu_count", return_value=8):
            self.assertEqual(4, clipper._threads_do_encode())


class TestColheitaDeOrfaos(unittest.TestCase):
    """O vigia e PID 1 no container: ffmpeg orfao de um subprocesso morto e
    re-parenteado para ele, e Python como PID 1 nao colhe nada sozinho."""

    def setUp(self):
        # waitid, P_ALL, WEXITED e WNOWAIT so existem em Unix; os testes rodam
        # no Windows do Glauber, entao entram por mock.
        for nome, valor in (("P_ALL", 0), ("WEXITED", 4), ("WNOWAIT", 0x1000000),
                            ("WNOHANG", 1)):
            patch = mock.patch.object(watcher.os, nome, valor, create=True)
            patch.start()
            self.addCleanup(patch.stop)

    def _vigia(self, vod=None, live=None):
        instancia = watcher.Vigia.__new__(watcher.Vigia)
        instancia._running_vod_jobs = vod or {}
        instancia._running_live_jobs = live or {}
        return instancia

    def _info(self, pid):
        return mock.Mock(si_pid=pid)

    def test_colhe_orfao_que_nao_e_nosso(self):
        vigia = self._vigia()
        with mock.patch.object(watcher.os, "waitid", create=True,
                               side_effect=[self._info(4242), ChildProcessError()]),              mock.patch.object(watcher.os, "waitpid", create=True) as colher:
            vigia._colher_orfaos()
        colher.assert_called_once_with(4242, 1)

    def test_nao_rouba_o_codigo_de_saida_de_job_em_voo(self):
        """Se o vigia colher um job dele, o poll() nunca mais retorna e o
        ledger fica preso em 'running' para sempre."""
        processo = mock.Mock(pid=777)
        vigia = self._vigia(vod={"s1": (processo, Path("x.log"), "sessao")})
        with mock.patch.object(watcher.os, "waitid", create=True,
                               return_value=self._info(777)),              mock.patch.object(watcher.os, "waitpid", create=True) as colher:
            vigia._colher_orfaos()
        colher.assert_not_called()

    def test_sem_filho_nenhum_sai_quieto(self):
        vigia = self._vigia()
        with mock.patch.object(watcher.os, "waitid", create=True,
                               side_effect=ChildProcessError()),              mock.patch.object(watcher.os, "waitpid", create=True) as colher:
            vigia._colher_orfaos()
        colher.assert_not_called()

    def test_no_windows_nao_tenta(self):
        vigia = self._vigia()
        with mock.patch.object(watcher, "os") as falso_os:
            del falso_os.waitid
            vigia._colher_orfaos()  # nao pode explodir


if __name__ == "__main__":
    unittest.main()
