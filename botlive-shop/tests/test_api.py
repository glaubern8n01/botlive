import io, os, subprocess, sys, tempfile, unittest, wave
from unittest import mock
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
LOCAL_AGENT = Path(__file__).parents[1] / "apps" / "local-agent"
os.environ["SHOP_LIVE_DATABASE_URL"] = f"sqlite:///{Path(TEMP.name, 'test.db').as_posix()}"
os.environ["SHOP_LIVE_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["SHOP_LIVE_ALLOWED_EXTENSION_IDS"] = "abcdefghijklmnopabcdefghijklmnop"
os.environ["SHOP_LIVE_AUTH_DISABLED"] = "true"
os.environ["SHOP_LIVE_MEDIA_ROOT"] = str(Path(TEMP.name,"media"))
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

    def ws_url(self,headers=None):
        ticket=self.client.post("/shop-live/v1/auth/ws-ticket",headers=headers or {}).json()
        return f'/shop-live/v1/events?expires={ticket["expires"]}&ticket={ticket["ticket"]}'

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
        product=self.product()
        response=self.client.post("/shop-live/v1/sessions",json={"title":"Sessão duplicada","estimated_minutes":30,"product_ids":[product["id"],product["id"]]})
        self.assertEqual(response.status_code,422)

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

    def test_real_upload_metadata_playback_and_safe_delete(self):
        buffer=io.BytesIO()
        with wave.open(buffer,"wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b"\0\0"*8000)
        response=self.client.post("/shop-live/v1/media/upload",data={"authorized":"true","authorization_source":"Gerado pelo teste"},files={"file":("operator.wav",buffer.getvalue(),"audio/wav")})
        self.assertEqual(response.status_code,201,response.text);media=response.json()
        self.assertEqual(media["kind"],"audio");self.assertEqual(media["duration_seconds"],1);self.assertEqual(media["size_bytes"],16044)
        self.assertNotEqual(media["stored_name"],"operator.wav");self.assertNotIn("/",media["stored_name"])
        ticket=self.client.get(f'/shop-live/v1/media/{media["id"]}/ticket').json()
        self.assertEqual(self.client.get(ticket["url"]).content[:4],b"RIFF")
        session=self.client.post("/shop-live/v1/sessions",json={"title":"Fila local","estimated_minutes":5}).json()
        self.assertEqual(self.client.put(f'/shop-live/v1/sessions/{session["id"]}/materials',json=[{"media_id":media["id"],"position":0,"planned_duration_seconds":30}]).status_code,200)
        started=self.client.post(f'/shop-live/v1/sessions/{session["id"]}/playback/control',json={"action":"start"}).json();self.assertEqual(started["status"],"playing")
        self.assertEqual(self.client.post(f'/shop-live/v1/sessions/{session["id"]}/playback/control',json={"action":"pause"}).json()["status"],"paused")
        self.assertEqual(self.client.post(f'/shop-live/v1/sessions/{session["id"]}/playback/control',json={"action":"resume"}).json()["status"],"playing")
        self.assertEqual(self.client.delete(f'/shop-live/v1/media/{media["id"]}').status_code,409)
        self.assertEqual(self.client.post(f'/shop-live/v1/sessions/{session["id"]}/playback/control',json={"action":"stop"}).json()["status"],"stopped")
        self.client.put(f'/shop-live/v1/sessions/{session["id"]}/materials',json=[])
        self.assertEqual(self.client.delete(f'/shop-live/v1/media/{media["id"]}').status_code,204)
        self.assertFalse(Path(TEMP.name,"media",media["stored_name"]).exists())
        audit=self.client.get("/shop-live/v1/audit?limit=200").json()["items"]
        for event in ["media.uploaded","playback.started","playback.paused","playback.resumed","playback.stopped","media.delete_blocked","media.deleted"]: self.assertTrue(any(row["type"]==event for row in audit),event)

    def test_upload_rejects_extension_mime_content_size_and_traversal(self):
        bad=self.client.post("/shop-live/v1/media/upload",data={"authorized":"true","authorization_source":"Teste"},files={"file":("bad.exe",b"x","application/octet-stream")});self.assertEqual(bad.status_code,422)
        mismatch=self.client.post("/shop-live/v1/media/upload",data={"authorized":"true","authorization_source":"Teste"},files={"file":("bad.wav",b"not-wave","audio/wav")});self.assertEqual(mismatch.status_code,422)
        with mock.patch.dict(os.environ,{"SHOP_LIVE_MEDIA_MAX_BYTES":"4"}):
            too_big=self.client.post("/shop-live/v1/media/upload",data={"authorized":"true","authorization_source":"Teste"},files={"file":("large.wav",b"RIFFxxxxWAVE", "audio/wav")});self.assertEqual(too_big.status_code,422)
        from app.media_storage import safe_path
        with self.assertRaises(ValueError): safe_path("../outside.wav")

    def test_complete_assisted_runtime_library_diagnostics_report_and_settings(self):
        product=self.client.post("/shop-live/v1/products",json={"name":"Produto completo","category":"Casa","price":99,"tags":["destaque"],"notes":"Uso autorizado"}).json()
        duplicate=self.client.post(f'/shop-live/v1/products/{product["id"]}/duplicate');self.assertEqual(duplicate.status_code,201)
        script=self.client.post("/shop-live/v1/scripts",json={"product_id":product["id"],"kind":"apresentacao","position":0,"duration_seconds":30,"title":"Abertura humana","text":"Apresente o produto sem alegações proibidas."}).json()
        self.assertEqual(self.client.post(f'/shop-live/v1/scripts/{script["id"]}/duplicate').status_code,201)
        buffer=io.BytesIO()
        with wave.open(buffer,"wb") as wav: wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b"\0\0"*4000)
        media=self.client.post("/shop-live/v1/media/upload",data={"product_id":product["id"],"authorized":"true","authorization_source":"Teste local"},files={"file":("complete.wav",buffer.getvalue(),"audio/wav")}).json()
        self.assertEqual(self.client.post(f'/shop-live/v1/media/{media["id"]}/duplicate').status_code,201)
        library=self.client.get("/shop-live/v1/library?q=completo&kind=product").json();self.assertIn(product["id"],{row["id"] for row in library["products"]})
        session=self.client.post("/shop-live/v1/sessions",json={"title":"Fluxo completo","estimated_minutes":30,"product_ids":[product["id"]]}).json()
        item={"media_id":media["id"],"position":0,"planned_duration_seconds":20,"product_id":product["id"],"script_id":script["id"]}
        self.assertEqual(self.client.put(f'/shop-live/v1/sessions/{session["id"]}/materials',json=[item]).status_code,200)
        started=self.client.post(f'/shop-live/v1/sessions/{session["id"]}/runtime/control',json={"action":"start_rehearsal"}).json();self.assertEqual(started["mode"],"rehearsal");self.assertEqual(started["product"]["id"],product["id"]);self.assertEqual(started["script"]["id"],script["id"])
        tele=self.client.post(f'/shop-live/v1/sessions/{session["id"]}/runtime/control',json={"action":"teleprompter","speed":1.5,"font_size":40,"teleprompter_paused":False}).json();self.assertEqual(tele["teleprompter_font_size"],40)
        diagnostic=self.client.post(f'/shop-live/v1/sessions/{session["id"]}/diagnostics',json={"camera":"frozen","microphone":"silent","connection":"unstable","volume":0}).json();self.assertIn("camera_frozen",diagnostic["problems"])
        self.assertEqual(self.client.post(f'/shop-live/v1/sessions/{session["id"]}/comments/simulated?text=Teste').status_code,201)
        self.assertEqual(self.client.put("/shop-live/v1/settings/hotkeys",json={"value":{"Space":"pause"}}).status_code,200);self.assertEqual(self.client.get("/shop-live/v1/settings").json()["hotkeys"]["Space"],"pause")
        report=self.client.get(f'/shop-live/v1/sessions/{session["id"]}/report').json();self.assertGreater(report["summary"]["events"],3);self.assertGreater(report["summary"]["problems"],0)
        csv_report=self.client.get(f'/shop-live/v1/sessions/{session["id"]}/report?format=csv');self.assertEqual(csv_report.status_code,200);self.assertIn("timestamp,type,result",csv_report.text)
        self.assertFalse(self.client.get("/shop-live/v1/integrations/tiktok").json()["connected"])
        signed=self.client.get(f'/shop-live/v1/media/{media["id"]}/ticket').json();self.assertEqual(self.client.get(signed["url"]).status_code,200);self.assertEqual(self.client.get(f'/shop-live/v1/media/{media["id"]}/content?expires=9999999999&ticket=bad').status_code,401)

    def test_extension_allowlist_is_exact(self):
        from app.main import allowed_websocket_origin
        self.assertTrue(allowed_websocket_origin("chrome-extension://abcdefghijklmnopabcdefghijklmnop"))
        self.assertFalse(allowed_websocket_origin("chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))

    def test_websocket_start_pause_resume_stop(self):
        with self.client.websocket_connect(self.ws_url(),headers={"origin":"http://localhost:3000"}) as ws:
            self.assertEqual(ws.receive_json()["type"],"simulation.ready")
            ws.send_json({"action":"start","speed":1})
            self._until(ws,"simulation.started")
            ws.send_json({"action":"pause"}); self._until(ws,"simulation.paused")
            ws.send_json({"action":"resume"}); self._until(ws,"simulation.resumed")
            ws.send_json({"action":"stop"}); self._until(ws,"simulation.stopped")
        self.assertEqual(self.client.get("/shop-live/v1/sessions").json()[-1]["status"],"encerrada")

    def test_disconnect_marks_running_session_interrupted(self):
        with self.client.websocket_connect(self.ws_url(),headers={"origin":"http://localhost:3000"}) as ws:
            ws.receive_json(); ws.send_json({"action":"start","speed":1}); self._until(ws,"simulation.started")
        self.assertEqual(self.client.get("/shop-live/v1/sessions").json()[-1]["status"],"interrompida")

    def test_websocket_rejects_unknown_origin(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect(self.ws_url(),headers={"origin":"https://evil.example"}) as ws: ws.receive_json()

    def test_websocket_requires_local_token_when_auth_enabled(self):
        with mock.patch.dict(os.environ,{"SHOP_LIVE_AUTH_DISABLED":"false","SHOP_LIVE_LOCAL_TOKEN":"correct"}):
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/shop-live/v1/events?expires=9999999999&ticket=wrong",headers={"origin":"http://localhost:3000"}) as ws: ws.receive_json()
            with self.client.websocket_connect(self.ws_url({"X-Shop-Live-Token":"correct"}),headers={"origin":"http://localhost:3000"}) as ws:
                self.assertEqual(ws.receive_json()["type"],"simulation.ready")

    def test_chrome_extension_origin_requires_valid_shape_and_token(self):
        chrome_origin="chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        with mock.patch.dict(os.environ,{"SHOP_LIVE_AUTH_DISABLED":"false","SHOP_LIVE_LOCAL_TOKEN":"correct"}):
            with self.client.websocket_connect(self.ws_url({"X-Shop-Live-Token":"correct"}),headers={"origin":chrome_origin}) as ws:
                self.assertEqual(ws.receive_json()["type"],"simulation.ready")
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/shop-live/v1/events?expires=9999999999&ticket=wrong",headers={"origin":chrome_origin}) as ws: ws.receive_json()

    def _until(self,ws,expected):
        for _ in range(80):
            event=ws.receive_json()
            if event["type"]==expected:return event
        self.fail(f"Evento {expected} não recebido")

class DashboardContractTests(unittest.TestCase):
    def test_dashboard_has_real_crud_session_builder_and_controls(self):
        source=(Path(__file__).parents[2]/"dashboard"/"src"/"pages"/"ShopLive.tsx").read_text(encoding="utf-8")
        self.assertIn('playback?.status==="playing"?"pause"',source); self.assertIn('runtimeCommand("start_rehearsal")',source); self.assertIn('runtimeCommand("stop")',source)
        self.assertIn('method:"PUT"',source); self.assertIn('method:"DELETE"',source)
        self.assertIn("SessionBuilder",source);self.assertIn("draggable",source);self.assertIn("Teleprompter",source)
        self.assertIn("navigator.mediaDevices.getUserMedia",source);self.assertIn("requestFullscreen",source)
        self.assertNotIn("content?token=",source)
