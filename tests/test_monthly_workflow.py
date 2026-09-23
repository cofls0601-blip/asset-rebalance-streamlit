import unittest
from datetime import date
import json

import pandas as pd

from streamlit_app.data import (
    export_category_month,
    export_month,
    next_holdings_after_execution,
    normalize_holdings,
)
import streamlit_app.engine as engine
from streamlit_app.engine import (
    category_history,
    prior_month_comparison,
    resolved_market,
    validate_market_data,
    validate_snapshot_history,
    yahoo_symbol,
)


HOLDING_COLUMNS = ["strategy", "account", "ticker", "name", "market", "category", "role", "target_pct", "shares"]


def holdings(rows):
    return pd.DataFrame(rows, columns=HOLDING_COLUMNS)


class MonthlyWorkflowTests(unittest.TestCase):
    def test_configured_sma_period_is_used_and_price_date_is_kept(self):
        source = holdings([["A", "계좌", "AAA", "주식", "KR", "주식", "", 100, 1]])
        strategies = pd.DataFrame([{"code": "A", "rule": "sma_filter_rebalance", "params_json": json.dumps({"sma_months": 3})}])
        index = pd.date_range("2026-01-31", periods=5, freq="ME")
        original = engine._series
        engine._series = lambda *args, **kwargs: pd.Series([10, 20, 30, 40, 50], index=index)
        try:
            priced, warnings = engine.enrich_prices(source, date(2026, 5, 31), strategies=strategies)
        finally:
            engine._series = original
        self.assertFalse(warnings)
        self.assertEqual(priced.iloc[0]["sma_period"], 3)
        self.assertEqual(priced.iloc[0]["sma10"], 40)
        self.assertEqual(priced.iloc[0]["price_date"].date(), date(2026, 5, 31))

    def test_cash_is_case_insensitive_and_valued_as_entered(self):
        frame = holdings([["A", "계좌", " cash ", "현금", "KR", "현금", "", 0, 1_250_000]])
        normalized = normalize_holdings(frame)
        self.assertEqual(normalized.iloc[0]["ticker"], "CASH")
        self.assertEqual(normalized.iloc[0]["shares"], 1_250_000)

    def test_english_us_ticker_is_not_converted_to_korean_symbol(self):
        self.assertEqual(resolved_market("QQQ", "KR"), "US")
        self.assertEqual(yahoo_symbol("QQQ", "KR"), "QQQ")
        self.assertEqual(yahoo_symbol("360750", "KR"), "360750.KS")

    def test_english_ticker_uses_usd_fx_and_cash_price_is_one(self):
        source = holdings([
            ["A", "계좌", "QQQ", "나스닥", "KR", "선진국 주식", "", 50, 1],
            ["A", "계좌", "CASH", "현금", "KR", "현금", "", 50, 1000],
        ])
        index = pd.date_range("2025-01-31", periods=14, freq="ME")
        original = engine._series
        def fake_series(ticker, market, *args, **kwargs):
            if ticker == "KRW=X":
                return pd.Series([1300.0, 1350.0], index=index[-2:])
            self.assertEqual((ticker, market), ("QQQ", "US"))
            return pd.Series(range(100, 114), index=index, dtype=float)
        engine._series = fake_series
        try:
            priced, warnings = engine.enrich_prices(source, date(2026, 2, 28))
        finally:
            engine._series = original
        self.assertFalse(warnings)
        qqq = priced[priced["ticker"] == "QQQ"].iloc[0]
        cash = priced[priced["ticker"] == "CASH"].iloc[0]
        self.assertEqual(qqq["fx"], 1350)
        self.assertEqual(cash["close"], 1)
        self.assertEqual(cash["fx"], 1)

    def test_market_validation_blocks_missing_price_and_fx(self):
        priced = pd.DataFrame([
            {"strategy": "A", "ticker": "KR", "market": "KR", "close": 0, "fx": 1, "price_date": pd.NaT},
            {"strategy": "A", "ticker": "US", "market": "US", "close": 100, "fx": 0, "price_date": "2026-09-20"},
            {"strategy": "A", "ticker": "CASH", "market": "KR", "close": 1, "fx": 1, "price_date": "2026-09-21"},
        ])
        errors, _ = validate_market_data(priced, date(2026, 9, 21))
        self.assertTrue(any("유효한 종가" in item for item in errors))
        self.assertTrue(any("환율" in item for item in errors))

    def test_prior_month_comparison_uses_latest_date_before_as_of(self):
        view = pd.DataFrame([
            {"strategy": "A", "평가액": 1_100},
            {"strategy": "B", "평가액": 2_000},
        ])
        snapshots = pd.DataFrame([
            {"date": "2026-07-31", "strategy": "A", "value": 900},
            {"date": "2026-08-31", "strategy": "A", "value": 1_000},
            {"date": "2026-08-31", "strategy": "B", "value": 2_000},
        ])
        result, prior_date = prior_month_comparison(view, snapshots, date(2026, 9, 30))
        row = result[result["전략"] == "A"].iloc[0]
        self.assertEqual(prior_date.date(), date(2026, 8, 31))
        self.assertEqual(row["증감액"], 100)
        self.assertEqual(row["증감률(%)"], 10)

    def test_category_history_reconciles_to_100_percent(self):
        snapshots = pd.DataFrame([
            {"date": "2026-08-31", "category": "주식", "value": 750},
            {"date": "2026-08-31", "category": "현금", "value": 250},
        ])
        result = category_history(snapshots)
        self.assertAlmostEqual(result["weight_pct"].sum(), 100)
        self.assertEqual(dict(zip(result["category"], result["value"])), {"주식": 750, "현금": 250})

    def test_executed_trades_create_next_holdings_and_adjust_cash(self):
        current = holdings([
            ["A", "계좌", "AAA", "주식", "KR", "선진국 주식", "", 50, 10],
            ["A", "계좌", "CASH", "현금", "KR", "현금", "", 50, 10_000],
        ])
        plan = pd.DataFrame([
            {"실행": True, "전략": "A", "티커": "AAA", "구분": "매수", "실제수량": 2, "실제체결금액": 2_200},
        ])
        view = pd.DataFrame([{"strategy": "A", "ticker": "AAA", "close": 1_000, "fx": 1}])
        updated, warnings = next_holdings_after_execution(current, plan, view)
        self.assertFalse(warnings)
        shares = dict(zip(updated["ticker"], updated["shares"]))
        self.assertEqual(shares["AAA"], 12)
        self.assertEqual(shares["CASH"], 7_800)

    def test_unchecked_trade_does_not_change_holdings(self):
        current = holdings([
            ["A", "계좌", "AAA", "주식", "KR", "주식", "", 100, 10],
            ["A", "계좌", "CASH", "현금", "KR", "현금", "", 0, 1_000],
        ])
        plan = pd.DataFrame([
            {"실행": False, "전략": "A", "티커": "AAA", "구분": "매도", "실제수량": 2, "실제체결금액": 200},
        ])
        updated, _ = next_holdings_after_execution(current, plan, pd.DataFrame())
        self.assertEqual(updated["shares"].tolist(), [10, 1_000])

    def test_oversell_is_rejected(self):
        current = holdings([
            ["A", "계좌", "AAA", "주식", "KR", "주식", "", 100, 1],
            ["A", "계좌", "CASH", "현금", "KR", "현금", "", 0, 0],
        ])
        plan = pd.DataFrame([
            {"실행": True, "전략": "A", "티커": "AAA", "구분": "매도", "실제수량": 2, "실제체결금액": 200},
        ])
        updated, warnings = next_holdings_after_execution(current, plan, pd.DataFrame())
        self.assertEqual(updated.loc[updated["ticker"] == "AAA", "shares"].iloc[0], 1)
        self.assertTrue(any("많이 매도" in item for item in warnings))

    def test_duplicate_or_existing_snapshot_date_is_flagged(self):
        snapshots = pd.DataFrame([
            {"date": "2026-09-30", "strategy": "A", "ticker": "AAA"},
            {"date": "2026-09-30", "strategy": "A", "ticker": "AAA"},
        ])
        warnings = validate_snapshot_history(snapshots, date(2026, 9, 30))
        self.assertTrue(any("중복" in item for item in warnings))
        self.assertTrue(any("이미" in item for item in warnings))

    def test_month_exports_keep_existing_sheet_schema_and_asset_summary(self):
        view = pd.DataFrame([{
            "strategy": "A", "account": "계좌", "ticker": "AAA", "name": "주식", "category": "선진국 주식",
            "price_date": pd.Timestamp("2026-09-29"), "close": 1_000.4, "fx": 1, "shares": 10,
            "평가액": 10_004, "전체비중": 100, "target_pct": 100,
        }])
        plan = pd.DataFrame([{
            "전략": "A", "티커": "AAA", "종목": "주식", "구분": "유지", "제안수량": 0,
            "실제수량": 0, "실제체결금액": 0, "예상매매액": 0, "실행": False, "근거": "유지", "메모": "",
        }])
        snapshots, actions = export_month(date(2026, 9, 30), view, plan, "월말")
        summary = export_category_month(date(2026, 9, 30), view, "월말")
        self.assertEqual(list(snapshots.columns), ["date", "saved_at", "strategy", "account", "ticker", "name", "category", "close", "shares", "value", "weight_pct", "target_pct", "strategy_version", "memo"])
        self.assertEqual(list(actions.columns), ["date", "saved_at", "strategy", "ticker", "name", "side", "planned_shares", "actual_shares", "planned_amount", "done", "reason", "memo"])
        self.assertEqual(summary.iloc[0]["value"], 10_004)
        self.assertEqual(summary.iloc[0]["weight_pct"], 100)

    def test_snapshot_keeps_strategy_version(self):
        view = pd.DataFrame([{"strategy":"A","account":"계좌","ticker":"AAA","name":"주식","category":"주식",
                              "close":100,"shares":1,"평가액":100,"전체비중":100,"target_pct":100}])
        plan = pd.DataFrame([{"전략":"A","티커":"AAA","종목":"주식","구분":"유지","제안수량":0,
                              "실제수량":0,"예상매매액":0,"실행":False,"근거":"유지","메모":""}])
        strategies = pd.DataFrame([{"code":"A","version":"2.1"}])
        snapshots, _ = export_month(date(2026, 9, 30), view, plan, "", strategies)
        self.assertEqual(snapshots.iloc[0]["strategy_version"], "2.1")


if __name__ == "__main__":
    unittest.main()
