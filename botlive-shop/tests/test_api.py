import os, subprocess, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
LOCAL_AGENT = Path(__file__).parents[1] / "apps" / "local-agent"
os.environ["SHOP_LIVE_DATABASE_URL"] = f"sqlite:///{Path(TEMP.name, 'test.db').as_posix()}"
os.environ["SHOP_LIVE_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["SHOP_LIVE_ALLOWED_EXTENSION_IDS"] = "abcdefghijklmnopabcdefghijklmnop"
os.environ["SHOP_LIVE_AUTH_DISABLED"] = "true"
sys.path.insert(0, str(LOCAL_AGENT))
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=LOCAL_AGENT, check=True, capture_output=True)

from fastapi.testclient import TestClient
from app.main import app
from app.database import engine

class ApiTests(unittest.TestCase):
    def setUp(self): self.context=TestClient(app); self.client=self.context.__enter__()
    def tearDown(self): self.context.__exit__(None,None,None)
    @classmethod
    def tearDownClass(cls): engine.dispose(); TEMP.cleanup()

    def product(self):
        return self.client.post("/shop-live/v1/products",json={"name":"Produto teste","price":10}).json()

    def test_auth_is_required_outside_controlled_tests(self):
        with mock.patch.dict(os.environ,{"SHOP_LIVE_AUTH_DISABLED":"false","SHOP_LIVE_LOCAL_TOKEN":"correct"}):
            self.assertEqual(self.client.get("/shop-live/v1/health").status_code,401)
            self.assertEqual(self.client.get("/shop-live/v1/health",headers={"X-Shop-Live-Token":"correct"}).status_code,200)

    def test_product_session_relation_and_audit_persist(self):
        product=self.product()
        created=self.client.post("/shop-live/v1/sessions",json={"title":"Sessão teste","estimated_minutes":30,"product_ids":[product["id"]]})
        self.assertEqual(created.status_code,201)
        self.assertEqual(created.json()["product_ids"],[product["id"]])
        sessions=self.client.get("/shop-live/v1/sessions").json()
        self.assertEqual(sessions[-1]["product_ids"],[product["id"]])
        audit=self.client.get("/shop-live/v1/audit?limit=2&offset=0").json()
        self.assertEqual(audit["limit"],2); self.assertLessEqual(len(audit["items"]),2)

    def test_session_rejects_unknown_product(self):
        self.assertEqual(self.client.post("/shop-live/v1/sessions",json={"title":"Sessão teste","estimated_minutes":30,"product_ids":["missing"]}).status_code,422)

    def test_authorized_media_scripts_and_session_order(self):
        product=self.product()
        session=self.client.post("/shop-live/v1/sessions",json={"title":"Operação assistida","estimated_minutes":30,"product_ids":[product["id"]]}).json()
        blocked=self.client.post("/shop-live/v1/media",json={"product_id":product["id"],"kind":"video","name":"Sem autorização","local_path":"media/demo.mp4","authorized":True})
        self.assertEqual(blocked.status_code,422)
        media=self.client.post("/shop-live/v1/media",json={"product_id":product["id"],"kind":"video","name":"Demonstração autorizada","local_path":"media/demo.mp4","duration_seconds":90,"authorized":True,"authorization_source":"Produção própria"}).json()
        script=self.client.post("/shop-live/v1/scripts",json={"product_id":product["id"],"kind":"demonstracao","position":1,"duration_seconds":60,"text":"Mostre o produto com presença humana."})
        self.assertEqual(script.status_code,201)
        self.assertEqual(self.client.get(f'/shop-live/v1/products/{product["id"]}/scripts').json()[0]["kind"],"demonstracao")
        planned=self.client.put(f'/shop-live/v1/sessions/{session["id"]}/materials',json=[{"media_id":media["id"],"position":1,"planned_duration_seconds":75}])
        self.assertEqual(planned.status_code,200)
        self.assertEqual(self.client.get(f'/shop-live/v1/sessions/{session["id"]}/materials').json()["items"][0]["planned_duration_seconds"],75)
        duplicate=self.client.put(f'/shop-live/v1/sessions/{session["id"]}/materials',json=[{"media_id":media["id"],"position":1,"planned_duration_seconds":30},{"media_id":media["id"],"position":2,"planned_duration_seconds":30}])
        self.assertEqual(duplicate.status_code,422)

    def test_crud_audit_and_operation_context(self):
        first=self.product(); second=self.client.post("/shop-live/v1/products",json={"name":"Produto seguinte","price":20}).json()
        updated=self.client.put(f'/shop-live/v1/products/{first["id"]}',json={"name":"Produto editado","price":12}).json(); self.assertEqual(updated["name"],"Produto editado")
        block=self.client.post("/shop-live/v1/scripts",json={"product_id":first["id"],"kind":"apresentacao","position":0,"duration_seconds":30,"text":"Roteiro real cadastrado"}).json()
        live=self.client.post("/shop-live/v1/sessions",json={"title":"Sessão montada","estimated_minutes":30,"product_ids":[first["id"],second["id"]]}).json()
        context=self.client.get(f'/shop-live/v1/sessions/{live["id"]}/operation').json()
        self.assertEqual(context["current_product"]["id"],first["id"]); self.assertEqual(context["next_product"]["id"],second["id"]); self.assertEqual(context["scripts"][0]["id"],block["id"])
        self.assertEqual(self.client.delete(f'/shop-live/v1/scripts/{block["id"]}').status_code,204)
        audit=self.client.get("/shop-live/v1/audit?limit=100").json()["items"]
        self.assertTrue(any(row["type"]=="product.updated" for row in audit)); self.assertTrue(any(row["type"]=="script.deleted" for row in audit))

    def test_extension_allowlist_is_exact(self):
        from app.main import allowed_websocket_origin
        self.assertTrue(allowed_websocket_origin("chrome-extension://abcdefghijklmnopabcdefghijklmnop"))
        self.assertFalse(allowed_websocket_origin("chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))

    def test_websocket_start_pause_resume_stop(self):
        with self.client.websocket_connect("/shop-live/v1/events",headers={"origin":"http://localhost:3000"}) as ws:
            self.assertEqual(ws.receive_json()["type"],"simulation.ready")
            ws.send_json({"action":"start","speed":1})
            self._until(ws,"simulation.started")
            ws.send_json({"action":"pause"}); self._until(ws,"simulation.paused")
            ws.send_json({"action":"resume"}); self._until(ws,"simulation.resumed")
            ws.send_json({"action":"stop"}); self._until(ws,"simulation.stopped")
        self.assertEqual(self.client.get("/shop-live/v1/sessions").json()[-1]["status"],"encerrada")

    def test_disconnect_marks_running_session_interrupted(self):
        with self.client.websocket_connect("/shop-live/v1/events",headers={"origin":"http://localhost:3000"}) as ws:
            ws.receive_json(); ws.send_json({"action":"start","speed":1}); self._until(ws,"simulation.started")
        self.assertEqual(self.client.get("/shop-live/v1/sessions").json()[-1]["status"],"interrompida")

    def test_websocket_rejects_unknown_origin(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/shop-live/v1/events",headers={"origin":"https://evil.example"}) as ws: ws.receive_json()

    def test_websocket_requires_local_token_when_auth_enabled(self):
        with mock.patch.dict(os.environ,{"SHOP_LIVE_AUTH_DISABLED":"false","SHOP_LIVE_LOCAL_TOKEN":"correct"}):
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/shop-live/v1/events?token=wrong",headers={"origin":"http://localhost:3000"}) as ws: ws.receive_json()
            with self.client.websocket_connect("/shop-live/v1/events?token=correct",headers={"origin":"http://localhost:3000"}) as ws:
                self.assertEqual(ws.receive_json()["type"],"simulation.ready")

    def test_chrome_extension_origin_requires_valid_shape_and_token(self):
        chrome_origin="chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        with mock.patch.dict(os.environ,{"SHOP_LIVE_AUTH_DISABLED":"false","SHOP_LIVE_LOCAL_TOKEN":"correct"}):
            with self.client.websocket_connect("/shop-live/v1/events?token=correct",headers={"origin":chrome_origin}) as ws:
                self.assertEqual(ws.receive_json()["type"],"simulation.ready")
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/shop-live/v1/events?token=wrong",headers={"origin":chrome_origin}) as ws: ws.receive_json()

    def _until(self,ws,expected):
        for _ in range(80):
            event=ws.receive_json()
            if event["type"]==expected:return event
        self.fail(f"Evento {expected} não recebido")

class DashboardContractTests(unittest.TestCase):
    def test_dashboard_has_real_crud_session_builder_and_controls(self):
        source=(Path(__file__).parents[2]/"dashboard"/"src"/"pages"/"ShopLive.tsx").read_text(encoding="utf-8")
        self.assertIn('command("pause")',source); self.assertIn('command("resume")',source); self.assertIn('command("stop")',source)
        self.assertIn('method:"PUT"',source); self.assertIn('method:"DELETE"',source)
        self.assertIn("MaterialForm",source)
