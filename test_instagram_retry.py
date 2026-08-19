"""Retry do upload de Reel dentro do proprio job.

Producao mostrou 3 cortes gastando 16 tentativas: cada falha do rupload
queimava um ciclo inteiro do vigia, porque nao havia retry aqui dentro.
Estes testes travam o comportamento novo sem tocar na rede.
"""

import unittest
from pathlib import Path
from unittest import mock

import instagram_publisher as ig


CREDENCIAIS = {
    "access_token": "token-falso",
    "ig_user_id": "17841400000000000",
    "api_host": "graph.facebook.com",
}


class RetryUploadTests(unittest.TestCase):
    def setUp(self):
        self.containers = []
        self.dormidas = []

    def _rodar(self, falhas: int, tentativas_max: int = 5):
        """Simula `falhas` erros de rupload antes do sucesso."""
        self.chamadas = {"upload": 0}

        def post_form(url, params):
            if url.endswith("/media"):
                self.containers.append(f"container-{len(self.containers) + 1}")
                return {"id": self.containers[-1]}
            return {"id": "media-publicada"}

        def upload(container_id, video_path, token):
            self.chamadas["upload"] += 1
            if self.chamadas["upload"] <= falhas:
                raise RuntimeError(
                    'rupload HTTP 400: {"debug_info":{"retriable":false,'
                    '"type":"ProcessingFailedError"}}'
                )

        with mock.patch.object(ig, "_UPLOAD_TENTATIVAS", tentativas_max), \
             mock.patch.object(ig, "_UPLOAD_ESPERA_BASE", 1), \
             mock.patch.object(ig, "_UPLOAD_ESPERA_MAX", 4), \
             mock.patch.object(ig, "_credenciais", return_value=CREDENCIAIS), \
             mock.patch.object(ig, "montar_post", return_value={"media_type": "REELS"}), \
             mock.patch.object(ig, "_post_form", side_effect=post_form), \
             mock.patch.object(ig, "_upload_binario", side_effect=upload), \
             mock.patch.object(ig, "_get", return_value={"status_code": "FINISHED", "permalink": "https://x"}), \
             mock.patch.object(ig.time, "sleep", side_effect=self.dormidas.append):
            return ig._publicar_reel({}, Path("corte.mp4"), "principal")

    def test_sucesso_de_primeira_nao_repete(self):
        resultado = self._rodar(falhas=0)
        self.assertEqual("media-publicada", resultado["media_id"])
        self.assertEqual(1, len(self.containers))
        self.assertEqual([], self.dormidas)

    def test_falha_transitoria_e_superada_no_mesmo_job(self):
        """O caso real de producao: falha algumas vezes e publica."""
        resultado = self._rodar(falhas=4)
        self.assertEqual("media-publicada", resultado["media_id"])
        self.assertEqual(5, self.chamadas["upload"])
        # Container novo por tentativa: e o caminho que producao ja comprovava.
        self.assertEqual(5, len(self.containers))

    def test_espera_cresce_entre_tentativas(self):
        self._rodar(falhas=3)
        self.assertEqual([1, 2, 4], self.dormidas)

    def test_espera_respeita_o_teto(self):
        self._rodar(falhas=4)
        self.assertTrue(all(x <= 4 for x in self.dormidas), self.dormidas)

    def test_desiste_depois_do_limite_e_propaga_o_erro(self):
        with self.assertRaises(RuntimeError) as erro:
            self._rodar(falhas=99, tentativas_max=3)
        self.assertIn("rupload HTTP 400", str(erro.exception))
        self.assertEqual(3, len(self.containers))
        # Ultima tentativa nao dorme por nada.
        self.assertEqual(2, len(self.dormidas))

    def test_limite_vem_do_ambiente(self):
        import os

        with mock.patch.dict(os.environ, {"BOTLIVE_IG_UPLOAD_TENTATIVAS": "9"}):
            import importlib

            recarregado = importlib.reload(ig)
            try:
                self.assertEqual(9, recarregado._UPLOAD_TENTATIVAS)
            finally:
                importlib.reload(recarregado)


if __name__ == "__main__":
    unittest.main()
