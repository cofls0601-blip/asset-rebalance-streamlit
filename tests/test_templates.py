import unittest

from streamlit_app.templates import TEMPLATES, apply_template


class TemplateTests(unittest.TestCase):
    def test_library_contains_19_unique_templates(self):
        self.assertEqual(len(TEMPLATES), 19)
        self.assertEqual(len({item["id"] for item in TEMPLATES}), 19)

    def test_static_template_totals_100_percent(self):
        for item in TEMPLATES:
            if item["rule"] == "static":
                self.assertAlmostEqual(sum(asset["target_pct"] for asset in item["assets"]), 100, msg=item["name"])

    def test_kr_substitution_updates_sma_tickers(self):
        strategy, assets = apply_template("laa", "NEW", "계좌", True)
        self.assertIn("133690", strategy["params_json"])
        self.assertIn("251350", strategy["params_json"])
        self.assertEqual(set(assets["strategy"]), {"NEW"})
        self.assertIn("CASH", set(assets["ticker"]))


if __name__ == "__main__":
    unittest.main()
