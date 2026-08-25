"""Corte em duvida nao vai para as redes.

Motivo real: em 25/08/2026 quatro cortes de Counter-Strike 2 foram publicados
no canal "GTA6 Brasil cortes oficial", que e so de GTA. O filtro de nicho tinha
marcado todos como needs_review - fez o que devia -, mas corte em needs_review
subia assim mesmo, como unlisted. O canal e de um nicho so; nem rascunho de
outro jogo pode entrar.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import publisher


class TestNeedsReviewNaoPosta(unittest.TestCase):
    def test_corte_em_needs_review_e_barrado(self):
        with mock.patch.dict(os.environ, {"BOTLIVE_POSTAR_NEEDS_REVIEW": ""}, clear=False):
            caminho = Path("D:/robo/output/cortes/needs_review/corte_x.mp4")
            self.assertTrue(publisher._precisa_de_olho_humano(caminho))

    def test_corte_aprovado_passa(self):
        with mock.patch.dict(os.environ, {"BOTLIVE_POSTAR_NEEDS_REVIEW": ""}, clear=False):
            for pasta in ("ready", "ready_hd", "live_preview"):
                caminho = Path(f"D:/robo/output/cortes/{pasta}/corte_x.mp4")
                self.assertFalse(publisher._precisa_de_olho_humano(caminho), pasta)

    def test_da_para_voltar_ao_comportamento_antigo(self):
        with mock.patch.dict(os.environ, {"BOTLIVE_POSTAR_NEEDS_REVIEW": "1"}, clear=False):
            caminho = Path("D:/robo/output/cortes/needs_review/corte_x.mp4")
            self.assertFalse(publisher._precisa_de_olho_humano(caminho))

    def test_nome_de_arquivo_parecido_nao_engana(self):
        """So a PASTA decide - arquivo chamado 'needs_review_algo.mp4' dentro de
        ready continua sendo publicavel."""
        with mock.patch.dict(os.environ, {"BOTLIVE_POSTAR_NEEDS_REVIEW": ""}, clear=False):
            caminho = Path("D:/robo/output/cortes/ready/needs_review_algo.mp4")
            self.assertFalse(publisher._precisa_de_olho_humano(caminho))


if __name__ == "__main__":
    unittest.main()
