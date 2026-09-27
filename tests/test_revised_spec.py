import copy
import json
import unittest
from datetime import date
from unittest.mock import patch
import pandas as pd
from streamlit_app.data import DataError, HOLDING_COLUMNS, normalize_holdings, normalize_strategies, read_workbook
from streamlit_app.market import calendar, expected_session, next_trade_day, closed_session
from streamlit_app.workflow import run_evaluation, revise_proposal, classification_view
from streamlit_app.ledger import empty_workspace, freeze_run, execution_draft, apply_executions, backup_bytes, restore_backup, latest_snapshots, load_frozen_run, snapshots_match, cancel_orders, order_status
from streamlit_app.performance import summarize, monthly_risk, benchmark_index
from streamlit_app.rules import due, evaluate

DAY=date(2026,6,15)
NOW=pd.Timestamp('2026-06-16T12:00:00Z')

def holdings(cash=1000, stock=10):
    return normalize_holdings(pd.DataFrame([
        ['A','계좌','360750','주식','KR','선진국 주식','성장',60,stock],
        ['A','계좌','148070','채권','KR','선진국 채권','방어',30,10],
        ['A','계좌','CASH','현금','KR','현금','대기',10,cash]],columns=HOLDING_COLUMNS))

def strategies(params=None,rule='static'):
    return normalize_strategies(pd.DataFrame([{'code':'A','rule':rule,'params_json':json.dumps(params or {})}]))

def fetch(ticker,market,day,adjusted=False):
    dates=calendar(market,day.year).sessions_in_range(pd.Timestamp(day)-pd.Timedelta(days=500),pd.Timestamp(day))
    value=1300. if ticker=='KRW=X' else 50. if adjusted else 100.
    return pd.Series(value,index=dates)

def run(h=None,s=None):
    return run_evaluation(holdings() if h is None else h,strategies() if s is None else s,DAY,fetch=fetch,now=NOW)

def ws(r):
    w=empty_workspace();w['holdings']=r['holdings'];w['strategies']=r['strategies'];return w

