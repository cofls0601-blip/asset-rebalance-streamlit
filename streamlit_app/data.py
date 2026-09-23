from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

import pandas as pd

HOLDING_COLUMNS = ["strategy", "account", "ticker", "name", "market", "category", "role", "target_pct", "shares"]
STRATEGY_COLUMNS = ["code", "account", "description", "dynamic", "active", "annual_limit", "rule", "params_json",
                    "version", "effective_date", "source", "change_note"]
SNAPSHOT_COLUMNS = ["date", "saved_at", "strategy", "account", "ticker", "name", "category", "close", "shares", "value", "weight_pct", "target_pct", "strategy_version", "memo"]
ACTION_COLUMNS = ["date", "saved_at", "strategy", "ticker", "name", "side", "planned_shares", "actual_shares", "planned_amount", "done", "reason", "memo"]
CASHFLOW_COLUMNS = ["date", "amount", "memo", "strategy"]
CATEGORY_TARGET_COLUMNS = ["category", "target_pct"]


class DataError(RuntimeError):
    pass


def normalize_holdings(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in HOLDING_COLUMNS if column not in frame.columns]
    if missing:
        raise DataError(f"보유내역에 필요한 열이 없습니다: {', '.join(missing)}")
    df = frame.reindex(columns=HOLDING_COLUMNS).copy()
    for column in ["strategy", "account", "ticker", "name", "market", "category", "role"]:
        df[column] = df[column].fillna("").astype(str).str.strip()
    df["market"] = df["market"].str.upper().replace("", "KR")
    raw = df["ticker"].str.replace(r"\.0$", "", regex=True)
    raw = raw.mask(raw.str.upper().eq("CASH"), "CASH")
    is_kr_code = df["market"].eq("KR") & raw.str.fullmatch(r"\d+")
    df["ticker"] = raw.where(~is_kr_code, raw.str.zfill(6))
    for column in ["target_pct", "shares"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def normalize_strategies(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in ["code", "rule", "params_json"] if column not in frame.columns]
    if missing:
        raise DataError(f"전략표에 필요한 열이 없습니다: {', '.join(missing)}")
    df = frame.copy()
    defaults = {"account": "", "description": "", "dynamic": False, "active": True, "annual_limit": 0.0,
                "version": "1.0", "effective_date": "", "source": "", "change_note": ""}
    for column, value in defaults.items():
        if column not in df:
            df[column] = value
    return df.reindex(columns=STRATEGY_COLUMNS).copy()


def load_default_holdings() -> pd.DataFrame:
    return normalize_holdings(pd.read_csv("config/default_holdings.csv", dtype={"ticker": str}))


def load_default_strategies() -> pd.DataFrame:
    with open("config/default_strategies.json", encoding="utf-8") as handle:
        items = json.load(handle)
    accounts = {"LAA": "과세 연금저축", "GSM": "비과세 연금저축", "ISA": "ISA", "SSO": "일반계좌 2", "EM": "일반계좌 1"}
    descriptions = {
        "LAA": "10개월 SMA 필터와 분기말 목표비중 복원", "GSM": "SMA 통과 후보 중 12개월 모멘텀 1위",
        "ISA": "나스닥 낙폭 트리거 분할매수", "SSO": "S&P500 낙폭 트리거 비중전환", "EM": "신흥국 분산 장기보유",
    }
    return pd.DataFrame([{
        "code": item["code"], "account": accounts.get(item["code"], item["code"]),
        "description": descriptions.get(item["code"], ""), "dynamic": item["rule"] == "momentum_rotate",
        "active": True, "annual_limit": 0.0, "rule": item["rule"],
        "params_json": json.dumps(item.get("params", {}), ensure_ascii=False),
        "version": "1.0", "effective_date": "", "source": "", "change_note": "",
    } for item in items], columns=STRATEGY_COLUMNS)


def _google_csv_url(url: str, sheet_name: str | None = None) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        raise DataError("올바른 Google Sheets URL이 아닙니다.")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = (query.get("gid") or fragment.get("gid") or ["0"])[0]
    if sheet_name:
        return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/gviz/tq?tqx=out:csv&sheet={quote(sheet_name)}"
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={gid}"


def read_public_google_sheet(url: str, kind: str = "holdings", sheet_name: str | None = None) -> pd.DataFrame:
    try:
        frame = pd.read_csv(_google_csv_url(url, sheet_name), dtype={"ticker": str})
    except Exception as exc:
        raise DataError("시트를 읽지 못했습니다. 링크 공유가 '링크가 있는 모든 사용자: 뷰어'인지 확인하세요.") from exc
    return normalize_holdings(frame) if kind == "holdings" else normalize_strategies(frame)


def read_optional_sheet(url: str, sheet_name: str, columns: list[str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(_google_csv_url(url, sheet_name), dtype={"ticker": str})
        if frame.empty and not len(frame.columns):
            return pd.DataFrame(columns=columns)
        # New optional fields are added without making existing user sheets unreadable.
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame.reindex(columns=columns)
    except Exception:
        return pd.DataFrame(columns=columns)


def read_workbook(url: str) -> dict[str, pd.DataFrame]:
    try:
        strategies = read_public_google_sheet(url, "strategies", "Strategies")
    except DataError:
        strategies = load_default_strategies()
    return {
        "holdings": read_public_google_sheet(url, "holdings", "Holdings"),
        "strategies": strategies,
        "snapshots": read_optional_sheet(url, "Snapshots", SNAPSHOT_COLUMNS),
        "actions": read_optional_sheet(url, "Actions", ACTION_COLUMNS),
        "cashflows": read_optional_sheet(url, "Cashflows", CASHFLOW_COLUMNS),
        "category_targets": read_optional_sheet(url, "CategoryTargets", CATEGORY_TARGET_COLUMNS),
    }


def read_pasted_holdings(text: str) -> pd.DataFrame:
    if not text.strip():
        raise DataError("붙여넣은 데이터가 없습니다.")
    try:
        delimiter = "\t" if "\t" in text.partition("\n")[0] else ","
        return normalize_holdings(pd.read_csv(io.StringIO(text), sep=delimiter, dtype={"ticker": str}))
    except DataError:
        raise
    except Exception as exc:
        raise DataError(f"붙여넣은 표를 해석하지 못했습니다: {exc}") from exc


def export_month(as_of: date, view: pd.DataFrame, plan: pd.DataFrame, memo: str,
                 strategies: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    versions = {}
    if strategies is not None and not strategies.empty and "version" in strategies:
        versions = dict(zip(strategies["code"].astype(str), strategies["version"].fillna("1.0").astype(str)))
    snapshots = pd.DataFrame({
        "date": as_of.isoformat(), "saved_at": stamp,
        "strategy": view["strategy"], "account": view["account"], "ticker": view["ticker"],
        "name": view["name"], "category": view["category"], "close": view["close"],
        "shares": view["shares"], "value": view["평가액"], "weight_pct": view["전체비중"],
        "target_pct": view["target_pct"],
        "strategy_version": view["strategy"].astype(str).map(lambda code: versions.get(code, "1.0")),
        "memo": memo,
    }).reindex(columns=SNAPSHOT_COLUMNS)
    actions = pd.DataFrame({
        "date": as_of.isoformat(), "saved_at": stamp, "strategy": plan["전략"],
        "ticker": plan["티커"], "name": plan["종목"], "side": plan["구분"],
        "planned_shares": plan["제안수량"], "actual_shares": plan["실제수량"],
        "planned_amount": plan["예상매매액"], "done": plan["실행"],
        "reason": plan["근거"], "memo": plan["메모"],
    }).reindex(columns=ACTION_COLUMNS)
    return snapshots, actions


def export_category_month(as_of: date, view: pd.DataFrame, memo: str) -> pd.DataFrame:
    columns = ["date", "category", "value", "weight_pct", "memo"]
    if view.empty:
        return pd.DataFrame(columns=columns)
    grouped = view.groupby("category", as_index=False)["평가액"].sum().rename(columns={"평가액": "value"})
    total = float(grouped["value"].sum())
    grouped["date"] = as_of.isoformat()
    grouped["weight_pct"] = grouped["value"] / total * 100 if total > 0 else 0.0
    grouped["memo"] = memo
    return grouped.reindex(columns=columns)


def next_holdings_after_execution(holdings: pd.DataFrame, executed_plan: pd.DataFrame,
                                  view: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Create next month's holdings from checked executions.

    Actual quantity is entered as a positive number. Cash is adjusted by the
    actual KRW amount, or by the latest KRW unit price when that amount is blank.
    """
    next_holdings = normalize_holdings(holdings)
    warnings: list[str] = []
    if executed_plan.empty:
        return next_holdings, warnings
    price_lookup = {
        (str(row.strategy), str(row.ticker)): float(row.close) * float(row.fx)
        for row in view.itertuples()
    }
    cash_delta: dict[str, float] = {}
    for row in executed_plan.itertuples():
        if not bool(getattr(row, "실행", False)) or str(row.티커) == "CASH":
            continue
        qty = abs(float(getattr(row, "실제수량", 0) or 0))
        if qty <= 0:
            warnings.append(f"{row.전략}/{row.티커}: 실행 체크됐지만 실제수량이 없어 반영하지 않았습니다.")
            continue
        mask = next_holdings["strategy"].astype(str).eq(str(row.전략)) & next_holdings["ticker"].astype(str).eq(str(row.티커))
        if not mask.any():
            warnings.append(f"{row.전략}/{row.티커}: 보유내역에서 종목을 찾지 못했습니다.")
            continue
        sign = 1.0 if str(row.구분) == "매수" else -1.0
        current = float(next_holdings.loc[mask, "shares"].iloc[0])
        updated = current + sign * qty
        if updated < -1e-9:
            warnings.append(f"{row.전략}/{row.티커}: 보유수량보다 많이 매도할 수 없습니다.")
            continue
        next_holdings.loc[mask, "shares"] = max(0.0, updated)
        actual_amount = abs(float(getattr(row, "실제체결금액", 0) or 0))
        if actual_amount <= 0:
            actual_amount = qty * price_lookup.get((str(row.전략), str(row.티커)), 0.0)
        cash_delta[str(row.전략)] = cash_delta.get(str(row.전략), 0.0) - sign * actual_amount
    for strategy, delta in cash_delta.items():
        mask = next_holdings["strategy"].astype(str).eq(strategy) & next_holdings["ticker"].astype(str).eq("CASH")
        if not mask.any():
            warnings.append(f"{strategy}: CASH 행이 없어 체결금액 {delta:+,.0f}원을 반영하지 못했습니다.")
            continue
        current_cash = float(next_holdings.loc[mask, "shares"].iloc[0])
        updated_cash = current_cash + delta
        if updated_cash < -1:
            warnings.append(f"{strategy}: 체결 반영 후 현금이 {updated_cash:,.0f}원으로 음수가 됩니다.")
        next_holdings.loc[mask, "shares"] = max(0.0, updated_cash)
    if warnings:
        # Apply an execution batch atomically; never drop cash deficits or
        # partially update holdings when another fill cannot be represented.
        return normalize_holdings(holdings), warnings
    return next_holdings, warnings


def to_tsv(frame: pd.DataFrame, include_header: bool = True) -> str:
    return frame.fillna("").to_csv(index=False, sep="\t", header=include_header, lineterminator="\n")


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.fillna("").to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
