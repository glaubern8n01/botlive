import os,socket,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"local-agent"))
os.environ["CAMPAIGNS_DATABASE_PATH"]=str(Path(tempfile.mkdtemp())/"test.db")
from app import store
from app.adapters import ADAPTERS
from app.security import confined_path,safe_reference_url
class Tests(unittest.TestCase):
 def setUp(self):
  store.migrate()
  with store.connect() as db:
   for table in ("campaign_candidates","campaign_campaigns"):db.execute(f"DELETE FROM {table}")
 def test_manual_adapters(self):
  self.assertEqual({"networking-club","viewx","manual"},set(ADAPTERS));self.assertTrue(all(not x.official_api_verified for x in ADAPTERS.values()))
 def test_schema_idempotent(self): store.migrate();self.assertEqual([],store.rows("campaign_campaigns"))
 def test_candidate_idempotency(self):
  stamp=store.now();c=store.insert("campaign_campaigns",{"platform":"manual","name":"Teste","created_at":stamp,"updated_at":stamp});p={"campaign_id":c["id"],"idempotency_key":"same-key","created_at":stamp,"updated_at":stamp};store.insert("campaign_candidates",p)
  with self.assertRaises(Exception): store.insert("campaign_candidates",p)
 def test_path_confinement(self):
  root=Path(tempfile.mkdtemp());self.assertEqual(root.resolve()/"passwd",confined_path(root,"../../passwd"))
 def test_ssrf_private_ip(self):
  original=socket.getaddrinfo;socket.getaddrinfo=lambda *a:[(socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",443))]
  try:
   with self.assertRaises(ValueError):safe_reference_url("https://example.test/video.mp4")
  finally:socket.getaddrinfo=original
if __name__=="__main__":unittest.main()
