import json
import sys
import types
import unittest
from datetime import date

import pandas as pd

if "yfinance" not in sys.modules:
    sys.modules["yfinance"] = types.SimpleNamespace(download=lambda *args, **kwargs: pd.DataFrame())

from streamlit_app.engine import build_action_plan


def strategies(code, rule, params):
    return pd.DataFrame([{"code": code, "rule": rule, "params_json": json.dumps(params)}])


def view(rows):
    defaults = {"account": "", "market": "KR", "category": "기타", "role": "", "target_pct": 0,
                "shares": 1, "close": 1, "fx": 1, "sma10": None, "momentum12": None,
                "drawdown120": None, "현재비중": 0, "전체비중": 0, "괴리": 0}
    return pd.DataFrame([{**defaults, **row} for row in rows])


class StrategyRuleTests(unittest.TestCase):
    def assert_balanced(self, plan, total):
        self.assertAlmostEqual(plan["목표평가액"].sum(), total, places=4)
        self.assertAlmostEqual(plan["예상매매액"].sum(), 0, places=4)

    def test_sso_treats_153130_as_defensive_asset(self):
        rows = view([
            {"strategy": "SSO", "ticker": "360750", "name": "S&P500", "평가액": 600, "drawdown120": -.05},
            {"strategy": "SSO", "ticker": "153130", "name": "단기채", "평가액": 400},
        ])
        params = {"signal": {"ticker": "360750", "market": "KR"}, "threshold": -.15,
                  "normal_stock_pct": 70, "triggered_stock_pct": 85}
        plan = build_action_plan(rows, strategies("SSO", "drawdown_shift", params), date(2026, 9, 30))
        targets = dict(zip(plan["티커"], plan["목표평가액"]))
        self.assertEqual(targets["360750"], 700)
        self.assertEqual(targets["153130"], 300)
        self.assert_balanced(plan, 1000)

    def test_sso_trigger_moves_to_85_15(self):
        rows = view([
            {"strategy": "SSO", "ticker": "360750", "name": "S&P500", "평가액": 700, "drawdown120": -.20},
            {"strategy": "SSO", "ticker": "153130", "name": "단기채", "평가액": 300},
        ])
        params = {"signal": {"ticker": "360750", "market": "KR"}, "threshold": -.15,
                  "normal_stock_pct": 70, "triggered_stock_pct": 85}
        plan = build_action_plan(rows, strategies("SSO", "drawdown_shift", params), date(2026, 9, 30))
        targets = dict(zip(plan["티커"], plan["목표평가액"]))
        self.assertEqual(targets["360750"], 850)
        self.assertEqual(targets["153130"], 150)
        self.assert_balanced(plan, 1000)

    def test_gsm_keeps_assets_with_missing_signal(self):
        rows = view([
            {"strategy": "GSM", "ticker": "A", "name": "winner", "평가액": 200, "close": 110, "sma10": 100, "momentum12": .20},
            {"strategy": "GSM", "ticker": "B", "name": "missing", "평가액": 100},
            {"strategy": "GSM", "ticker": "CASH", "name": "cash", "평가액": 700},
        ])
        params = {"winner_share": .8, "cash_winner_share": .2}
        plan = build_action_plan(rows, strategies("GSM", "momentum_rotate", params), date(2026, 9, 30))
        targets = dict(zip(plan["티커"], plan["목표평가액"]))
        self.assertEqual(targets["B"], 100)
        self.assertEqual(targets["A"], 720)
        self.assertEqual(targets["CASH"], 180)
        self.assert_balanced(plan, 1000)

    def test_laa_nonquarter_breach_balances_to_cash(self):
        rows = view([
            {"strategy": "LAA", "ticker": "A", "name": "filtered", "평가액": 300, "target_pct": 30, "close": 90, "sma10": 100},
            {"strategy": "LAA", "ticker": "B", "name": "held", "평가액": 500, "target_pct": 50, "close": 110, "sma10": 100},
            {"strategy": "LAA", "ticker": "CASH", "name": "cash", "평가액": 200, "target_pct": 20},
        ])
        plan = build_action_plan(rows, strategies("LAA", "sma_filter_rebalance", {"sma_tickers": ["A"]}), date(2026, 8, 31))
        targets = dict(zip(plan["티커"], plan["목표평가액"]))
        self.assertEqual(targets["A"], 0)
        self.assertEqual(targets["B"], 500)
        self.assertEqual(targets["CASH"], 500)
        self.assert_balanced(plan, 1000)

    def test_isa_trigger_uses_half_of_cash(self):
        rows = view([
            {"strategy": "ISA", "ticker": "418660", "name": "leveraged", "평가액": 400},
            {"strategy": "ISA", "ticker": "CASH", "name": "cash", "평가액": 600},
        ])
        params = {"signal": {"ticker": "QQQ", "market": "US", "lookback_days": 120}, "threshold": -.10, "buy_fraction": .5}
        import streamlit_app.engine as engine
        original = engine._series
        engine._series = lambda *args, **kwargs: pd.Series([100] * 119 + [85])
        try:
            plan = build_action_plan(rows, strategies("ISA", "drawdown_buy", params), date(2026, 9, 30))
        finally:
            engine._series = original
        targets = dict(zip(plan["티커"], plan["목표평가액"]))
        self.assertEqual(targets["418660"], 700)
        self.assertEqual(targets["CASH"], 300)
        self.assert_balanced(plan, 1000)

    def test_static_and_hold_rules(self):
        rows = view([
            {"strategy": "CORE", "ticker": "A", "name": "A", "평가액": 800, "target_pct": 60},
            {"strategy": "CORE", "ticker": "CASH", "name": "cash", "평가액": 200, "target_pct": 40},
        ])
        static_plan = build_action_plan(rows, strategies("CORE", "static", {}), date(2026, 9, 30))
        self.assertEqual(dict(zip(static_plan["티커"], static_plan["목표평가액"])), {"A": 600, "CASH": 400})
        self.assert_balanced(static_plan, 1000)
        hold_plan = build_action_plan(rows, strategies("CORE", "hold", {"hold_note": "유지"}), date(2026, 9, 30))
        self.assertTrue((hold_plan["예상매매액"] == 0).all())

    def test_visual_rule_restores_target_when_condition_passes(self):
        rows = view([
            {"strategy":"V","ticker":"AAA","name":"주식","평가액":400,"target_pct":60,"close":110,"sma10":100,"sma_period":10},
            {"strategy":"V","ticker":"CASH","name":"현금","평가액":600,"target_pct":40},
        ])
        params = {"combine":"AND","conditions":[{"ticker":"AAA","metric":"sma_deviation","period":10,"operator":">","threshold":0}],
                  "on_pass":"target","on_fail":"cash"}
        plan = build_action_plan(rows, strategies("V", "visual", params), date(2026, 9, 30))
        self.assertEqual(dict(zip(plan["티커"], plan["목표평가액"])), {"AAA":600,"CASH":400})
        self.assert_balanced(plan, 1000)

    def test_visual_monthly_schedule_moves_all_to_selected_ticker(self):
        rows = view([
            {"strategy":"V","ticker":"SPY","name":"SPY","market":"US","평가액":500,"target_pct":50},
            {"strategy":"V","ticker":"CASH","name":"현금","평가액":500,"target_pct":50},
        ])
        params = {"conditions":[{"metric":"schedule","schedule":"monthly","operator":">=","threshold":1}],
                  "on_pass":"move_all","on_fail":"hold","target_ticker":"SPY"}
        plan = build_action_plan(rows, strategies("V", "visual", params), date(2026, 9, 30))
        self.assertEqual(dict(zip(plan["티커"], plan["목표평가액"])), {"SPY":1000,"CASH":0})
        self.assert_balanced(plan, 1000)


if __name__ == "__main__":
    unittest.main()