class RevisedSpecTests(unittest.TestCase):
    def test_raw_close_not_adjusted_close_values_holdings(self):
        r=run(s=strategies({'signal_adjusted':True}));self.assertFalse(r['errors'])
        stock=r['view'].query('ticker == "360750"').iloc[0]
        self.assertEqual(stock.close,100);self.assertEqual(stock.signal_close,50)
        self.assertEqual(stock['평가액'],1000)

    def test_cash_is_one_and_totals_reconcile(self):
        r=run();self.assertEqual(r['view']['평가액'].sum(),3000)
        cash=r['view'].query('ticker == "CASH"').iloc[0];self.assertEqual(cash.close,1);self.assertEqual(cash.fx,1)

    def test_no_sale_proceeds_used_for_buys(self):
        r=run(h=holdings(cash=0,stock=0));p=r['plan'].set_index('티커')
        self.assertLess(p.loc['148070','제안수량'],0)
        self.assertEqual(p.loc['360750','제안수량'],0)
        self.assertTrue(p.loc['360750','현금제약'])

    def test_integer_lots_and_tolerance(self):
        s=strategies();s['tolerance_pct']=100
        r=run(s=s);self.assertTrue(r['plan']['제안수량'].eq(0).all())
        r=run(h=holdings(cash=151));self.assertTrue((r['plan']['제안수량']%1).eq(0).all())
        self.assertLessEqual(r['plan'].query('구분 == "매수"')['예상매매액'].sum(),151)

    def test_user_date_and_quarter_gate(self):
        self.assertTrue(due(date(2026,6,15),'quarterly'))
        self.assertFalse(due(date(2026,5,15),'quarterly'))
        self.assertTrue(due(date(2026,5,15),'monthly'))
        self.assertTrue(due(date(2026,5,15),'months',[5]))

    def test_bad_account_does_not_block_good_one(self):
        h=holdings();bad=h.copy();bad['strategy']='B';bad.loc[bad.ticker.eq('360750'),'ticker']='INVALID'
        s=pd.concat([strategies(),strategies().assign(code='B')],ignore_index=True)
        def get(t,m,d,a=False):
            if t=='INVALID':raise ValueError('종목 없음')
            return fetch(t,m,d,a)
        r=run_evaluation(pd.concat([h,bad]),s,DAY,fetch=get,now=NOW)
        self.assertEqual(set(r['view'].strategy),{'A'});self.assertIn('B',r['errors'])

    def test_duplicate_negative_non_numeric_inputs_rejected(self):
        for value in [-1,'oops',float('inf')]:
            h=holdings();h.loc[0,'shares']=value
            with self.assertRaises(DataError):normalize_holdings(h)
        with self.assertRaises(DataError):normalize_holdings(pd.concat([holdings(),holdings()]))

    def test_frozen_run_is_idempotent_and_revisions_select_latest(self):
        r=run();w,added=freeze_run(r,ws(r));self.assertTrue(added)
        again,added=freeze_run(r,w);self.assertFalse(added);self.assertEqual(len(w['snapshots']),len(again['snapshots']))
        changed=run(h=holdings(cash=2000))
        with self.assertRaises(DataError):freeze_run(changed,w)
        new,_=freeze_run(changed,w,revision_reason='잔고 수정')
        self.assertEqual(len(new['snapshots']),6);self.assertEqual(len(latest_snapshots(new['snapshots'])),3)
        self.assertEqual(latest_snapshots(new['snapshots']).value.sum(),4000)

    def test_backup_restores_exact_identifiers_and_frozen_sources(self):
        r=run();w,_=freeze_run(r,ws(r))
        restored=restore_backup(backup_bytes(w))
        self.assertEqual(restored['snapshots'].record_id.tolist(),w['snapshots'].record_id.tolist())
        payload=load_frozen_run(restored['evaluations'],r['id'])
        self.assertTrue(payload['observations']);self.assertEqual(payload['engine_version'],r['engine_version'])
        pd.testing.assert_frame_equal(restored['holdings'],w['holdings'],check_dtype=False)

    def test_missing_sheet_is_not_silently_empty(self):
        with patch('streamlit_app.data.pd.read_csv',side_effect=OSError('network')):
            with self.assertRaises(DataError):read_workbook('https://docs.google.com/spreadsheets/d/example/edit')

    def test_fills_roundtrip_atomic_and_duplicate_blocked(self):
        r=run();w,_=freeze_run(r,ws(r));draft=execution_draft(r)
        draft['実']=0 # unrecognized extra field has no meaning
        idx=draft[draft['구분'].eq('매수')].index[0]
        draft.loc[idx,['실행','실제수량','실제단가','실제환율','실제체결금액','체결일']]=[True,1,100,1,100,'2026-06-16']
        updated=apply_executions(w,draft,r)
        self.assertEqual(updated['holdings'].query('ticker == "CASH"').shares.iloc[0],900)
        self.assertEqual(updated['snapshots'].value.sum(),3000)
        with self.assertRaises(DataError):apply_executions(updated,draft,r)
        restored=restore_backup(backup_bytes(updated))
        self.assertEqual(restored['actions'].actual_amount.iloc[0],100)
        self.assertEqual(restored['actions'].execution_date.iloc[0],'2026-06-16')
        bad=draft.copy();bad.loc[idx,'실제체결금액']=500
        with self.assertRaises(DataError):apply_executions(w,bad,r)
        self.assertEqual(w['holdings'].query('ticker == "CASH"').shares.iloc[0],1000)

    def test_order_revision_respects_budget_and_preserves_original(self):
        r=run();edit=r['plan'][['주문ID','제안수량']].copy();i=edit.index[0]
        edit.loc[i,'제안수량']=10000
        with self.assertRaises(DataError):revise_proposal(r,edit,'변경')
        edit.loc[i,'제안수량']=1
        changed=revise_proposal(r,edit,'수량 축소')
        self.assertNotEqual(changed['id'],r['id']);self.assertIn('original_plan',changed)

    def test_calendar_holidays_and_pending_close(self):
        self.assertEqual(expected_session(date(2026,7,5),'US').date(),date(2026,7,2))
        self.assertEqual(next_trade_day(date(2026,7,2),'US'),date(2026,7,6))
        with self.assertRaises(ValueError):closed_session(DAY,'KR','2026-06-15T00:00:00Z')

    def test_unchanged_inputs_reproduce_run_id(self):
        self.assertEqual(run()['id'],run()['id'])

    def test_short_signal_is_unknown_and_no_fail_orders(self):
        s=strategies({'sma_months':36,'sma_tickers':['360750']},'sma_filter_rebalance')
        r=run(s=s);self.assertIn('A',r['errors']);self.assertTrue(r['plan'].empty)

    def test_mix_classification_preserves_total(self):
        r=run();v=r['view'].copy();v['classification_json']=''
        v.loc[0,'classification_json']='{"선진국 주식":50,"선진국 채권":50}'
        self.assertEqual(classification_view(v)['평가액'].sum(),v['평가액'].sum())

    def test_dietz_uses_timed_cashflows_and_xirr_initial_value(self):
        snaps=pd.DataFrame([{'date':'2026-01-01','strategy':'A','ticker':'CASH','value':100},
                            {'date':'2026-02-01','strategy':'A','ticker':'CASH','value':200}])
        flows=pd.DataFrame([{'date':'2026-01-16','amount':100,'strategy':'A','kind':'external'}])
        eq,m=summarize(snaps,flows);self.assertEqual(m['total_return'],0);self.assertAlmostEqual(m['xirr'],0)
        self.assertEqual(eq.profit.iloc[-1],0)

    def test_internal_transfers_net_to_zero(self):
        snaps=pd.DataFrame([{'date':d,'strategy':c,'ticker':'CASH','value':v} for d,c,v in [
            ('2026-01-01','A',100),('2026-01-01','B',100),('2026-02-01','A',50),('2026-02-01','B',150)]])
        flows=pd.DataFrame([{'date':'2026-01-15','strategy':c,'amount':v,'kind':'transfer','transfer_id':'T'} for c,v in [('A',-50),('B',50)]])
        _,m=summarize(snaps,flows);self.assertEqual(m['total_return'],0)

    def test_backup_restores_unconfirmed_draft_and_manual_prices(self):
        r=run();fills=execution_draft(r);fills['실제수량']=1.
        drafts={'run':r,'fills':fills,'overrides':{'A:360750':{'close':100,'date':str(DAY),'source':'manual','reason':'check'}}}
        restored,work=restore_backup(backup_bytes(ws(r),drafts),include_drafts=True)
        self.assertEqual(work['run']['id'],r['id'])
        pd.testing.assert_frame_equal(work['run']['plan'],r['plan'],check_dtype=False)
        self.assertEqual(work['fills']['실제수량'].sum(),len(fills))
        self.assertEqual(work['overrides'],drafts['overrides'])
        self.assertTrue(all(len(v.columns)>0 for v in empty_workspace().values()))

    def test_sheets_chunked_evaluation_and_value_reconciliation(self):
        r=run();r['observations'].append({'long':'검증'*50000})
        w,_=freeze_run(r,ws(r));saved=w['evaluations']
        self.assertLessEqual(saved.payload_json.str.len().max(),20000)
        self.assertEqual(load_frozen_run(saved,r['id'])['observations'],r['observations'])
        with self.assertRaises(DataError):load_frozen_run(saved.iloc[:-1],r['id'])
        self.assertTrue(snapshots_match(w['snapshots'],w['snapshots']))
        corrupted=w['snapshots'].copy();corrupted.loc[0,'value']+=1
        self.assertFalse(snapshots_match(w['snapshots'],corrupted))
        w['evaluations']=empty_workspace()['evaluations']
        _,added=freeze_run(r,w);self.assertFalse(added)

    def test_same_count_different_accounts_cannot_make_total_performance(self):
        snaps=pd.DataFrame([{'date':d,'strategy':c,'ticker':'CASH','value':100} for d,c in [('2026-01-01','A'),('2026-02-01','B')]])
        with self.assertRaises(DataError):summarize(snaps,pd.DataFrame())

    def test_scope_switch_only_moves_selected_role(self):
        r=run();spec={'scope':{'run':'monthly'},'conditions':[{'op':'schedule'}],
          'onPass':{'action':'switch_scope','params':{'role':'성장','ticker':'CASH'}}}
        result=evaluate(spec,r['view'],DAY,lambda t,m,d:fetch(t,m,d))
        self.assertEqual(result['targets'],{'360750':0,'148070':1000,'CASH':2000})
        spec['onPass']={'action':'restore_scope','params':{'tickers':['360750']}}
        result=evaluate(spec,r['view'],DAY,lambda t,m,d:fetch(t,m,d))
        self.assertEqual(result['targets'],{'360750':1800,'148070':1000,'CASH':200})

    def test_future_published_indicator_blocks_both_branches(self):
        r=run();spec={'conditions':[{'op':'external_above','value':3,'threshold':2,'source':'manual','observed_date':'2026-05-01','published_date':'2026-06-16'}],
          'onPass':{'action':'sell_all'},'onFail':{'action':'sell_all'}}
        result=evaluate(spec,r['view'],DAY,lambda t,m,d:fetch(t,m,d))
        self.assertEqual(result['status'],'계산 차단');self.assertEqual(result['targets']['360750'],1000)

    def test_unknown_rule_is_blocked(self):
        self.assertIn('A',run(s=strategies(rule='typo'))['errors'])

    def test_cancelled_order_cannot_receive_fill(self):
        r=run();w,_=freeze_run(r,ws(r));draft=execution_draft(r);idx=draft.index[0]
        ident=draft.loc[idx,'주문ID'];w=cancel_orders(w,r,[ident],'수동 주문 취소')
        self.assertEqual(order_status(r,w['actions']).set_index('주문ID').loc[ident,'상태'],'취소')
        draft.loc[idx,'실행']=True
        with self.assertRaisesRegex(DataError,'취소된 주문'):apply_executions(w,draft,r)

    def test_monthly_defense_and_quarterly_restore_are_separate(self):
        r=run();day=date(2026,5,15)
        spec={'scope':{'run':'monthly'},'conditions':[{'op':'schedule'}],
            'onPass':{'action':'restore','params':{'restore_frequency':'quarterly'}}}
        result=evaluate(spec,r['view'],day,lambda t,m,d:fetch(t,m,d))
        self.assertEqual(result['status'],'일정 대기');self.assertEqual(result['targets']['360750'],1000)
        spec['onPass']={'action':'switch_scope','params':{'role':'성장','ticker':'CASH'}}
        self.assertEqual(evaluate(spec,r['view'],day,lambda t,m,d:fetch(t,m,d))['targets']['360750'],0)

    def test_risk_metrics_refuse_irregular_or_short_observations(self):
        monthly=pd.DataFrame({'date':pd.date_range('2024-01-31',periods=13,freq='ME'),'return':[0]+[.01,-.01]*6})
        self.assertAlmostEqual(monthly_risk(monthly)['sharpe'],0.)
        self.assertIsNotNone(monthly_risk(monthly)['volatility'])
        irregular=monthly.copy();irregular.loc[3,'date']+=pd.Timedelta(days=3)
        self.assertIsNone(monthly_risk(irregular)['volatility'])
        self.assertIsNone(monthly_risk(monthly.iloc[:5])['sharpe'])

    def test_benchmark_aligns_krw_and_rejects_missing_initial_price(self):
        dates=pd.to_datetime(['2026-05-15','2026-06-15'])
        result=benchmark_index('SPY',dates,fetch)
        self.assertEqual(result.benchmark.tolist(),[100,100])
        with self.assertRaises(DataError):benchmark_index('SPY',pd.to_datetime(['2020-01-01','2026-06-15']),fetch)

if __name__=='__main__':unittest.main()
