"""Rodada sob demanda de uma campanha."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))

from app import rodada


class TestAcharCampanha(unittest.TestCase):
    def _campanhas(self):
        return [
            {"id": "aaa1", "name": "ViewX - Juninho Manella", "status": "draft"},
            {"id": "bbb2", "name": "Juninho Manella", "status": "active"},
            {"id": "ccc3", "name": "GabePeixe", "status": "active"},
        ]

    def test_ativa_ganha_do_rascunho_com_nome_parecido(self):
        """O catalogo tem dezenas de rascunhos "ViewX - Fulano" com o mesmo
        nome da campanha de verdade."""
        with mock.patch.object(rodada, "rows", return_value=self._campanhas()):
            self.assertEqual("bbb2", rodada.achar_campanha("juninho")["id"])

    def test_aceita_o_inicio_do_id(self):
        with mock.patch.object(rodada, "rows", return_value=self._campanhas()):
            self.assertEqual("ccc3", rodada.achar_campanha("ccc")["id"])

    def test_termo_que_nao_bate_para_com_recado(self):
        with mock.patch.object(rodada, "rows", return_value=self._campanhas()):
            with self.assertRaises(SystemExit):
                rodada.achar_campanha("nao-existe")


class TestCapturar(unittest.TestCase):
    def test_fonte_sem_novidade_nao_derruba_as_outras(self):
        fontes_ligadas = [
            {"id": "f1", "network": "kick", "url": "https://kick.com/x"},
            {"id": "f2", "network": "youtube", "url": "https://youtube.com/@y"},
        ]
        respostas = [
            {"materiais": [], "motivo": "nada novo na fonte"},
            {"materiais": [{"id": "m1", "name": "vod", "local_path": __file__}], "motivo": ""},
        ]
        with mock.patch.object(rodada, "rows", return_value=fontes_ligadas), \
             mock.patch.object(rodada.fontes, "buscar", side_effect=respostas):
            materiais = rodada.capturar({"id": "c1"}, lambda *a: None)
        self.assertEqual(["m1"], [m["id"] for m in materiais])


if __name__ == "__main__":
    unittest.main()
