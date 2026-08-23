"""Seleção de corte pela fala — o método que dá dinheiro no mercado de cortes.

Nenhum teste transcreve de verdade: o whisper é substituído por falas de
mentira. O que se verifica é a regra de escolha.
"""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))
os.environ.setdefault("CAMPAIGNS_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "fala.db"))

from app import fala


@dataclass
class FalaFake:
    inicio: float
    fim: float
    texto: str


def conversa(inicio, fim, texto="palavra " * 30):
    """Um trecho falado com densidade normal de conversa."""
    return FalaFake(inicio, fim, texto.strip())


class SelecaoPorFalaTests(unittest.TestCase):
    def _detectar(self, falas, **kwargs):
        with mock.patch.object(fala, "_falas", return_value=falas):
            return fala.detectar("video.mp4", **kwargs)

    def test_material_sem_fala_devolve_vazio(self):
        """Gameplay mudo e clipe musical devem cair para o detector de movimento."""
        self.assertEqual([], self._detectar([]))

    def test_janela_curta_demais_e_descartada(self):
        curta = [conversa(0, 8)]
        self.assertEqual([], self._detectar(curta))

    def test_janela_respeita_o_teto_de_duracao(self):
        longa = [conversa(i * 10, i * 10 + 9) for i in range(20)]
        janelas = self._detectar(longa, janela_max=60)
        self.assertTrue(all(x["duracao"] <= 60.5 for x in janelas), [x["duracao"] for x in janelas])

    def test_fala_densa_pontua_mais_que_fala_rala(self):
        densa = [FalaFake(0, 20, "palavra " * 60)]
        rala = [FalaFake(100, 120, "ah e")]
        janelas = self._detectar(densa + rala, min_gap_seconds=1)
        por_inicio = {x["inicio"]: x["score"] for x in janelas}
        self.assertGreater(por_inicio[0.0], por_inicio[100.0])

    def test_gancho_na_abertura_soma_pontos(self):
        sem = [FalaFake(0, 20, "palavra " * 40)]
        com = [FalaFake(100, 120, "voce sabia que sao R$ 5 mil? " + "palavra " * 34)]
        janelas = self._detectar(sem + com, min_gap_seconds=1)
        por_inicio = {x["inicio"]: x for x in janelas}
        self.assertGreater(por_inicio[100.0]["score"], por_inicio[0.0]["score"])
        self.assertGreater(por_inicio[100.0]["ganchos"], 0)

    def test_janelas_escolhidas_nao_se_sobrepoem(self):
        falas = [conversa(i * 5, i * 5 + 4) for i in range(40)]
        janelas = self._detectar(falas, max_candidates=5, min_gap_seconds=45)
        centros = sorted(x["timestamp"] for x in janelas)
        for anterior, seguinte in zip(centros, centros[1:]):
            self.assertGreaterEqual(seguinte - anterior, 45)

    def test_respeita_o_maximo_de_candidatos(self):
        falas = [conversa(i * 5, i * 5 + 4) for i in range(100)]
        self.assertLessEqual(len(self._detectar(falas, max_candidates=3)), 3)

    def test_saida_traz_inicio_fim_e_o_texto_do_trecho(self):
        falas = [FalaFake(10, 35, "esse trecho aqui e o que vale " + "palavra " * 40)]
        janela = self._detectar(falas)[0]
        self.assertEqual(10.0, janela["inicio"])
        self.assertEqual(35.0, janela["fim"])
        self.assertIn("esse trecho aqui", janela["texto"])
        self.assertEqual("fala densa", janela["reason"].split(" com")[0])

    def test_saida_vem_em_ordem_cronologica(self):
        falas = [conversa(i * 60, i * 60 + 30) for i in range(5)]
        janelas = self._detectar(falas, max_candidates=5)
        self.assertEqual([x["inicio"] for x in janelas], sorted(x["inicio"] for x in janelas))

    def test_piso_de_score_corta_o_que_nao_presta(self):
        rala = [FalaFake(0, 40, "e ah entao")]
        self.assertEqual([], self._detectar(rala, min_score=0.5))


class AvaliadorPorModeloTests(unittest.TestCase):
    """O modelo é opcional: sem configuração, a heurística decide sozinha."""

    def setUp(self):
        for chave in ("CAMPAIGNS_LLM_URL", "CAMPAIGNS_LLM_KEY", "CAMPAIGNS_LLM_MODEL"):
            os.environ.pop(chave, None)
        self.janelas = [
            {"inicio": 0, "duracao": 20, "texto": "primeiro", "score": 0.9, "reason": "fala densa"},
            {"inicio": 60, "duracao": 20, "texto": "segundo", "score": 0.5, "reason": "fala densa"},
        ]

    def test_sem_url_configurada_nao_chama_rede(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("não deveria chamar")):
            self.assertEqual(self.janelas, fala.avaliar_com_llm(self.janelas, 2))

    def test_modelo_reordena_e_marca_o_motivo(self):
        os.environ["CAMPAIGNS_LLM_URL"] = "http://127.0.0.1:11434/v1/chat/completions"
        resposta = mock.MagicMock()
        resposta.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "Os melhores: [1, 0]"}}]}).encode()
        resposta.__enter__.return_value = resposta
        with mock.patch("urllib.request.urlopen", return_value=resposta):
            saida = fala.avaliar_com_llm(list(self.janelas), 2)
        self.assertEqual(60, saida[0]["inicio"])
        self.assertIn("escolhido pelo modelo", saida[0]["reason"])

    def test_modelo_fora_do_ar_cai_para_a_heuristica(self):
        os.environ["CAMPAIGNS_LLM_URL"] = "http://127.0.0.1:11434/v1/chat/completions"
        with mock.patch("urllib.request.urlopen", side_effect=OSError("recusou conexão")):
            saida = fala.avaliar_com_llm(list(self.janelas), 2)
        self.assertEqual(0, saida[0]["inicio"])
