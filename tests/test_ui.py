"""Streamlit user journeys with deterministic prices; no live service calls."""
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest
from test_revised_spec import fetch, holdings, strategies, DAY, NOW
from streamlit_app.ui import allocation_status_frame
from streamlit_app.studio import rule_preview_html
from streamlit_app.workflow import run_evaluation
from streamlit_app.ledger import (TABLES, freeze_run, execution_draft,
    apply_executions, cancel_orders)

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.mock=patch('streamlit_app.engine._series',side_effect=fetch);self.mock.start();self.addCleanup(self.mock.stop)
        self.app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'),default_timeout=30).run()
        self.assertFalse(self.app.exception)

    def navigate(self,page):
        self.app.sidebar.radio[0].set_value(page).run()
        self.assertFalse(self.app.exception)

    def test_css_preserves_streamlit_material_icons(self):
        source=(Path(__file__).resolve().parents[1]/'streamlit_app'/'theme.css').read_text(encoding='utf-8')
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

    def test_mobile_decision_summary_and_manual_order_list(self):
        self.with_run();self.navigate('이번 달')
        self.assertTrue(any('class="monthly-summary"' in block.value for block in self.app.markdown))
        self.assertTrue(any('class="decision-top"' in block.value for block in self.app.markdown))
        self.navigate('주문안')
        self.assertTrue(any('class="order-list"' in block.value for block in self.app.markdown))

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

    def test_allocation_status_uses_strategy_tolerance(self):
        plan=pd.DataFrame([
            {'전략':'A','현재비중(%)':38.,'실행목표(%)':40.},
            {'전략':'A','현재비중(%)':40.5,'실행목표(%)':40.},
            {'전략':'A','현재비중(%)':43.,'실행목표(%)':40.},
        ])
        settings=pd.DataFrame([{'code':'A','tolerance_pct':1.}])
        result=allocation_status_frame(plan,settings)
        self.assertEqual(set(result['목표상태']),{'미달','충족','초과'})

    def test_order_review_button_changes_workspace(self):
        self.with_run();self.navigate('이번 달')
        next(b for b in self.app.button if b.label=='주문안 검토하기').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.sidebar.radio[0].value,'주문안')

    def test_mobile_menu_and_date_stay_in_sync_with_sidebar(self):
        next(box for box in self.app.selectbox if box.label=='메뉴').set_value('전략실').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.sidebar.radio[0].value,'전략실')
        self.app.sidebar.date_input[0].set_value(DAY).run()
        self.assertEqual(self.app.date_input[0].value,DAY)

    def test_mobile_account_quantity_updates_only_selected_holding(self):
        before=self.app.session_state['holdings'].copy()
        first=before.iloc[0]
        label=f'{first["name"]} · {first.ticker} ({"원" if first.ticker=="CASH" else "주"})'
        next(widget for widget in self.app.text_input if widget.label==label).set_value('1,234').run()
        next(button for button in self.app.button if button.label=='선택 계좌 보유내역 적용').click().run()
        self.assertFalse(self.app.exception)
        after=self.app.session_state['holdings']
        self.assertEqual(after.iloc[0].shares,1234.)
        pd.testing.assert_frame_equal(after.iloc[1:].reset_index(drop=True),
                                      before.iloc[1:].reset_index(drop=True))

    def test_holding_drafts_survive_account_and_page_changes_until_applied(self):
        first=holdings()
        second=holdings().assign(strategy='B',account='다른 계좌')
        original=pd.concat([first,second],ignore_index=True)
        self.app.session_state['holdings']=original.copy()
        self.app.session_state['strategies']=pd.concat([strategies(),strategies().assign(code='B')],ignore_index=True)
        self.app.run()
        self.app.text_input(key='mobile_qty_1_0').set_value('1,234').run()
        self.app.selectbox(key='mobile_holdings_account').set_value(('B','다른 계좌')).run()
        self.app.text_input(key='mobile_qty_1_3').set_value('56').run()
        self.navigate('주문안')
        self.assertFalse(any('class="order-list"' in block.value for block in self.app.markdown))
        self.navigate('이번 달')
        self.app.selectbox(key='mobile_holdings_account').set_value(('A','계좌')).run()
        self.assertEqual(self.app.text_input(key='mobile_qty_1_0').value,'1,234')
        pd.testing.assert_frame_equal(self.app.session_state['holdings'],original)
        self.assertTrue(next(b for b in self.app.button if b.label=='2 · 지정일 종가 조회·판정').disabled)
        next(b for b in self.app.button if b.label=='선택 계좌 보유내역 적용').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state['holdings'].iloc[0].shares,1234.)
        self.assertEqual(self.app.session_state['holdings'].iloc[3].shares,10.)
        self.assertEqual(len(self.app.session_state['holding_drafts']),1)
        self.app.selectbox(key='mobile_holdings_account').set_value(('B','다른 계좌')).run()
        self.assertEqual(self.app.text_input(key='mobile_qty_2_3').value,'56')
        next(b for b in self.app.button if b.label=='입력 취소').click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.session_state['holding_drafts'])
        self.assertEqual(self.app.session_state['holdings'].iloc[3].shares,10.)
        self.assertFalse(next(b for b in self.app.button if b.label=='2 · 지정일 종가 조회·판정').disabled)

    def test_new_date_requires_new_evaluation_or_return_to_saved_date(self):
        self.with_run();self.navigate('주문안')
        self.app.sidebar.date_input[0].set_value(date(2026,6,16)).run()
        self.assertFalse(self.app.exception)
        self.assertFalse(any('class="order-list"' in block.value for block in self.app.markdown))
        self.assertFalse(any(b.label=='평가 확정하고 체결 입력' for b in self.app.button))
        next(b for b in self.app.button if b.label=='기존 평가일로 돌아가기').click().run()
        self.assertEqual(self.app.sidebar.date_input[0].value,DAY)
        self.assertEqual(self.app.date_input[0].value,DAY)
        self.assertTrue(any('class="order-list"' in block.value for block in self.app.markdown))

    def test_pending_input_hides_old_orders_and_blocks_strategy_application(self):
        self.with_run()
        next(widget for widget in self.app.text_input if widget.label=='주식 · 360750 (주)').set_value('12').run()
        self.navigate('주문안')
        self.assertFalse(any('class="order-list"' in block.value for block in self.app.markdown))
        self.assertTrue(any(b.label=='보유수량 입력으로 돌아가기' for b in self.app.button))
        self.navigate('전략실')
        self.assertTrue(next(b for b in self.app.button if b.label=='검토한 규칙 적용').disabled)
        self.assertTrue(any('입력 중인 보유수량' in warning.value for warning in self.app.warning))

    def test_account_decision_opens_only_that_accounts_orders(self):
        h=pd.concat([holdings(),holdings().assign(strategy='B',account='다른 계좌',name=lambda df:'다른 '+df['name'])],ignore_index=True)
        s=pd.concat([strategies(),strategies().assign(code='B')],ignore_index=True)
        self.app.session_state['holdings']=h;self.app.session_state['strategies']=s
        self.app.session_state['run']=run_evaluation(h,s,DAY,fetch=fetch,now=NOW)
        self.app.sidebar.date_input[0].set_value(DAY).run()
        self.app.button(key='account_orders_B').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.selectbox(key='order_account').value,'B')
        cards=next(block.value for block in self.app.markdown if 'class="order-list"' in block.value)
        self.assertIn('다른 주식',cards)
        self.assertNotIn('>주식</strong>',cards)

    def test_order_review_freezes_evaluation_before_unlocking_execution(self):
        self.with_run();self.navigate('주문안')
        before=self.app.session_state['holdings'].copy()
        self.assertFalse(any(b.label=='검증한 실제 체결만 반영' for b in self.app.button))
        next(b for b in self.app.button if b.label=='평가 확정하고 체결 입력').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state['evaluations'].run_id.nunique(),1)
        self.assertEqual(len(self.app.session_state['snapshots']),3)
        self.assertTrue(self.app.session_state['actions'].empty)
        pd.testing.assert_frame_equal(self.app.session_state['holdings'],before)
        self.assertTrue(any(b.label=='검증한 실제 체결만 반영' for b in self.app.button))
        self.assertFalse(any(b.label=='평가 확정하고 체결 입력' for b in self.app.button))

    def test_partial_completed_and_cancelled_orders_show_only_remaining_quantity(self):
        self.with_run()
        run=self.app.session_state['run']
        workspace={key:self.app.session_state[key].copy() for key in TABLES}
        workspace,_=freeze_run(run,workspace)
        fills=execution_draft(run)
        buy=fills.index[fills['구분'].eq('매수')][0]
        sell=fills.index[fills['구분'].eq('매도')][0]
        proposed=float(fills.loc[buy,'제안수량'])
        self.assertGreater(proposed,1)
        fills.loc[buy,['실행','실제수량','실제단가','실제환율','실제체결금액','체결일']]=[True,1,100,1,100,'2026-06-16']
        sell_qty=abs(float(fills.loc[sell,'제안수량']))
        fills.loc[sell,['실행','실제수량','실제단가','실제환율','실제체결금액','체결일']]=[True,sell_qty,100,1,sell_qty*100,'2026-06-16']
        workspace=apply_executions(workspace,fills,run)
        for key,value in workspace.items():self.app.session_state[key]=value
        self.navigate('주문안')
        cards=next(block.value for block in self.app.markdown if 'class="order-list"' in block.value)
        self.assertIn(f'+{proposed-1:g}주',cards)
        self.assertIn('부분 체결',cards)
        self.assertNotIn('>채권</strong>',cards)
        self.assertEqual(float(self.app.session_state['run']['plan'].loc[buy,'제안수량']),proposed)
        workspace=cancel_orders(workspace,run,[fills.loc[buy,'주문ID']],'잔여 취소')
        for key,value in workspace.items():self.app.session_state[key]=value
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('입력할 주문 0개'==heading.value for heading in self.app.subheader))

    def test_saved_evaluation_reopens_with_matching_date(self):
        self.with_run()
        run=self.app.session_state['run']
        workspace={key:self.app.session_state[key].copy() for key in TABLES}
        workspace,_=freeze_run(run,workspace)
        for key,value in workspace.items():self.app.session_state[key]=value
        self.navigate('기록')
        self.app.sidebar.date_input[0].set_value(date(2026,6,16)).run()
        next(b for b in self.app.button if b.label=='확정한 평가·주문안 불러오기').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.sidebar.radio[0].value,'주문안')
        self.assertEqual(self.app.sidebar.date_input[0].value,DAY)
        self.assertEqual(self.app.date_input[0].value,DAY)

    def test_rule_builder_links_to_price_lookup_without_losing_draft(self):
        self.navigate('전략실')
        next(widget for widget in self.app.number_input if widget.label=='기간(개월)').set_value(7).run()
        code=self.app.session_state['studio_code']
        next(b for b in self.app.button if b.label=='이번 달에서 종가 확인').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.sidebar.radio[0].value,'이번 달')
        self.navigate('전략실')
        self.assertEqual(self.app.session_state[f'studio_{code}_1.0']['conditions'][0]['months'],7)

    def test_rule_builder_is_available_before_price_lookup(self):
        self.navigate('전략실')
        self.assertTrue(any(box.label=='편집할 전략' for box in self.app.selectbox))
        self.assertTrue(any('규칙 문장 미리보기' in block.value for block in self.app.markdown))
        self.assertTrue(next(button for button in self.app.button if button.label=='검토한 규칙 적용').disabled)
        next(button for button in self.app.button if button.label=='이 조건 삭제').click().run()
        self.assertFalse(self.app.exception)
        code=self.app.session_state['studio_code']
        self.assertEqual(self.app.session_state[f'studio_{code}_1.0']['conditions'],[])
        next(button for button in self.app.button if button.label=='＋ 조건 추가').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.session_state[f'studio_{code}_1.0']['conditions']),1)

    def test_rule_preview_uses_names_and_escapes_user_text(self):
        spec={'scope':{'run':'monthly'},
              'conditions':[{'op':'sma_above','ticker':'QQQ','months':10}],
              'onPass':{'action':'buy_cash_pct','params':{'ticker':'QQQ','pct':50}},
              'onFail':{'action':'notify','params':{'message':'<script>alert(1)</script>'}}}
        preview=rule_preview_html(spec,{'QQQ':'나스닥 ETF'})
        self.assertIn('나스닥 ETF',preview)
        self.assertIn('10',preview)
        self.assertIn('충족하면',preview)
        self.assertNotIn('<script>',preview)

    def test_switching_to_momentum_rank_uses_selected_winner(self):
        self.navigate('전략실')
        next(box for box in self.app.selectbox if box.label=='조건 종류').set_value('mom_rank').run()
        self.assertFalse(self.app.exception)
        code=self.app.session_state['studio_code']
        spec=self.app.session_state[f'studio_{code}_1.0']
        self.assertEqual(spec['conditions'][0]['ticker'],'__winner__')
        next(box for box in self.app.text_input if box.label=='후보 티커 추가 (쉼표 구분)').set_value('SPY').run()
        self.assertFalse(self.app.exception)
        self.assertIn('SPY',self.app.session_state[f'studio_{code}_1.0']['conditions'][0]['tickers'])

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
            app.sidebar.radio[0].set_value('이번 달').run()
            next(widget for widget in app.text_input if widget.label=='주식 · 360750 (주)').set_value('12').run()
            app.sidebar.radio[0].set_value('설정').run()
            next(b for b in app.button if b.label=='Sheets에 저장').click().run()
            save.assert_not_called()
            self.assertTrue(any('입력 중인 보유수량' in warning.value for warning in app.warning))
            app.sidebar.radio[0].set_value('이번 달').run()
            next(b for b in app.button if b.label=='입력 취소').click().run()
            app.sidebar.radio[0].set_value('설정').run()
            next(b for b in app.button if b.label=='Sheets에 저장').click().run()
            self.assertFalse(app.exception);save.assert_called_once()
            self.assertEqual(app.session_state['remote_token'],'saved')

if __name__=='__main__':unittest.main()
