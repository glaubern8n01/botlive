"""Fase 5: superficie HTTP do modulo de importacao."""

import os, sys, tempfile, unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("IMPORT_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "import-api.db"))
os.environ.setdefault("IMPORT_ADMIN_TOKEN", "admin-import")
os.environ.setdefault("IMPORT_REVIEWER_TOKEN", "reviewer-import")

from fastapi.testclient import TestClient

from importer import store
from importer.main import app

store.DB_PATH = Path(os.environ["IMPORT_DATABASE_PATH"])

ADMIN = {"X-Import-Token": "admin-import"}
LEITOR = {"X-Import-Token": "reviewer-import"}


def fonte(**extra):
    base = {
        "name": f"Fonte {store.uid()[:8]}",
        "kind": "local_folder",
        "authorized": True,
        "authorization_source": "Acordo por escrito",
        "license": "cc-by",
    }
    base.update(extra)
    return base


class ApiTests(unittest.TestCase):
    def setUp(self):
        store.migrar()
        self.client = TestClient(app)
        os.environ["IMPORT_ADAPT_PUBLISH_ENABLED"] = "true"
        self.pasta = Path(tempfile.mkdtemp())

    def tearDown(self):
        os.environ.pop("IMPORT_ADAPT_PUBLISH_ENABLED", None)

    def test_health_diz_que_nao_publica_direto(self):
        dados = self.client.get("/import/v1/health").json()
        self.assertFalse(dados["publica_direto"])
        self.assertFalse(dados["download_liberado"])

    def test_modulo_desligado_esconde_rotas(self):
        os.environ["IMPORT_ADAPT_PUBLISH_ENABLED"] = "false"
        self.assertEqual(404, self.client.get("/import/v1/sources", headers=ADMIN).status_code)

    def test_sem_token_nao_le(self):
        self.assertEqual(401, self.client.get("/import/v1/sources").status_code)

    def test_leitor_nao_cria_fonte(self):
        self.assertEqual(403, self.client.post("/import/v1/sources", headers=LEITOR, json=fonte()).status_code)

    def test_fonte_sem_autorizacao_volta_422_e_fica_na_auditoria(self):
        resposta = self.client.post("/import/v1/sources", headers=ADMIN, json=fonte(authorized=False))
        self.assertEqual(422, resposta.status_code)
        auditoria = self.client.get("/import/v1/audit", headers=ADMIN).json()["items"]
        self.assertTrue(any(x["action"] == "source.rejected" for x in auditoria))

    def test_fluxo_fonte_item_e_plano(self):
        criada = self.client.post("/import/v1/sources", headers=ADMIN, json=fonte(location=str(self.pasta)))
        self.assertEqual(201, criada.status_code)
        source_id = criada.json()["id"]

        video = self.pasta / "corte.mp4"
        video.write_bytes(b"conteudo")
        item = self.client.post(
            "/import/v1/items", headers=ADMIN, json={"source_id": source_id, "path": str(video)}
        )
        self.assertEqual(201, item.status_code)

        plano = self.client.post(
            "/import/v1/adaptations",
            headers=ADMIN,
            json={"item_id": item.json()["id"], "channel_id": "canal-1", "plan": {"title": "Oi"}},
        )
        self.assertEqual(201, plano.status_code)
        self.assertEqual("planned", plano.json()["status"])

    def test_validacao_de_plano_nao_grava_nada(self):
        antes = len(self.client.get("/import/v1/adaptations", headers=ADMIN).json()["items"])
        ok = self.client.post(
            "/import/v1/adaptations/validate", headers=ADMIN, json={"item_id": "x", "plan": {"layout": "vertical-crop"}}
        )
        self.assertEqual(200, ok.status_code)
        self.assertEqual("vertical-crop", ok.json()["plan"]["layout"])
        depois = len(self.client.get("/import/v1/adaptations", headers=ADMIN).json()["items"])
        self.assertEqual(antes, depois)

    def test_plano_de_apropriacao_volta_422(self):
        resposta = self.client.post(
            "/import/v1/adaptations/validate",
            headers=ADMIN,
            json={"item_id": "x", "plan": {"remove_watermark": True}},
        )
        self.assertEqual(422, resposta.status_code)
        self.assertIn("autoria", resposta.text)

    def test_lote_de_pasta_inexistente_volta_422(self):
        criada = self.client.post("/import/v1/sources", headers=ADMIN, json=fonte(location=str(self.pasta)))
        resposta = self.client.post(
            "/import/v1/batch", headers=ADMIN, json={"source_id": criada.json()["id"], "folder": "G:/nao/existe"}
        )
        self.assertEqual(422, resposta.status_code)


if __name__ == "__main__":
    unittest.main()
