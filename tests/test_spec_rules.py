import copy
import json
import unittest
from datetime import date
from unittest.mock import patch
import numpy as np
import pandas as pd
from streamlit_app.rules import evaluate, next_run, OPERATORS, ACTIONS
from streamlit_app.engine import build_action_plan


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026,9,30)
        self.index = pd.bdate_range('2024-01-01','2026-09-30')
        self.prices = {'AAA':pd.Series(np.linspace(100,200,len(self.index)),index=self.index),
                       'BBB':pd.Series(np.linspace(100,110,len(self.index)),index=self.index)}
        self.holdings = pd.DataFrame([
            {'strategy':'S','ticker':'AAA','name':'A','평가액':600.,'target_pct':60.,'market':'US','shares':3,'close':200,'fx':1},
            {'strategy':'S','ticker':'BBB','name':'B','평가액':200.,'target_pct':20.,'market':'US','shares':2,'close':110,'fx':1},
            {'strategy':'S','ticker':'CASH','name':'현금','평가액':200.,'target_pct':20.,'market':'KR','shares':200,'close':1,'fx':1}])

    def fetch(self, ticker, *args):
        return self.prices.get(ticker,pd.Series(dtype=float))

    def spec(self, condition=None, action='hold_buy', params=None):
        return {'schema_version':2,'scope':{'run':'monthly','market':'MIX'},
                'conditions':[condition or {'ticker':'AAA','op':'price_above_abs','price':150}],
                'onPass':{'action':action,'params':params or {}},
                'onFail':{'action':'hold_buy','params':{}}}

    def test_all_eleven_operators_have_executable_evidence(self):
        conditions = [
            {'op':'sma_above','months':10}, {'op':'sma_below','months':10},
            {'op':'ema_above','days':200}, {'op':'ema_below','days':200},
            {'op':'dd_below','pct':-10,'lookback':120}, {'op':'dd_above','pct':-10,'lookback':120},
            {'op':'mom_rank','months':12,'rank':1,'tickers':['AAA','BBB']},
            {'op':'price_above_abs','price':150}, {'op':'price_below_abs','price':150},
            {'op':'ticker_gt','tickerB':'BBB','pct':100}, {'op':'schedule','every':'monthend'}]
        self.assertEqual({c['op'] for c in conditions}, set(OPERATORS))
        for c in conditions:
            with self.subTest(op=c['op']):
                result = evaluate(self.spec({'ticker':'AAA',**c}),self.holdings,self.day,self.fetch)
                self.assertNotEqual(result['status'],'계산 차단',result['message'])
                self.assertEqual(len(result['evidence']),1)

    def test_all_eight_actions_preserve_capital(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                result = evaluate(self.spec(action=action,params={'ticker':'AAA','pct':85,'cashPct':20,'message':'점검'}),self.holdings,self.day,self.fetch)
                self.assertEqual(result['action'],action,result['message'])
                self.assertAlmostEqual(sum(result['targets'].values()),1000)
                self.assertTrue(all(v>=0 for v in result['targets'].values()))

    def test_rank_winner_passes_into_sma_and_80_20_allocation(self):
        spec = self.spec({'op':'mom_rank','tickers':['AAA','BBB'],'months':12,'rank':1}, 'move_all', {'ticker':'__winner__','cashPct':20})
        spec['conditions'].append({'ticker':'__winner__','op':'sma_above','months':10,'connector':'AND'})
        result = evaluate(spec,self.holdings,self.day,self.fetch)
        self.assertEqual(result['winner'],'AAA')
        self.assertEqual(result['targets'],{'AAA':800,'BBB':0,'CASH':200})

    def test_pass_and_fail_have_independent_parameters(self):
        spec = self.spec(action='set_weight',params={'ticker':'AAA','pct':85})
        spec['onFail'] = {'action':'set_weight','params':{'ticker':'AAA','pct':70}}
        self.assertEqual(evaluate(spec,self.holdings,self.day,self.fetch)['targets']['AAA'],850)
        spec['conditions'][0]['price'] = 999
        self.assertEqual(evaluate(spec,self.holdings,self.day,self.fetch)['targets']['AAA'],700)

    def test_unknown_signal_blocks_fail_branch(self):
        spec = self.spec({'ticker':'MISSING','op':'sma_above','months':10})
        spec['onFail'] = {'action':'sell_all','params':{}}
        result = evaluate(spec,self.holdings,self.day,self.fetch)
        self.assertEqual(result['status'],'계산 차단')
        self.assertEqual(result['targets']['AAA'],600)

    def test_missing_rank_candidate_blocks_entire_decision(self):
        spec = self.spec({'op':'mom_rank','tickers':['AAA','MISSING'],'months':12,'rank':1},'sell_all')
        self.assertEqual(evaluate(spec,self.holdings,self.day,self.fetch)['status'],'계산 차단')

    def test_schedule_waits_without_fetch_and_next_date_handles_leap_year(self):
        def no_fetch(*args):
            self.fail('Waiting rules must not fetch signals')
        result = evaluate(self.spec(),self.holdings,date(2026,9,23),no_fetch)
        self.assertEqual(result['status'],'일정 대기')
        self.assertEqual(next_run(date(2028,2,1),'monthly'),date(2028,2,29))
        self.assertEqual(next_run(date(2026,9,30),'quarterly'),date(2026,12,31))

    def test_stale_signal_is_blocked(self):
        self.prices['AAA'] = self.prices['AAA'].iloc[:-20]
        self.assertEqual(evaluate(self.spec(),self.holdings,self.day,self.fetch)['status'],'계산 차단')

    def test_missing_cash_or_target_is_blocked(self):
        for action,params in [('sell_all',{}),('move_all',{'ticker':'MISSING'}),('set_weight',{'ticker':'AAA','pct':120})]:
            with self.subTest(action=action):
                result = evaluate(self.spec(action=action,params=params),self.holdings[self.holdings.ticker!='CASH'],self.day,self.fetch)
                self.assertEqual(result['status'],'계산 차단')

    def test_mixed_connectors_use_documented_left_to_right_order(self):
        spec = self.spec()
        spec['conditions'] = [{'ticker':'AAA','op':'price_above_abs','price':300},
                              {'ticker':'AAA','op':'price_above_abs','price':100,'connector':'OR'},
                              {'ticker':'AAA','op':'price_above_abs','price':300,'connector':'AND'}]
        self.assertFalse(evaluate(spec,self.holdings,self.day,self.fetch)['passed'])

    def test_order_engine_matches_studio_exactly(self):
        spec = self.spec(action='set_weight',params={'ticker':'AAA','pct':85})
        strategies = pd.DataFrame([{'code':'S','rule':'visual','params_json':json.dumps(spec)}])
        result = evaluate(spec,self.holdings,self.day,self.fetch)
        plan = build_action_plan(self.holdings,strategies,self.day,signal_fetch=self.fetch)
        self.assertEqual(dict(zip(plan['티커'],plan['목표평가액'])),result['targets'])
        self.assertAlmostEqual(plan['예상매매액'].sum(),0)

    def test_cash_price_and_fraction_action(self):
        spec = self.spec({'ticker':'CASH','op':'price_above_abs','price':1},'buy_cash_pct',{'ticker':'AAA','pct':50})
        result = evaluate(spec,self.holdings,self.day,self.fetch)
        self.assertEqual(result['targets'],{'AAA':700,'BBB':200,'CASH':100})


if __name__ == '__main__':
    unittest.main()
