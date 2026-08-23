"""O guarda de nicho tem que barrar o UPLOAD, nao so gerar um aviso.

Cobre o ponto unico de postagem no YouTube. Nenhum destes testes toca a rede:
se o guarda falhar em barrar, _upload seria chamado — e o mock acusa.
"""

import os
import unittest
from unittest.mock import patch

import yt_publisher


FUTEBOL = (
    "No EVA, comecou o campeonato, esta jogando de muleta! Que bolao! "
    "Demite o tecnico! Demite ele!"
)
GTA = "A policia chegou no assalto e o advogado me tirou da cadeia."


class ConfigFalsa:
    dry_run = False
    conta = "principal"
    visibilidade = "unlisted"


def _registro(transcricao, tmp):
    return {
        "corte": "corte_x.mp4",
        "horizontal": str(tmp / "h.mp4"),
        "vertical": str(tmp / "v.mp4"),
        "legenda": "Titulo do corte",
        "hashtags": ["#gta"],
        "nicho": "gta",
        "transcricao": transcricao,
    }


class GuardaNoPostTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        for nome in ("h.mp4", "v.mp4"):
            (self.tmp / nome).write_bytes(b"video")

    def test_conteudo_de_futebol_nao_sobe(self):
        with patch.object(yt_publisher, "_upload") as upload:
            r = yt_publisher.postar_corte_registro(_registro(FUTEBOL, self.tmp), ConfigFalsa())
        upload.assert_not_called()
        self.assertTrue(r["bloqueado_por_nicho"])
        self.assertIn("pulado", r["horizontal"])
        self.assertIn("pulado", r["vertical"])

    def test_gameplay_de_gta_sobe_normal(self):
        with patch.object(yt_publisher, "_upload", return_value={"video_id": "abc", "url": "u"}) as upload:
            r = yt_publisher.postar_corte_registro(_registro(GTA, self.tmp), ConfigFalsa())
        self.assertEqual(upload.call_count, 2)
        self.assertNotIn("bloqueado_por_nicho", r)
        self.assertEqual(r["vertical"]["video_id"], "abc")

    def test_bloqueio_nao_e_reportado_como_erro_de_upload(self):
        """Se virasse erro, o vigia trataria como falha e ficaria retentando."""
        with patch.object(yt_publisher, "_upload"):
            r = yt_publisher.postar_corte_registro(_registro(FUTEBOL, self.tmp), ConfigFalsa())
        self.assertIsNone(r["erro"])

    def test_kill_switch_desliga_o_guarda(self):
        with patch.dict(os.environ, {"BOTLIVE_GUARDA_NICHO": "0"}), \
             patch.object(yt_publisher, "_upload", return_value={"video_id": "x", "url": "u"}) as upload:
            yt_publisher.postar_corte_registro(_registro(FUTEBOL, self.tmp), ConfigFalsa())
        self.assertEqual(upload.call_count, 2, "com o guarda desligado, sobe como antes")

    def test_guarda_ausente_nao_derruba_a_postagem(self):
        """Se nicho_guard sumir da imagem, o post continua — nunca o contrario."""
        import builtins
        real = builtins.__import__

        def sem_guarda(nome, *a, **k):
            if nome == "nicho_guard":
                raise ImportError("modulo ausente")
            return real(nome, *a, **k)

        with patch.object(builtins, "__import__", sem_guarda), \
             patch.object(yt_publisher, "_upload", return_value={"video_id": "x", "url": "u"}) as upload:
            yt_publisher.postar_corte_registro(_registro(FUTEBOL, self.tmp), ConfigFalsa())
        self.assertEqual(upload.call_count, 2)

    def test_dry_run_tambem_respeita_o_guarda(self):
        class Seco(ConfigFalsa):
            dry_run = True

        with patch.object(yt_publisher, "_upload") as upload:
            r = yt_publisher.postar_corte_registro(_registro(FUTEBOL, self.tmp), Seco())
        upload.assert_not_called()
        self.assertTrue(r["bloqueado_por_nicho"])


if __name__ == "__main__":
    unittest.main()
