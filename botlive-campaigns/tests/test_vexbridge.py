"""Fase 3: ponte Campanhas -> VexPublish e registro de metricas.

A ponte nao publica nada: ela cria um PublishJob em draft, com dry-run e
aprovacao obrigatoria. Toda barreira que impede o enfileiramento tem teste.
"""

import os, sys, tempfile, unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("CAMPAIGNS_DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "bridge.db"))
os.environ.setdefault("CAMPAIGNS_LOCAL_TOKEN", "admin-secret")
os.environ.setdefault("CAMPAIGNS_OPERATOR_TOKEN", "operator-secret")
os.environ.setdefault("CAMPAIGNS_REVIEWER_TOKEN", "reviewer-secret")
os.environ.setdefault("CAMPAIGNS_ENABLED", "true")
os.environ["VEXPUBLISH_DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "vexpublish.db")

from fastapi.testclient import TestClient

from app import store, vexbridge
from app.main import app

from vexpublish.core import models as vexmodels
from vexpublish.core import store as vexstore

# DB_PATH e resolvido no import do modulo: se outra suite importar o store
# antes desta, a variavel de ambiente acima chega tarde demais. Fixamos o
# caminho aqui para que o teste nunca escreva no banco real do VexPublish.
vexstore.DB_PATH = Path(os.environ["VEXPUBLISH_DATABASE_PATH"])


class PonteTests(unittest.TestCase):
    def setUp(self):
        store.migrate()
        vexstore.migrar()
        with store.connect() as db:
            db.execute("DELETE FROM campaign_channels")
        os.environ["CAMPAIGNS_VEXPUBLISH_ENABLED"] = "true"
        self.saida = Path(tempfile.mkdtemp()) / "corte.mp4"
        self.saida.write_bytes(b"video")
        stamp = store.now()
        self.campanha = store.insert(
            "campaign_campaigns",
            {
                "platform": "manual",
                "name": "Campanha ponte",
                "automation_policy": "assisted",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        self.canal = store.insert(
            "campaign_channels",
            {"network": "tiktok", "handle": "@perfil_ponte", "created_at": stamp},
        )
        self.candidato = {
            "id": "cand-1",
            "status": "approved",
            "checklist_status": "warning",
            "output_path": str(self.saida),
            "caption": "legenda",
            "hook": "gancho",
        }
        self.publicacao = {"description": "descricao", "hashtags": '["#gta6"]'}

    def tearDown(self):
        os.environ.pop("CAMPAIGNS_VEXPUBLISH_ENABLED", None)

    def _conta_vexpublish(self, handle="@perfil_ponte"):
        canal = vexmodels.Channel(name=f"Marca {handle}", platforms=["tiktok"]).salvar()
        registro = vexmodels.Account(
            channel_id=canal["id"], platform="tiktok", handle=handle, status="active"
        ).salvar()
        return vexstore.obter("vexpublish_accounts", registro["id"])

    def _enfileirar(self):
        return vexbridge.enfileirar(self.publicacao, self.candidato, self.campanha, self.canal)

    def test_ponte_desligada_recusa(self):
        os.environ["CAMPAIGNS_VEXPUBLISH_ENABLED"] = "false"
        with self.assertRaises(vexbridge.BridgeError) as erro:
            self._enfileirar()
        self.assertIn("CAMPAIGNS_VEXPUBLISH_ENABLED", str(erro.exception))

    def test_campanha_manual_only_recusa(self):
        self.campanha["automation_policy"] = "manual-only"
        with self.assertRaises(vexbridge.BridgeError) as erro:
            self._enfileirar()
        self.assertIn("manual-only", str(erro.exception))

    def test_candidato_sem_aprovacao_recusa(self):
        self.candidato["status"] = "review"
        with self.assertRaises(vexbridge.BridgeError):
            self._enfileirar()

    def test_candidato_bloqueado_recusa(self):
        self.candidato["checklist_status"] = "blocked"
        with self.assertRaises(vexbridge.BridgeError):
            self._enfileirar()

    def test_sem_canal_recusa(self):
        self.canal = None
        with self.assertRaises(vexbridge.BridgeError):
            self._enfileirar()

    def test_arquivo_ausente_recusa(self):
        self.candidato["output_path"] = str(self.saida) + ".sumiu"
        with self.assertRaises(vexbridge.BridgeError):
            self._enfileirar()

    def test_conta_nao_cadastrada_no_vexpublish_recusa(self):
        with self.assertRaises(vexbridge.BridgeError) as erro:
            self._enfileirar()
        self.assertIn("nao existe no VexPublish", str(erro.exception))

    def test_job_nasce_em_draft_dry_run_e_com_aprovacao(self):
        conta = self._conta_vexpublish()
        resultado = self._enfileirar()
        self.assertEqual("draft", resultado["status"])
        self.assertTrue(resultado["dry_run"])
        self.assertTrue(resultado["requires_approval"])
        self.assertEqual("tiktok", resultado["platform"])
        job = vexstore.obter("vexpublish_jobs", resultado["publish_job_id"])
        self.assertEqual(conta["id"], job["account"])
        self.assertEqual(str(self.saida), job["media_path"])
        self.assertEqual("", job["published_url"])

    def test_enfileirar_duas_vezes_nao_duplica(self):
        self._conta_vexpublish("@perfil_repetido")
        self.canal = store.insert(
            "campaign_channels",
            {"network": "tiktok", "handle": "@perfil_repetido", "created_at": store.now()},
        )
        primeiro = self._enfileirar()
        segundo = self._enfileirar()
        self.assertEqual(primeiro["publish_job_id"], segundo["publish_job_id"])


class MetricasTests(unittest.TestCase):
    def setUp(self):
        store.migrate()
        self.client = TestClient(app)
        self.admin = {"X-Campaigns-Token": os.environ["CAMPAIGNS_LOCAL_TOKEN"]}
        stamp = store.now()
        campanha = store.insert(
            "campaign_campaigns",
            {"platform": "manual", "name": "Metrica", "created_at": stamp, "updated_at": stamp},
        )
        candidato = store.insert(
            "campaign_candidates",
            {
                "campaign_id": campanha["id"],
                "status": "approved",
                "idempotency_key": f"metric-{stamp}",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        self.publicacao = store.insert(
            "campaign_publications",
            {
                "campaign_id": campanha["id"],
                "candidate_id": candidato["id"],
                "idempotency_key": f"pub-{stamp}",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )

    def test_registra_e_lista_medicao(self):
        corpo = {"publication_id": self.publicacao["id"], "reported_views": 900, "validated_views": 750}
        criado = self.client.post("/campaigns/v1/metrics", headers=self.admin, json=corpo)
        self.assertEqual(201, criado.status_code)
        leitura = self.client.get(
            f"/campaigns/v1/publications/{self.publicacao['id']}/metrics", headers=self.admin
        ).json()
        self.assertEqual(750, leitura["latest_validated_views"])
        self.assertEqual(1, leitura["samples"])

    def test_views_validadas_nao_superam_informadas(self):
        corpo = {"publication_id": self.publicacao["id"], "reported_views": 10, "validated_views": 99}
        self.assertEqual(
            422, self.client.post("/campaigns/v1/metrics", headers=self.admin, json=corpo).status_code
        )

    def test_publicacao_inexistente_recusa_medicao(self):
        corpo = {"publication_id": "nao-existe", "reported_views": 1, "validated_views": 1}
        self.assertEqual(
            404, self.client.post("/campaigns/v1/metrics", headers=self.admin, json=corpo).status_code
        )

    def test_health_expoe_estado_da_ponte(self):
        self.assertIn("vexpublish_bridge", self.client.get("/campaigns/v1/health").json())


if __name__ == "__main__":
    unittest.main()
