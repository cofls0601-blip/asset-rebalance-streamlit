"""Streamlit user journeys with deterministic prices; no live service calls."""
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from test_revised_spec import fetch, holdings, strategies, DAY, NOW
from streamlit_app.workflow import run_evaluation

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.mock=patch('streamlit_app.engine._series',side_effect=fetch);self.mock.start();self.addCleanup(self.mock.stop)
        self.app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'),default_timeout=30).run()
        self.assertFalse(self.app.exception)

    def navigate(self,page):
        self.app.sidebar.radio[0].set_value(page).run()
        self.assertFalse(self.app.exception)

    def test_css_preserves_streamlit_material_icons(self):
        source=(Path(__file__).resolve().parents[1]/'streamlit_app.py').read_text(encoding='utf-8')
        self.assertNotIn('[class*="st-"]{font-family',source)
        self.assertIn('[data-testid="stIconMaterial"]',source)
        self.assertIn('Material Symbols Rounded',source)

    def with_run(self):
        h,s=holdings(),strategies()
        self.app.session_state['holdings']=h;self.app.session_state['strategies']=s
        self.app.session_state['run']=run_evaluation(h,s,DAY,fetch=fetch,now=NOW)
        self.app.sidebar.date_input[0].set_value(DAY).run()

    def test_all_workspaces_before_lookup(self):
        for page in ['이번 달','자산 현황','주문안','전략실','기록','설정']:self.navigate(page)

    def test_all_workspaces_with_real_calculations(self):
        self.with_run()
        for page in ['이번 달','자산 현황','주문안','전략실','기록','설정']:self.navigate(page)

    def test_evaluation_button_and_record_freeze(self):
        self.app.session_state['holdings']=holdings();self.app.session_state['strategies']=strategies()
        self.app.sidebar.date_input[0].set_value(DAY).run()
        next(b for b in self.app.button if b.label=='2 · 지정일 종가 조회·판정').click().run()
        self.assertFalse(self.app.exception);self.assertFalse(self.app.session_state['run']['errors'])
        self.navigate('기록')
        next(b for b in self.app.button if b.label=='평가 스냅샷 확정').click().run()
        self.assertFalse(self.app.exception);self.assertEqual(len(self.app.session_state['snapshots']),3)
        next(b for b in self.app.button if b.label=='평가 스냅샷 확정').click().run()
        self.assertEqual(len(self.app.session_state['snapshots']),3)

    def test_price_failure_is_visible_and_does_not_crash(self):
        self.mock.stop()
        with patch('streamlit_app.engine._series',side_effect=ValueError('가격 서비스 장애')):
            next(b for b in self.app.button if b.label=='2 · 지정일 종가 조회·판정').click().run()
            self.assertFalse(self.app.exception)
            self.assertTrue(any('확정 차단' in x.value for x in self.app.error))

    def test_inputs_survive_navigation(self):
        self.with_run();self.navigate('주문안')
        saved=self.app.session_state['fills'].copy();saved.loc[saved.index[0],'실제수량']=2.
        self.app.session_state['fills']=saved
        self.navigate('설정');self.navigate('주문안')
        self.assertEqual(self.app.session_state['fills'].iloc[0]['실제수량'],2.)

    def test_remote_auth_load_once_and_explicit_save(self):
        from test_revised_spec import ws, run
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'),default_timeout=30)
        app.secrets['SHEETS_WEBAPP_URL']='https://script.google.com/macros/s/test_deployment/exec'
        app.secrets['SHEETS_SECRET']='test-secret-'+'x'*32
        app.secrets['APP_PASSWORD']='test-password-1234'
        with patch('streamlit_app.sheets_sync.load_workspace',return_value=(ws(run()),'base')) as load, patch('streamlit_app.sheets_sync.save_workspace',return_value='saved') as save:
            app.run();load.assert_not_called()
            app.text_input[0].set_value('test-password-1234')
            next(b for b in app.button if b.label=='열기').click().run()
            self.assertFalse(app.exception);self.assertEqual(load.call_count,1)
            app.sidebar.radio[0].set_value('설정').run()
            self.assertEqual(load.call_count,1);save.assert_not_called()
            next(b for b in app.button if b.label=='Sheets에 저장').click().run()
            self.assertFalse(app.exception);save.assert_called_once()
            self.assertEqual(app.session_state['remote_token'],'saved')

if __name__=='__main__':unittest.main()
