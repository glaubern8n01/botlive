import unittest
from packages.adapters import MockLiveAdapter
from packages.compliance_engine import Severity, Signal, evaluate

class ComplianceTests(unittest.TestCase):
    def test_critical_requires_pause(self):
        alert = evaluate([Signal("video.freeze_seconds", 9)])[0]
        self.assertEqual(alert.severity, Severity.CRITICAL)
        self.assertTrue(alert.pause_required)
    def test_below_threshold_is_clear(self):
        self.assertEqual(evaluate([Signal("audio.silence_seconds", 11.9)]), [])
    def test_prohibited_claim_is_blocked(self):
        self.assertEqual(evaluate([Signal("script.prohibited_claim", True)])[0].rule, "LIVE_CLAIM_001")
    def test_mock_is_deterministic(self):
        adapter = MockLiveAdapter(42); adapter.connect()
        self.assertEqual(adapter.state(), {"status": "simulation", "seed": 42})
