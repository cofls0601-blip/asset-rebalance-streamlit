"""Design tokens: CSS :root and the Python mirror must agree; components use tokens."""
import re
import unittest
from pathlib import Path
from streamlit_app.ui import TOKENS, TARGET_STATUS_STYLES, CHART_COLORS

CSS = (Path(__file__).resolve().parents[1] / 'streamlit_app' / 'theme.css').read_text(encoding='utf-8')
ROOT = CSS[CSS.index(':root'):CSS.index('}', CSS.index(':root'))]
CSS_TOKENS = dict(re.findall(r'--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})', ROOT))


class DesignTokenTests(unittest.TestCase):
    def test_python_mirror_matches_css(self):
        for key, value in TOKENS.items():
            self.assertEqual(CSS_TOKENS.get(key.replace('_', '-')), value, key)

    def test_status_styles_use_semantic_tokens(self):
        self.assertEqual(TARGET_STATUS_STYLES['미달'], (TOKENS['under_soft'], TOKENS['under']))
        self.assertEqual(TARGET_STATUS_STYLES['초과'], (TOKENS['over_soft'], TOKENS['over']))
        self.assertEqual(CHART_COLORS[0], TOKENS['accent'])

    def test_components_reference_tokens_not_raw_hex(self):
        body = CSS[CSS.index('}', CSS.index(':root')):]
        self.assertEqual(re.findall(r'#[0-9a-fA-F]{6}', body), [])

    def test_single_mobile_breakpoint_block(self):
        self.assertEqual(CSS.count('@media (max-width: 800px)'), 1)


if __name__ == '__main__':
    unittest.main()
