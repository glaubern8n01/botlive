"""Sincronia do cadastro de campanhas entre a VPS e o PC."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))

from app import sincronizar, store


class TestSincronizar(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        caminho = Path(self.pasta.name) / "local.db"
        patch = mock.patch.object(store, "DB_PATH", caminho)
        patch.start()
        self.addCleanup(patch.stop)
        store.migrate()

    def _dados(self, nome="Juninho Manella", url="https://kick.com/juninhomanella"):
        return {
            "campaign_campaigns": [{
                "id": "camp-1", "platform": "viewx", "name": nome, "status": "active",
                "rules": "{}", "hashtags": '["#juninhomanella"]', "mentions": "[]",
                "networks": "[]", "created_at": store.now(), "updated_at": store.now(),
            }],
            "campaign_sources": [{
                "id": "src-1", "campaign_id": "camp-1", "network": "kick", "url": url,
                "authorization_source": "regra da campanha", "created_at": store.now(),
            }],
        }

    def test_traz_campanha_e_fonte_com_os_mesmos_ids(self):
        """Id igual dos dois lados: senao PC e VPS falam de campanhas
        diferentes com o mesmo nome."""
        resumo = sincronizar.importar(self._dados())
        self.assertEqual(2, resumo["criados"])
        self.assertEqual("Juninho Manella", store.get("campaign_campaigns", "camp-1")["name"])
        self.assertEqual("kick", store.get("campaign_sources", "src-1")["network"])

    def test_rodar_de_novo_atualiza_em_vez_de_duplicar(self):
        sincronizar.importar(self._dados())
        resumo = sincronizar.importar(self._dados(nome="Juninho Manella 2"))
        self.assertEqual(0, resumo["criados"])
        self.assertEqual(2, resumo["atualizados"])
        self.assertEqual("Juninho Manella 2", store.get("campaign_campaigns", "camp-1")["name"])
        self.assertEqual(1, len(store.rows("campaign_campaigns", 50, 0)))

    def test_coluna_que_so_existe_na_vps_nao_derruba_a_sincronia(self):
        dados = self._dados()
        dados["campaign_sources"][0]["coluna_do_futuro"] = "x"
        resumo = sincronizar.importar(dados)
        self.assertEqual(2, resumo["criados"])

    def test_campanha_apagada_na_vps_permanece_no_pc(self):
        """Pode haver corte local pendurado nela; apagar levaria o material."""
        sincronizar.importar(self._dados())
        sincronizar.importar({"campaign_campaigns": [], "campaign_sources": []})
        self.assertIsNotNone(store.get("campaign_campaigns", "camp-1"))

    def test_exportar_devolve_o_que_importar_entende(self):
        sincronizar.importar(self._dados())
        foto = sincronizar.exportar()
        self.assertEqual(1, len(foto["campaign_campaigns"]))
        json.dumps(foto)  # tem de ser serializavel para atravessar o ssh


if __name__ == "__main__":
    unittest.main()
