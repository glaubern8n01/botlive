import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "local-agent"))
from packages.adapters import MockLiveAdapter
from app.compliance import evaluate_signal

class ComplianceTests(unittest.TestCase):
    def test_critical_requires_pause(self):
        alert = evaluate_signal("video.freeze_seconds", 9)[0]
        self.assertEqual(alert["severity"], "critico")
        self.assertTrue(alert["pause_required"])
    def test_below_threshold_is_clear(self):
        self.assertEqual(evaluate_signal("audio.silence_seconds", 11.9), [])
    def test_prohibited_claim_is_blocked(self):
        self.assertEqual(evaluate_signal("script.prohibited_claim", True)[0]["rule"], "LIVE_CLAIM_001")
    def test_mock_is_deterministic(self):
        adapter = MockLiveAdapter(42); adapter.connect()
        self.assertEqual(adapter.state(), {"status": "simulation", "seed": 42})
