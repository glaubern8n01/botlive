import json, unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]/"apps"/"extension"

class ExtensionTests(unittest.TestCase):
    def test_manifest_v3_has_minimum_local_permissions(self):
        manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"],3)
        self.assertEqual(set(manifest["permissions"]),{"sidePanel","storage"})
        self.assertTrue(all("127.0.0.1" in host or "localhost" in host for host in manifest["host_permissions"]))
        self.assertNotIn("tiktok.com",json.dumps(manifest).lower())
        self.assertNotIn("<all_urls>",json.dumps(manifest))

    def test_content_script_is_simulator_only_and_no_eval(self):
        manifest=(ROOT/"manifest.json").read_text(encoding="utf-8")
        scripts="\n".join(path.read_text(encoding="utf-8") for path in ROOT.glob("*.js"))
        self.assertIn("/shop-live/simulator-page",manifest)
        self.assertNotIn("eval(",scripts)

    def test_side_panel_has_manual_live_studio_checklist(self):
        panel=(ROOT/"sidepanel.html").read_text(encoding="utf-8")
        self.assertIn("Checklist manual · TikTok LIVE Studio",panel)
        self.assertIn("Operador presente",panel)
        self.assertNotIn("Iniciar automaticamente",panel)
        script=(ROOT/"sidepanel.js").read_text(encoding="utf-8")
        self.assertIn("chrome.storage.session",script)
        self.assertIn("127.0.0.1:8765",script)
        self.assertIn("MAX_RECONNECTS = 5",script)
        self.assertIn("operation.context",script)
        self.assertIn("data-command=\"pause\"",panel)
        worker=(ROOT/"service-worker.js").read_text(encoding="utf-8")
        self.assertIn("simulator.snapshot.forwarded",worker)
