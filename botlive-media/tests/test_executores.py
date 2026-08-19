"""Executores locais: geram arquivo de verdade, sem GPU, sem API, sem token.

Estes testes rodam o gerador real (nao mock) porque o ponto e justamente
provar que a capacidade existe nesta maquina. O de voz e pulado quando o
modelo nao esta baixado, para nao quebrar a suite em outro computador.
"""

import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mediastack.executors import imagem_local, voz_local


class ImagemTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.pasta = Path(tempfile.mkdtemp())

    def test_capa_vertical_sai_no_tamanho_do_reels(self):
        from PIL import Image

        alvo = imagem_local.Capa(
            titulo="Gol no ultimo minuto", subtitulo="corte da live", selo="futebol"
        ).render(self.pasta / "capa.jpg")
        self.assertTrue(alvo.is_file())
        with Image.open(alvo) as img:
            self.assertEqual((1080, 1920), img.size)

    def test_formato_horizontal_para_thumbnail_do_youtube(self):
        from PIL import Image

        alvo = imagem_local.Capa(titulo="Teste", formato="horizontal").render(
            self.pasta / "thumb.jpg"
        )
        with Image.open(alvo) as img:
            self.assertEqual((1280, 720), img.size)

    def test_formato_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            imagem_local.Capa(titulo="x", formato="redondo").render(self.pasta / "x.jpg")

    def test_card_de_produto_sem_foto_nao_inventa_foto(self):
        """Sem imagem de origem o card e grafico - nunca uma foto falsa."""
        alvo = imagem_local.CardProduto(
            titulo="Fone sem fio", preco="R$ 199,90", cta="Link na bio"
        ).render(self.pasta / "produto.jpg")
        self.assertTrue(alvo.is_file())
        self.assertNotIn("foto de produto inexistente", imagem_local.capacidades()["gera"])
        self.assertIn("foto de produto inexistente", imagem_local.capacidades()["nao_gera"])

    def test_titulo_longo_nao_estoura_a_imagem(self):
        from PIL import Image

        alvo = imagem_local.Capa(titulo="palavra " * 60).render(self.pasta / "longo.jpg")
        with Image.open(alvo) as img:
            self.assertEqual((1080, 1920), img.size)

    def test_declara_que_nao_usa_gpu_nem_custa(self):
        cap = imagem_local.capacidades()
        self.assertFalse(cap["gpu"])
        self.assertEqual(0.0, cap["custo"])
        self.assertEqual("local", cap["tier"])


class VozTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.pasta = Path(tempfile.mkdtemp())
        if not voz_local.vozes_disponiveis():
            self.skipTest("modelo de voz nao baixado nesta maquina")

    def test_gera_narracao_em_portugues(self):
        alvo = voz_local.Narracao("Olha esse lance decisivo no ultimo minuto.").render(
            self.pasta / "voz.wav"
        )
        self.assertTrue(alvo.is_file())
        self.assertGreater(voz_local.Narracao("x").duracao(alvo), 1.0)

    def test_texto_vazio_e_recusado(self):
        with self.assertRaises(ValueError):
            voz_local.Narracao("   ").render(self.pasta / "vazio.wav")

    def test_voz_inexistente_da_erro_claro(self):
        with self.assertRaises(FileNotFoundError) as erro:
            voz_local.Narracao("teste", voz="nao-existe").render(self.pasta / "x.wav")
        self.assertIn("Disponiveis", str(erro.exception))

    def test_declara_que_nao_clona_voz(self):
        cap = voz_local.capacidades()
        self.assertFalse(cap["gpu"])
        self.assertEqual(0.0, cap["custo"])
        self.assertIn("clonagem de voz", cap["nao_gera"])


if __name__ == "__main__":
    unittest.main()
