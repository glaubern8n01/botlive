"""Selo obrigatorio dentro do corte (lower do GabePeixe, Kick do Juninho)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))

from app import rules, selo


class TestSelo(unittest.TestCase):
    def test_sem_config_nao_toca_no_arquivo(self):
        with mock.patch("subprocess.run") as run:
            resultado = selo.aplicar("/tmp/corte.mp4", {})
        run.assert_not_called()
        self.assertFalse(resultado["aplicado"])

    def test_imagem_ausente_trava_antes_de_publicar(self):
        """O lower do GabePeixe vem de uma pasta no Drive. Se ninguem baixou,
        o corte tem de travar - publicar sem lower e desclassificacao."""
        with self.assertRaises(FileNotFoundError):
            selo.aplicar("/tmp/corte.mp4", {"tipo": "imagem", "arquivo": "/nao/existe.png"})

    def test_texto_fica_no_corte_inteiro(self):
        filtro = selo.montar_filtro({"tipo": "texto", "texto": "kick.com/juninhomanella"})
        self.assertIn("drawtext", filtro)
        # Sem enable=between(...): o selo vale do primeiro ao ultimo quadro.
        self.assertNotIn("enable=", filtro)

    def test_dois_pontos_do_texto_vao_escapados(self):
        filtro = selo.montar_filtro({"tipo": "texto", "texto": "https://kick.com/x"})
        self.assertIn(r"https\://kick.com/x", filtro)

    def test_usa_a_fonte_do_botlive_e_nao_a_serifada_do_ffmpeg(self):
        filtro = selo.montar_filtro({"tipo": "texto", "texto": "kick.com/x"})
        self.assertIn("fontfile=", filtro)
        self.assertIn("Anton-Regular.ttf", filtro)

    def test_caminho_do_windows_vai_escapado_para_o_drawtext(self):
        """Sem escapar, o "G:" do caminho separa parametros do filtro e o
        drawtext le "G" como um valor solto."""
        barra = chr(92)
        caminho = f"G:{barra}botlive{barra}fonts{barra}Anton-Regular.ttf"
        filtro = selo.montar_filtro({"tipo": "texto", "texto": "x", "fonte": caminho})
        self.assertIn(r"G\:/botlive/fonts/Anton-Regular.ttf", filtro)

    def test_texto_tem_caixa_atras_para_ficar_legivel(self):
        filtro = selo.montar_filtro({"tipo": "texto", "texto": "x"})
        self.assertIn("box=1", filtro)

    def test_selo_de_texto_sem_texto_e_erro_de_cadastro(self):
        with self.assertRaises(ValueError):
            selo.montar_filtro({"tipo": "texto", "texto": "   "})

    def test_audio_e_copiado_sem_recodificar(self):
        arquivo = Path(__file__).parent / "_lower.png"
        arquivo.write_bytes(b"x")
        try:
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stderr="")), \
                 mock.patch("pathlib.Path.exists", return_value=True), \
                 mock.patch("shutil.move") as mover:
                selo.aplicar("/tmp/corte.mp4", {"tipo": "imagem", "arquivo": str(arquivo)})
            mover.assert_called_once()
        finally:
            arquivo.unlink(missing_ok=True)


class TestRegraDoSelo(unittest.TestCase):
    def _campanha(self, exige):
        return {"rules": {"selo": {"tipo": "texto", "texto": "kick"}} if exige else {},
                "hashtags": [], "mentions": []}

    def test_campanha_que_exige_selo_bloqueia_sem_ele(self):
        check = rules._selo(self._campanha(True), {"selo": {"aplicado": False}})
        self.assertEqual("rejected", check["status"])
        self.assertEqual("critical", check["severity"])

    def test_campanha_que_exige_selo_passa_com_ele(self):
        check = rules._selo(self._campanha(True), {"selo": {"aplicado": True}})
        self.assertEqual("approved", check["status"])

    def test_campanha_sem_selo_nao_e_incomodada(self):
        check = rules._selo(self._campanha(False), {})
        self.assertEqual("approved", check["status"])
        self.assertEqual("warning", check["severity"])




class TestConferirAntesDeRenderizar(unittest.TestCase):
    """Sem esta conferencia o corte era renderizado inteiro - minutos de CPU -
    so para morrer no passo do selo, e ainda tres vezes por causa das
    tentativas do job. Aconteceu com o GabePeixe."""

    def test_campanha_sem_selo_passa_direto(self):
        selo.conferir({})

    def test_imagem_ausente_reprova_antes_do_render(self):
        with self.assertRaises(FileNotFoundError):
            selo.conferir({"tipo": "imagem", "arquivo": "/data/agents/selos/nao-existe.png"})

    def test_texto_invalido_reprova_antes_do_render(self):
        with self.assertRaises(ValueError):
            selo.conferir({"tipo": "texto", "texto": "  "})

    def test_selo_da_vps_e_encontrado_na_pasta_desta_maquina(self):
        """A campanha e cadastrada na VPS e guarda o caminho de la; quem
        renderiza e o PC, onde esse caminho nao existe."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            (Path(pasta) / "gabepeixe-lower.png").write_bytes(b"x")
            with mock.patch.dict(os.environ, {"CAMPAIGNS_SELOS_DIR": pasta}, clear=False):
                achado = selo.achar_arquivo("/data/agents/selos/gabepeixe-lower.png")
                self.assertIsNotNone(achado)
                self.assertEqual("gabepeixe-lower.png", achado.name)
                selo.conferir({"tipo": "imagem", "arquivo": "/data/agents/selos/gabepeixe-lower.png"})


if __name__ == "__main__":
    unittest.main()
