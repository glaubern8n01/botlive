import unittest
from packages.adapters import TikTokShopOfficialAdapter

class OfficialAdapterTests(unittest.TestCase):
    def test_adapter_is_inert_until_official_approval_and_credentials(self):
        adapter=TikTokShopOfficialAdapter()
        self.assertFalse(adapter.readiness()["ready"])
        self.assertFalse(adapter.state()["external_actions"])
        self.assertFalse(adapter.state()["live_studio_control"])
        with self.assertRaises(RuntimeError): adapter.connect()
        with self.assertRaises(RuntimeError): adapter.list_products()

    def test_readiness_requires_all_official_values(self):
        self.assertTrue(TikTokShopOfficialAdapter("app","token","shop").readiness()["ready"])
