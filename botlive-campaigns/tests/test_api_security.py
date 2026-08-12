import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"local-agent"))
os.environ.update(CAMPAIGNS_DATABASE_PATH=str(Path(tempfile.mkdtemp())/"api.db"),CAMPAIGNS_LOCAL_TOKEN="admin-secret",CAMPAIGNS_OPERATOR_TOKEN="operator-secret",CAMPAIGNS_REVIEWER_TOKEN="reviewer-secret",CAMPAIGNS_ENABLED="true",CAMPAIGNS_DRY_RUN="true")
from fastapi.testclient import TestClient
from app.main import app
from app import store
class ApiSecurityTests(unittest.TestCase):
 def setUp(self):
  store.migrate();self.client=TestClient(app);self.admin={"X-Campaigns-Token":"admin-secret"};self.operator={"X-Campaigns-Token":"operator-secret"};self.reviewer={"X-Campaigns-Token":"reviewer-secret"}
  with store.connect() as db:
   for table in ("campaign_audit","campaign_campaigns"):db.execute(f"DELETE FROM {table}")
 def payload(self):return {"platform":"manual","name":"Campanha segura","rules":{},"networks":[],"hashtags":[],"mentions":[]}
 def test_auth_and_roles_are_backend_enforced(self):
  self.assertEqual(401,self.client.get("/campaigns/v1/campaigns").status_code);self.assertEqual(403,self.client.post("/campaigns/v1/campaigns",headers=self.reviewer,json=self.payload()).status_code);self.assertEqual(201,self.client.post("/campaigns/v1/campaigns",headers=self.operator,json=self.payload()).status_code)
 def test_feature_flag_off_hides_protected_routes(self):
  os.environ["CAMPAIGNS_ENABLED"]="false"
  try:self.assertEqual(404,self.client.get("/campaigns/v1/campaigns",headers=self.admin).status_code)
  finally:os.environ["CAMPAIGNS_ENABLED"]="true"
 def test_archive_preserves_referential_record(self):
  created=self.client.post("/campaigns/v1/campaigns",headers=self.admin,json=self.payload()).json();response=self.client.delete(f"/campaigns/v1/campaigns/{created['id']}",headers=self.admin);self.assertEqual(200,response.status_code);self.assertEqual(1,store.get("campaign_campaigns",created["id"])["archived"])
 def test_health_never_starts_external_action(self):self.assertTrue(self.client.get("/campaigns/v1/health").json()["legacy_untouched"])
if __name__=="__main__":unittest.main()
