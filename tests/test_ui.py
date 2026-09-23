"""Run with requirements-streamlit.txt installed; no live network required."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, 'Streamlit runtime not installed')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        from datetime import date
        self.prices = pd.Series(range(100,820),index=pd.bdate_range(end=date.today(),periods=720),dtype=float)
        self.mock = patch('streamlit_app.engine._series', return_value=self.prices)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py'),default_timeout=30).run()

    def navigate(self, page):
        self.app.sidebar.radio[0].set_value(page).run()
        self.assertEqual([e.value for e in self.app.exception], [])

    def test_all_nine_workspaces(self):
        for page in ['Overview','Strategies','Studio','Signals','Rebalance','Portfolio','History','Data','Close']:
            with self.subTest(page=page):
                self.navigate(page)

    def test_cached_three_argument_engine_is_reloaded(self):
        import importlib
        import streamlit_app.engine as engine
        original_reload = importlib.reload
        def stale_planner(view, strategies, as_of):
            raise AssertionError('The stale planner must never be called')
        def reload_with_fixture(module):
            refreshed = original_reload(module)
            refreshed._series = lambda *args, **kwargs: self.prices
            return refreshed
        with patch.object(engine, 'build_action_plan', stale_planner), patch('importlib.reload', side_effect=reload_with_fixture) as reload:
            self.app.run()
            self.assertFalse(self.app.exception)
            reload.assert_called_once_with(engine)

    def test_incompatible_deployment_stops_with_clear_message(self):
        import streamlit_app.engine as engine
        with patch.object(engine, 'build_action_plan', lambda a,b,c: None), patch('importlib.reload', return_value=engine):
            self.app.run()
            self.assertFalse(self.app.exception)
            self.assertTrue(any('배포 파일의 버전' in e.value for e in self.app.error))

    def test_studio_save_and_engine_connection(self):
        self.navigate('Studio')
        frequency = next(w for w in self.app.selectbox if w.label == '판정 주기')
        frequency.set_value('daily').run()
        button = next(w for w in self.app.button if w.label == '검토한 규칙 적용')
        button.click().run()
        self.assertFalse(self.app.exception)
        strategies = self.app.session_state['strategies']
        spec = json.loads(strategies.iloc[0]['params_json'])
        self.assertEqual(spec['schema_version'],2)
        self.assertEqual(spec['scope']['run'],'daily')
        self.navigate('Signals')
        self.navigate('Rebalance')
        self.navigate('Data')

    def test_studio_table_and_card_switch(self):
        self.navigate('Studio')
        next(w for w in self.app.radio if w.label == '조건 편집 방식').set_value('표').run()
        self.assertFalse(self.app.exception)
        next(w for w in self.app.radio if w.label == '조건 편집 방식').set_value('카드').run()
        self.assertFalse(self.app.exception)

    def test_empty_prices_do_not_crash_overview(self):
        self.mock.stop()
        with patch('streamlit_app.engine._series', return_value=pd.Series(dtype=float)):
            del self.app.session_state['priced_holdings']
            self.navigate('Overview')

    def test_execution_values_survive_navigation(self):
        holdings = self.app.session_state['holdings'].copy()
        holdings.loc[holdings['ticker'].eq('CASH'),'shares'] = 1000000
        self.app.session_state['holdings'] = holdings
        del self.app.session_state['priced_holdings']
        self.navigate('Rebalance')
        saved = self.app.session_state['execution_plan'].copy()
        self.assertFalse(saved.empty)
        saved.loc[saved.index[0], '실제수량'] = 2.0
        saved.loc[saved.index[0], '실행'] = True
        self.app.session_state['execution_plan'] = saved
        self.navigate('Data')
        self.assertEqual(float(self.app.session_state['execution_plan'].iloc[0]['실제수량']),2)
        self.navigate('Rebalance')
        self.assertEqual(float(self.app.session_state['execution_plan'].iloc[0]['실제수량']),2)


if __name__ == '__main__':
    unittest.main()
