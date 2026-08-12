import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"local-agent"))
os.environ["CAMPAIGNS_DATABASE_PATH"]=str(Path(tempfile.mkdtemp())/"queue.db")
from app import queue,store
from app.rules import evaluate,summary
class QueueRuleTests(unittest.TestCase):
 def setUp(self):
  store.migrate()
  with store.connect() as db:
   for table in ("campaign_jobs","campaign_rule_checks","campaign_candidates","campaign_materials","campaign_campaigns"):db.execute(f"DELETE FROM {table}")
 def test_atomic_claim_and_duplicate_job(self):
  first=queue.enqueue("detect","material",{},"unique");same=queue.enqueue("detect","material",{},"unique");self.assertEqual(first["id"],same["id"]);claimed=queue.claim("worker-a");self.assertEqual(first["id"],claimed["id"]);self.assertIsNone(queue.claim("worker-b"))
 def test_cancel_queued(self):
  job=queue.enqueue("detect","material",{},"cancel");self.assertTrue(queue.cancel(job["id"]));self.assertEqual("cancelled",store.get("campaign_jobs",job["id"])["status"])
 def test_orphan_recovery(self):
  job=queue.enqueue("detect","material",{},"orphan");queue.claim("dead");
  with store.connect() as db:db.execute("UPDATE campaign_jobs SET heartbeat_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
  self.assertEqual(1,queue.recover_orphans());self.assertEqual("retry_wait",store.get("campaign_jobs",job["id"])["status"])
 def test_critical_rule_blocks(self):
  campaign={"min_duration":20,"max_duration":60,"hashtags":["#marca"],"mentions":[],"rules":{"prohibited_words":["fraude"]}}
  candidate={"source_start":0,"source_end":10,"caption":"fraude","material_id":"m"};checks=evaluate(campaign,candidate,{"width":1080,"height":1920,"authorized":True});self.assertEqual("blocked",summary(checks));self.assertTrue(any(x["rule_key"]=="duration" and x["status"]=="rejected" for x in checks))
if __name__=="__main__":unittest.main()
