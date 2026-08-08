import os, sys, tempfile, unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ["SHOP_LIVE_DATABASE_URL"] = f"sqlite:///{Path(TEMP.name, 'test.db').as_posix()}"
os.environ["SHOP_LIVE_ALLOWED_ORIGINS"] = "http://localhost:3000"
sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "local-agent"))

from fastapi.testclient import TestClient
from app.main import app
from app.database import engine

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
    def tearDown(self): self.client_context.__exit__(None, None, None)
    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        TEMP.cleanup()

    def test_health_and_persistence(self):
        self.assertTrue(self.client.get("/shop-live/v1/health").json()["ok"])
        created = self.client.post("/shop-live/v1/products", json={"name":"Produto real de teste","price":10,"approved_answers":[],"prohibited_claims":[]})
        self.assertEqual(created.status_code, 201)
        self.assertTrue(any(x["id"] == created.json()["id"] for x in self.client.get("/shop-live/v1/products").json()))
        self.assertTrue(any(x["type"] == "product.created" for x in self.client.get("/shop-live/v1/audit").json()))

    def test_session_rejects_unknown_product(self):
        response = self.client.post("/shop-live/v1/sessions", json={"title":"Sessão teste","estimated_minutes":30,"product_ids":["missing"]})
        self.assertEqual(response.status_code, 422)

    def test_websocket_stream_and_compliance(self):
        with self.client.websocket_connect("/shop-live/v1/events", headers={"origin":"http://localhost:3000"}) as ws:
            self.assertEqual(ws.receive_json()["type"], "simulation.ready")
            ws.send_json({"speed":20})
            received = []
            while "session.ended" not in received:
                received.append(ws.receive_json()["type"])
            self.assertIn("viewer.count_changed", received)
            self.assertIn("comment.received", received)
            self.assertIn("order.detected", received)
            self.assertIn("compliance.warning_received", received)

    def test_websocket_rejects_unknown_origin(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/shop-live/v1/events", headers={"origin":"https://evil.example"}) as ws:
                ws.receive_json()

class DashboardContractTests(unittest.TestCase):
    def test_dashboard_uses_websocket_without_fixed_metrics(self):
        source = (Path(__file__).parents[2] / "dashboard" / "src" / "pages" / "ShopLive.tsx").read_text(encoding="utf-8")
        self.assertIn("new WebSocket", source)
        self.assertIn("viewer.count_changed", source)
        self.assertNotIn("164 audiência", source)
        self.assertNotIn("R$ 79,90", source)
