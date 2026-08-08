import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "local-agent"))
from app.simulator import scenario

class SimulatorTests(unittest.TestCase):
    def test_seed_is_reproducible_and_complete(self):
        self.assertEqual(scenario(42), scenario(42))
        kinds = {e["type"] for e in scenario(42)}
        self.assertTrue({"viewer.count_changed","comment.received","order.detected","audio.muted","video.freeze_seconds","connection.packet_loss"} <= kinds)
