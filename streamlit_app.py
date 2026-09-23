from __future__ import annotations

import json
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_app.data import (
    DataError,
    export_category_month,
    export_month,
    load_default_holdings,
    load_default_strategies,
    next_holdings_after_execution,
    read_pasted_holdings,
    read_workbook,
    to_csv_bytes,
    to_tsv,
)
from streamlit_app.templates import TEMPLATES, apply_template
import importlib
import streamlit_app.engine as allocation_engine

# Streamlit Community Cloud can keep imported modules alive while pulling a new
# commit.  Reload the calculation engine when a newly deployed symbol is not yet
# present in that process, so the UI and engine can never run as mixed versions.
required_engine_symbols = {"validate_configuration", "validate_market_data", "validate_snapshot_history", "prior_month_comparison", "category_history"}
if not required_engine_symbols.issubset(set(dir(allocation_engine))):
    allocation_engine = importlib.reload(allocation_engine)

build_action_plan = allocation_engine.build_action_plan
comparison_history = allocation_engine.comparison_history
category_history = allocation_engine.category_history
enrich_prices = allocation_engine.enrich_prices
performance_summary = allocation_engine.performance_summary
portfolio_view = allocation_engine.portfolio_view
prior_month_comparison = allocation_engine.prior_month_comparison
sortino = allocation_engine.sortino
twr = allocation_engine.twr
validate_configuration = allocation_engine.validate_configuration
validate_market_data = allocation_engine.validate_market_data
validate_snapshot_history = allocation_engine.validate_snapshot_history
xirr = allocation_engine.xirr


st.set_page_config(page_title="월말 자산배분 도우미", page_icon="📊", layout="wide")
px.defaults.template = "plotly_dark"
px.defaults.color_discrete_sequence = ["#f7931a", "#38bdf8", "#22c55e", "#eab308", "#a78bfa", "#ef4444", "#7a8494"]
st.markdown("""<style>
:root{--bg:#0a0d12;--bg1:#0e1218;--bg2:#111621;--bg3:#161c2a;--hover:#1a2130;--line:#1e2533;--line2:#2a3346;--text:#d8dee9;--muted:#7a8494;--dim:#4a5262;--accent:#f7931a;--accent-soft:#f7931a26;--up:#22c55e;--down:#ef4444;--warn:#eab308;--info:#38bdf8;--mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;--sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
html,body,[class*="css"]{font-family:var(--sans)}
.stApp{background:var(--bg);color:var(--text)}
.block-container{max-width:1440px;padding-top:.8rem;padding-bottom:4rem}
header[data-testid="stHeader"]{background:rgba(10,13,18,.88);border-bottom:1px solid var(--line)}
section[data-testid="stSidebar"]{background:var(--bg1);border-right:1px solid var(--line)}
section[data-testid="stSidebar"] *{color:var(--text)}
section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3{font-family:var(--mono);font-size:.72rem!important;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)!important}
section[data-testid="stSidebar"] hr{border-color:var(--line)}
.terminal-topbar{height:38px;background:var(--bg1);border:1px solid var(--line);border-radius:5px 5px 0 0;display:flex;align-items:center;gap:14px;padding:0 14px;font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.04em}
.terminal-topbar b{color:var(--text);font-weight:500}.terminal-topbar .grow{flex:1}.terminal-topbar .dot{width:7px;height:7px;border-radius:50%;background:var(--up);box-shadow:0 0 7px var(--up)}.terminal-topbar .sep{height:16px;width:1px;background:var(--line)}
.app-hero{background:var(--bg2);color:var(--text);border:1px solid var(--line);border-top:0;border-radius:0 0 5px 5px;padding:18px 20px;margin-bottom:14px;position:relative;overflow:hidden}
.app-hero:after{content:"R";position:absolute;right:18px;top:7px;font-family:var(--mono);font-size:62px;font-weight:800;color:var(--accent);opacity:.12}
.app-hero .eyebrow{font-family:var(--mono);font-size:.65rem;font-weight:600;letter-spacing:.14em;color:var(--accent)}
.app-hero .title{font-size:1.38rem;font-weight:650;letter-spacing:-.025em;margin:.28rem 0}
.app-hero .sub{font-family:var(--mono);font-size:.72rem;color:var(--muted)}
.weight-card{background:var(--bg2);border:1px solid var(--line);border-radius:5px;padding:11px 12px;margin:6px 0}
.weight-head{display:flex;justify-content:space-between;gap:10px;font-weight:700}
.weight-head span:last-child,.weight-meta{font-family:var(--mono);font-variant-numeric:tabular-nums}.weight-meta{font-size:.7rem;color:var(--muted);margin-top:5px}
.weight-bar{height:5px;display:flex;overflow:hidden;border-radius:2px;background:var(--bg3);margin-top:9px}
[data-testid="stMetric"]{background:var(--bg2);border:1px solid var(--line);border-radius:5px;padding:.7rem .85rem;box-shadow:none}
[data-testid="stMetricLabel"]{font-family:var(--mono);font-size:.65rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
[data-testid="stMetricValue"]{font-family:var(--mono);font-weight:600;letter-spacing:-.02em;color:var(--text);font-variant-numeric:tabular-nums}
[data-testid="stMetricDelta"]{font-family:var(--mono);font-size:.7rem}
.stTabs [data-baseweb="tab-list"]{gap:0;background:var(--bg1);border:1px solid var(--line);border-radius:5px;padding:3px;overflow-x:auto}
.stTabs [data-baseweb="tab"]{height:2.35rem;border-radius:3px;padding:0 .72rem;color:var(--muted);font-family:var(--mono);font-size:.69rem;white-space:nowrap}
.stTabs [aria-selected="true"]{background:var(--bg3);color:var(--accent);box-shadow:inset 0 -2px 0 var(--accent)}
div[data-testid="stExpander"]{background:var(--bg2);border-color:var(--line);border-radius:5px;overflow:hidden}
div[data-testid="stDataFrame"],div[data-testid="stDataEditor"]{border:1px solid var(--line);border-radius:5px;overflow:hidden}
.stButton>button,.stDownloadButton>button{border-radius:3px;min-height:2.25rem;font-family:var(--mono);font-size:.72rem;font-weight:600;letter-spacing:.025em;background:var(--bg3);color:var(--text);border:1px solid var(--line2)}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--accent);color:var(--accent);background:var(--hover)}
.stButton>button[kind="primary"]{background:var(--accent);color:#0a0d12;border-color:var(--accent)}
.stTextInput input,.stTextArea textarea,.stNumberInput input,[data-baseweb="select"]>div{background:var(--bg1)!important;border-color:var(--line)!important;color:var(--text)!important;border-radius:3px!important;font-family:var(--mono)!important}
.stTextInput input:focus,.stTextArea textarea:focus,.stNumberInput input:focus{border-color:var(--accent)!important}
[data-testid="stAlert"]{background:var(--bg2);border:1px solid var(--line);border-radius:4px;color:var(--text)}
code{font-family:var(--mono);color:var(--accent);background:var(--bg1)!important}
h1,h2,h3,h4{letter-spacing:-.025em;color:var(--text)}
h2,h3{font-weight:620}.stCaptionContainer,p{color:var(--muted)}
hr{border-color:var(--line)!important}
@media(max-width:760px){.block-container{padding:.55rem}.stButton>button{width:100%}.terminal-topbar{gap:8px;overflow:hidden}.terminal-topbar .optional{display:none}.app-hero{padding:15px}.app-hero .title{font-size:1.16rem}.stTabs [data-baseweb="tab-list"]{overflow-x:auto}}
</style>""", unsafe_allow_html=True)


def won(value: float) -> str:
    return f"{value:,.0f}원"


def weight_card(name: str, current: float, target: float | None, amount: float) -> None:
    current = max(0.0, current)
    if target is None:
        st.markdown(f'<div class="weight-card"><div class="weight-head"><span>{name}</span><span>{current:.1f}%</span></div>'
                    f'<div class="weight-meta">{won(amount)} · 장기보유 · 리밸런싱 없음</div>'
                    f'<div class="weight-bar"><div style="width:{min(current, 100)}%;background:#64748b"></div></div></div>', unsafe_allow_html=True)
        return
    target = max(0.0, target)
    scale = max(100.0, current, target, 1.0)
    green, blue, red = min(current, target) / scale * 100, max(target-current, 0) / scale * 100, max(current-target, 0) / scale * 100
    bars = "".join([
        f'<div style="width:{green}%;background:#16a34a"></div>' if green else "",
        f'<div style="width:{blue}%;background:#3b82f6"></div>' if blue else "",
        f'<div style="width:{red}%;background:#ef4444"></div>' if red else "",
    ])
    st.markdown(f'<div class="weight-card"><div class="weight-head"><span>{name}</span><span>{current:.1f}%</span></div>'
                f'<div class="weight-meta">{won(amount)} · 목표 {target:.1f}% · 괴리 {current-target:+.1f}%p</div>'
                f'<div class="weight-bar">{bars}</div><div class="weight-meta">🟢 목표 충족 · 🔵 목표 미달 · 🔴 목표 초과</div></div>', unsafe_allow_html=True)


def rebalance_status(group: pd.DataFrame) -> tuple[str, str]:
    if group.empty:
        return "⚪ 데이터 없음", "계획 데이터가 없습니다."
    current = pd.to_numeric(group["현재평가액"], errors="coerce").fillna(0)
    trades = pd.to_numeric(group["예상매매액"], errors="coerce").fillna(0).abs()
    ratio = float(trades.max() / current.sum()) if current.sum() > 0 else 0
    if ratio >= .10: return "🔴 리밸런싱 필요", f"최대 조정액 {ratio:.1%}"
    if ratio >= .03: return "🟡 점검 권장", f"최대 조정액 {ratio:.1%}"
    return "🟢 정상", "목표비중과의 괴리가 크지 않습니다."


if "holdings" not in st.session_state:
    st.session_state.holdings = load_default_holdings()
if "strategies" not in st.session_state:
    st.session_state.strategies = load_default_strategies()
if "snapshots" not in st.session_state:
    st.session_state.snapshots = pd.DataFrame()
if "actions" not in st.session_state:
    st.session_state.actions = pd.DataFrame()
if "benchmarks" not in st.session_state:
    st.session_state.benchmarks = "QQQ, SPY, ^KS200"
if "cashflows" not in st.session_state:
    st.session_state.cashflows = pd.DataFrame(columns=["date", "amount", "memo", "strategy"])
if "category_targets" not in st.session_state:
    st.session_state.category_targets = pd.DataFrame(columns=["category", "target_pct"])

st.markdown(f"""<div class="terminal-topbar"><span class="dot"></span><b>READY</b><span class="sep"></span>
<span>ENGINE <b>STREAMLIT</b></span><span class="optional">DATA <b>YAHOO FINANCE</b></span><span class="grow"></span>
<span>AS-OF <b>{date.today().isoformat()}</b></span></div>
<div class="app-hero"><div class="eyebrow">REBALANCE TERMINAL · MONTH-END WORKSPACE</div>
<div class="title">월말 자산배분 도우미</div>
<div class="sub">PRICE · SIGNAL · ALLOCATION · EXECUTION · HISTORY · GOOGLE SHEETS</div></div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("월말 기준")
    as_of = st.date_input("기준일", value=date.today())
    price_mode = st.radio("가격", ["종가", "수정종가"], horizontal=True)
    refresh = st.button("종가 새로 조회", type="primary", use_container_width=True)
    st.caption("휴장일이면 기준일 이전의 가장 최근 거래일을 사용합니다.")

    st.divider()
    st.subheader("읽기 전용 Google Sheets")
    sheet_url = st.text_input("스프레드시트 URL", placeholder="https://docs.google.com/spreadsheets/d/...")
    if st.button("전체 데이터 읽기", use_container_width=True):
        try:
            workbook = read_workbook(sheet_url)
            for key, frame in workbook.items():
                st.session_state[key] = frame
            st.session_state.pop("priced_holdings", None)
            st.success("Holdings·Strategies·Snapshots·Actions·Cashflows·CategoryTargets를 불러왔습니다.")
        except DataError as exc:
            st.error(str(exc))
    st.caption("탭 이름은 Holdings, Strategies, Snapshots, Actions, Cashflows, CategoryTargets를 사용합니다. Holdings 외 탭은 없어도 됩니다.")

holdings = st.session_state.holdings.copy()
strategies = st.session_state.strategies.copy()
active_mask = ~strategies["active"].astype(str).str.lower().isin(["false", "0", "no"])
active_codes = set(strategies.loc[active_mask, "code"].astype(str))
active_holdings = holdings[holdings["strategy"].astype(str).isin(active_codes)].copy()

price_context = (as_of.isoformat(), price_mode)
if refresh or "priced_holdings" not in st.session_state or st.session_state.get("price_context") != price_context:
    with st.spinner("Yahoo Finance에서 종가를 조회하고 있습니다..."):
        priced, warnings = enrich_prices(
            active_holdings, as_of, adjusted=price_mode == "수정종가", strategies=strategies,
        )
        st.session_state.priced_holdings = priced
        st.session_state.price_warnings = warnings
        st.session_state.price_context = price_context

priced = st.session_state.priced_holdings.copy()
view = portfolio_view(priced)
plan = build_action_plan(view, strategies, as_of)
config_warnings = validate_configuration(holdings, strategies)
market_errors, market_warnings = validate_market_data(priced, as_of)
history_warnings = validate_snapshot_history(st.session_state.snapshots, as_of)
run_blockers = config_warnings + market_errors + history_warnings

for warning in st.session_state.get("price_warnings", []):
    st.warning(warning)
for warning in market_warnings:
    st.warning(warning)

tab_workflow, tab_dashboard, tab_plan, tab_holdings, tab_settings, tab_history, tab_export = st.tabs(
    ["✅ 월말 마감", "🏠 대시보드", "🔄 리밸런싱 실행", "📦 보유내역", "⚙️ 전략 설정", "📈 기록·성과", "📋 복사용 데이터"]
)

with tab_workflow:
    st.subheader("이번 달 마감 흐름")
    st.caption("지난달 보유수량 → 기준일 종가 평가 → 전략 규칙 적용 → 다음 거래일 주문 → 월별 기록 순서입니다.")
    latest_dates = pd.to_datetime(priced.loc[priced["ticker"] != "CASH", "price_date"], errors="coerce").dropna()
    effective_date = latest_dates.max().date().isoformat() if not latest_dates.empty else "—"
    actionable_count = int(((plan["티커"] != "CASH") & (pd.to_numeric(plan["예상매매액"], errors="coerce").abs() > 1000)).sum())
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("1 · 보유 종목", f"{len(active_holdings):,}개")
    w2.metric("2 · 실제 가격일", effective_date)
    w3.metric("3 · 주문 후보", f"{actionable_count:,}건")
    w4.metric("4 · 마감 상태", "확인 필요" if run_blockers else "기록 가능")

    if run_blockers:
        st.error("아래 문제를 해결하기 전에는 주문안과 월말 기록을 확정하지 마세요.")
        for issue in run_blockers:
            st.warning(issue)
    else:
        st.success("가격·환율·전략 설정 기본 검증을 통과했습니다. 리밸런싱 실행 탭에서 주문안을 확인하세요.")

    st.markdown("### 지난 기록 대비 평가액 변화")
    month_change, prior_date = prior_month_comparison(view, st.session_state.snapshots, as_of)
    if month_change.empty:
        st.info("이전 Snapshots 기록이 없어 지난달 비교는 이번 기록 이후부터 표시됩니다.")
    else:
        st.caption(f"비교 기준: {prior_date.date()} · 입출금과 매매가 포함된 평가액 변화이며 순수 투자수익률은 기록·성과 탭에서 확인합니다.")
        st.dataframe(month_change, use_container_width=True, hide_index=True, column_config={
            "지난달평가액": st.column_config.NumberColumn(format="%,.0f원"),
            "현재평가액": st.column_config.NumberColumn(format="%,.0f원"),
            "증감액": st.column_config.NumberColumn(format="%,.0f원"),
            "증감률(%)": st.column_config.NumberColumn(format="%.2f%%"),
        })

    st.markdown("### 현재 자산군 구성")
    workflow_categories = view.groupby("category", as_index=False)["평가액"].sum()
    workflow_categories["비중"] = workflow_categories["평가액"] / max(float(workflow_categories["평가액"].sum()), 1) * 100
    st.dataframe(workflow_categories, use_container_width=True, hide_index=True, column_config={
        "평가액": st.column_config.NumberColumn(format="%,.0f원"),
        "비중": st.column_config.NumberColumn(format="%.1f%%"),
    })

    st.markdown("### 마감 순서")
    st.markdown("1. **대시보드**에서 전략별 현재비중과 자산군 구성을 확인합니다.  \n"
                "2. **리밸런싱 실행**에서 매수·매도 대상과 계산 근거를 확인합니다. 장기보유 전략은 주문이 생성되지 않습니다.  \n"
                "3. 다음 거래일 주문 후 실제수량과 실제체결금액을 입력하고 실행을 체크합니다.  \n"
                "4. **복사용 데이터**에서 이번 달 스냅샷과 액션을 누적하고, 다음 달 보유내역으로 Holdings를 교체합니다.")

with tab_dashboard:
    total = float(view["평가액"].sum()) if not view.empty else 0
    cash = float(view.loc[view["category"] == "현금", "평가액"].sum()) if not view.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("총 평가액", won(total))
    c2.metric("현금", won(cash), f"{cash / total * 100:.1f}%" if total else "0%")
    c3.metric("조회 기준일", as_of.isoformat())

    st.markdown("### 전략별 목표비중 현황")
    for code, group in view.groupby("strategy", sort=False):
        cfg = strategies.loc[strategies["code"].astype(str) == str(code)]
        account = str(cfg.iloc[0]["account"]) if not cfg.empty else str(code)
        rule_value = str(cfg.iloc[0]["rule"]) if not cfg.empty else "static"
        with st.expander(f"{code} · {account} · {won(group['평가액'].sum())}", expanded=True):
            if rule_value == "hold":
                st.caption("장기보유 전략 · 현재 평가만 기록하며 목표비중 복원 주문을 만들지 않습니다.")
            for row in group.itertuples():
                target = None if rule_value == "hold" else float(row.target_pct)
                weight_card(str(row.name or row.ticker), float(row.현재비중), target, float(row.평가액))

    left, right = st.columns(2)
    with left:
        st.subheader("종목별 비중")
        fig = px.sunburst(
            view[view["평가액"] > 0], path=["strategy", "name"], values="평가액",
            color="category", height=470,
        )
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("전략별 비중")
        by_strategy = view.groupby("strategy", as_index=False)["평가액"].sum()
        fig = px.pie(by_strategy, names="strategy", values="평가액", hole=.45, height=470)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("목표 대비 괴리")
    target_rules = dict(zip(strategies["code"].astype(str), strategies["rule"].astype(str)))
    chart = view[(view["ticker"] != "CASH") & view["strategy"].astype(str).map(target_rules).ne("hold")].copy()
    if chart.empty:
        st.info("목표비중을 복원하는 활성 전략이 없습니다.")
    else:
        fig = px.bar(
            chart, x="name", y=["현재비중", "target_pct"], barmode="group",
            labels={"value": "비중(%)", "name": "종목", "variable": "구분"}, height=430,
            color_discrete_map={"현재비중": "#2563eb", "target_pct": "#94a3b8"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("전체 자산군 분포")
    categories = view.groupby("category", as_index=False)["평가액"].sum()
    categories["비중"] = categories["평가액"] / max(categories["평가액"].sum(), 1) * 100
    targets = dict(zip(st.session_state.category_targets.get("category", []), pd.to_numeric(st.session_state.category_targets.get("target_pct", []), errors="coerce").fillna(0)))
    categories["목표비중"] = categories["category"].map(lambda x: targets.get(x, 0.0))
    categories["괴리(%p)"] = categories["비중"] - categories["목표비중"]
    st.dataframe(categories, use_container_width=True, hide_index=True)

with tab_plan:
    st.subheader("이번 달 액션 플랜")
    st.caption("계획은 참고값입니다. 주문 전 가격·세금·수수료와 실제 주문 가능 수량을 확인하세요.")
    memo = st.text_area("이번 달 판단 메모", key="month_memo", placeholder="시장 상황, 예외 처리, 실행하지 않은 이유 등을 기록하세요.")
    st.markdown("### 전략별 현재 상태")
    signal_cols = view[["strategy", "ticker", "close", "sma10", "sma_period", "momentum12", "price_date"]].copy()
    detailed = plan.merge(signal_cols, left_on=["전략", "티커"], right_on=["strategy", "ticker"], how="left")
    detailed["목표평가액"] = detailed["현재평가액"] + detailed["예상매매액"]
    for code, group in detailed.groupby("전략", sort=False):
        status, help_text = rebalance_status(group)
        st.markdown(f"#### {code}")
        st.caption(f"{status} · {help_text}")
        m1, m2, m3 = st.columns(3)
        m1.metric("현재", won(group["현재평가액"].sum()))
        m2.metric("목표", won(group["목표평가액"].sum()))
        m3.metric("순매매", won(group["예상매매액"].sum()))
        show = group[["티커", "종목", "price_date", "close", "sma_period", "sma10", "momentum12", "현재평가액", "목표평가액", "예상매매액", "근거"]].copy()
        show = show.rename(columns={"price_date": "가격일", "close": "종가", "sma_period": "SMA개월", "sma10": "SMA", "momentum12": "12개월모멘텀"})
        def trade_color(value):
            return "color:#dc2626;font-weight:700" if value > 1000 else ("color:#2563eb;font-weight:700" if value < -1000 else "")
        show_style = show.style.format({
            "종가": "{:,.0f}",
            "SMA": "{:,.0f}",
            "12개월모멘텀": "{:.2%}",
            "현재평가액": "{:,.0f}",
            "목표평가액": "{:,.0f}",
            "예상매매액": "{:,.0f}",
        }, na_rep="—").map(trade_color, subset=["예상매매액"])
        st.dataframe(show_style, use_container_width=True, hide_index=True)

    st.markdown("### 실행 체크리스트")
    actionable_plan = plan[(plan["티커"] != "CASH") & (pd.to_numeric(plan["예상매매액"], errors="coerce").abs() > 1000)].copy()
    if actionable_plan.empty:
        st.success("실행할 매매가 없습니다.")
    edited_plan = st.data_editor(
        actionable_plan, key="action_editor", use_container_width=True, hide_index=True,
        disabled=[column for column in actionable_plan.columns if column not in {"실행", "실제수량", "실제체결금액", "메모"}],
        column_config={
            "실행": st.column_config.CheckboxColumn(),
            "예상매매액": st.column_config.NumberColumn(format="%,.0f원"),
            "현재평가액": st.column_config.NumberColumn(format="%,.0f원"),
            "목표평가액": st.column_config.NumberColumn(format="%,.0f원"),
            "실제수량": st.column_config.NumberColumn(min_value=0.0, format="%.4f", help="체결된 수량을 양수로 입력"),
            "실제체결금액": st.column_config.NumberColumn(min_value=0.0, format="%,.0f원", help="수수료를 제외한 원화 기준 총 체결금액"),
        },
    )
    with st.expander("🛡️ 리밸런싱 실행 전 최종 점검"):
        errors = list(run_blockers)
        checked = edited_plan[edited_plan["실행"].fillna(False).astype(bool)] if not edited_plan.empty else edited_plan
        if not checked.empty and (pd.to_numeric(checked["실제수량"], errors="coerce").fillna(0) <= 0).any():
            errors.append("실행 체크한 주문에는 실제수량을 입력해야 합니다.")
        if errors:
            for error in errors: st.warning(error)
        else:
            st.success("가격과 목표비중 기본 점검을 통과했습니다.")

with tab_holdings:
    st.subheader("보유수량·종목 편집")
    st.caption("CASH의 shares에는 원화 현금 금액을 입력합니다. 변경은 현재 브라우저 세션에만 유지됩니다.")
    editable_cols = ["strategy", "account", "ticker", "name", "market", "category", "role", "target_pct", "shares"]
    edited = st.data_editor(
        holdings[editable_cols], key="holding_editor", num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "market": st.column_config.SelectboxColumn(options=["KR", "US"]),
            "target_pct": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.2f"),
            "shares": st.column_config.NumberColumn(min_value=0.0, format="%.4f"),
        },
    )
    if st.button("편집한 보유내역 적용"):
        st.session_state.holdings = edited.copy()
        st.session_state.pop("priced_holdings", None)
        st.success("현재 세션에 적용했습니다. 종가를 다시 조회하세요.")

    st.subheader("표를 직접 붙여넣기")
    pasted = st.text_area("Google Sheets에서 헤더 포함 범위를 복사해 붙여넣으세요", height=160)
    if st.button("붙여넣은 보유내역 적용"):
        try:
            st.session_state.holdings = read_pasted_holdings(pasted)
            st.session_state.pop("priced_holdings", None)
            st.success("현재 세션에 적용했습니다.")
        except DataError as exc:
            st.error(str(exc))

with tab_settings:
    st.subheader("전략 구성과 규칙 설정")
    st.caption("변경값은 현재 세션에 적용되며, 아래 복사용 데이터에서 Strategies와 Holdings를 시트에 반영합니다.")
    config_warnings = validate_configuration(holdings, strategies)
    if config_warnings:
        with st.expander(f"⚠️ 설정 점검 {len(config_warnings)}건", expanded=True):
            for warning in config_warnings:
                st.warning(warning)
    else:
        st.success("전략 구성과 비중 설정이 기본 검증을 통과했습니다.")
    rule_names = {
        "static": "정적 목표비중", "sma_filter_rebalance": "10개월 SMA 필터",
        "momentum_rotate": "모멘텀 1위 로테이션", "drawdown_buy": "낙폭 분할매수",
        "drawdown_shift": "낙폭 비중전환", "hold": "보유 유지", "visual": "노코드 조건 규칙",
    }
    strategy_codes = strategies["code"].astype(str).tolist()
    selected = st.selectbox("설정할 전략", strategy_codes)
    current = strategies.loc[strategies["code"].astype(str) == selected].iloc[0]
    c1, c2 = st.columns(2)
    account_edit = c1.text_input("계좌명", str(current.get("account", selected)))
    active_edit = c2.checkbox("전략 활성화", bool(current.get("active", True)))
    description_edit = st.text_area("전략 설명", str(current.get("description", "")), height=70)
    v1, v2 = st.columns(2)
    version_edit = v1.text_input("전략 버전", str(current.get("version", "1.0") or "1.0"))
    effective_edit = v2.text_input("적용 시작일", str(current.get("effective_date", "") or ""), placeholder="YYYY-MM-DD")
    source_edit = st.text_input("참고 문헌·URL", str(current.get("source", "") or ""))
    change_note_edit = st.text_area("이번 버전 변경 이유", str(current.get("change_note", "") or ""), height=70)
    current_rule = str(current["rule"]) if str(current["rule"]) in rule_names else "static"
    rule = st.selectbox(
        "규칙", list(rule_names), index=list(rule_names).index(current_rule),
        format_func=lambda value: rule_names[value],
    )
    try:
        params = json.loads(current.get("params_json") or "{}")
    except Exception:
        params = {}

    if rule == "sma_filter_rebalance":
        candidates = holdings.loc[holdings["strategy"] == selected, "ticker"].astype(str).tolist()
        params["sma_tickers"] = st.multiselect("SMA 필터 대상", candidates, default=[x for x in params.get("sma_tickers", []) if x in candidates])
        params["sma_months"] = st.number_input("SMA 기간(개월)", 2, 24, int(params.get("sma_months", 10)))
        params["quarter_end_restore"] = st.checkbox("분기말 목표비중 복원", bool(params.get("quarter_end_restore", True)))
    elif rule == "momentum_rotate":
        params["winner_share"] = st.slider("1위 자산 비중", 0.0, 1.0, float(params.get("winner_share", .8)), .05)
        params["cash_winner_share"] = st.slider("현금 비중", 0.0, 1.0, float(params.get("cash_winner_share", .2)), .05)
        params["cash_no_winner"] = 1.0
    elif rule in {"drawdown_buy", "drawdown_shift"}:
        signal = params.get("signal", {})
        c1, c2, c3 = st.columns(3)
        signal["ticker"] = c1.text_input("기준 티커", str(signal.get("ticker", "QQQ")))
        signal["market"] = c2.selectbox("기준 시장", ["KR", "US"], index=1 if signal.get("market") == "US" else 0)
        signal["lookback_days"] = c3.number_input("고점 확인 거래일", 20, 500, int(signal.get("lookback_days", 120)))
        params["signal"] = signal
        params["threshold"] = st.number_input("발동 하락률", -0.90, 0.0, float(params.get("threshold", -.10)), .01, format="%.2f")
        if rule == "drawdown_buy":
            stock_candidates = holdings[(holdings["strategy"].astype(str) == selected) & (holdings["ticker"].astype(str) != "CASH")]["ticker"].astype(str).tolist()
            if stock_candidates:
                current_stock = str(params.get("stock_ticker", stock_candidates[0]))
                params["stock_ticker"] = st.selectbox("매수 대상 티커", stock_candidates, index=stock_candidates.index(current_stock) if current_stock in stock_candidates else 0)
            params["buy_fraction"] = st.slider("발동 시 현금 투입 비율", 0.0, 1.0, float(params.get("buy_fraction", .5)), .05)
        else:
            params["normal_stock_pct"] = st.slider("평시 주식비중(안내용)", 0, 100, int(params.get("normal_stock_pct", 70)))
            params["triggered_stock_pct"] = st.slider("발동 시 주식비중", 0, 100, int(params.get("triggered_stock_pct", 85)))
    elif rule == "hold":
        params["hold_note"] = st.text_input("표시 메모", str(params.get("hold_note", "매매 없음")))
    elif rule == "visual":
        st.caption("조건을 문장처럼 구성합니다. 값이 없으면 안전하게 보유 유지로 판정합니다.")
        metric_names = {"sma_deviation":"SMA 대비", "momentum":"모멘텀", "drawdown":"낙폭", "price":"현재 가격"}
        action_names = {"target":"목표비중 복원", "hold":"그대로 유지", "cash":"전량 현금화", "buy_fraction":"현금에서 일부 매수", "winner":"모멘텀 1위 집중"}
        conditions = params.get("conditions") or [{"ticker":"", "market":"KR", "metric":"sma_deviation", "period":10, "operator":">", "threshold":0.0}]
        condition_frame = pd.DataFrame(conditions).reindex(columns=["ticker","market","metric","period","operator","threshold"])
        condition_frame = st.data_editor(condition_frame, num_rows="dynamic", use_container_width=True, hide_index=True,
            column_config={"market":st.column_config.SelectboxColumn(options=["KR","US"]),
                           "metric":st.column_config.SelectboxColumn(options=list(metric_names)),
                           "operator":st.column_config.SelectboxColumn(options=[">",">=","<","<="]),
                           "period":st.column_config.NumberColumn(min_value=1, max_value=500)})
        params["conditions"] = [row for row in condition_frame.fillna("").to_dict("records") if str(row.get("ticker", "")).strip()]
        params["combine"] = st.radio("조건 결합", ["AND","OR"], horizontal=True, index=0 if params.get("combine","AND") == "AND" else 1)
        ac1, ac2 = st.columns(2)
        actions = list(action_names)
        pass_value, fail_value = params.get("on_pass","target"), params.get("on_fail","hold")
        params["on_pass"] = ac1.selectbox("조건 충족 시", actions, index=actions.index(pass_value) if pass_value in actions else 0, format_func=action_names.get)
        params["on_fail"] = ac2.selectbox("조건 미충족 시", actions, index=actions.index(fail_value) if fail_value in actions else 1, format_func=action_names.get)
        candidates = holdings.loc[(holdings["strategy"].astype(str) == selected) & (holdings["ticker"].astype(str) != "CASH"), "ticker"].astype(str).tolist()
        if candidates:
            params["target_ticker"] = st.selectbox("일부 매수 대상", candidates, index=candidates.index(params.get("target_ticker")) if params.get("target_ticker") in candidates else 0)
        params["buy_fraction"] = st.slider("현금 투입 비율", 0.0, 1.0, float(params.get("buy_fraction", .5)), .05)

    if st.button("전략 규칙 적용", type="primary"):
        updated = st.session_state.strategies.copy()
        mask = updated["code"].astype(str) == selected
        updated.loc[mask, "rule"] = rule
        updated.loc[mask, "params_json"] = json.dumps(params, ensure_ascii=False)
        updated.loc[mask, "account"] = account_edit
        updated.loc[mask, "active"] = active_edit
        updated.loc[mask, "description"] = description_edit
        updated.loc[mask, "version"] = version_edit
        updated.loc[mask, "effective_date"] = effective_edit
        updated.loc[mask, "source"] = source_edit
        updated.loc[mask, "change_note"] = change_note_edit
        st.session_state.strategies = updated
        st.session_state.pop("priced_holdings", None)
        st.success("현재 세션에 적용했습니다.")

    st.divider()
    st.markdown("#### 선택 전략의 구성 종목")
    selected_assets = st.session_state.holdings[st.session_state.holdings["strategy"].astype(str) == selected].copy()
    edited_assets = st.data_editor(
        selected_assets, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "market": st.column_config.SelectboxColumn(options=["KR", "US"]),
            "target_pct": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=.1),
            "shares": st.column_config.NumberColumn(min_value=0.0, step=1.0),
        },
    )
    target_sum = pd.to_numeric(edited_assets["target_pct"], errors="coerce").fillna(0).sum()
    st.caption(f"목표비중 합계 {target_sum:.1f}%")
    if st.button("구성 종목·목표비중 적용"):
        rest = st.session_state.holdings[st.session_state.holdings["strategy"].astype(str) != selected]
        st.session_state.holdings = pd.concat([rest, edited_assets], ignore_index=True)
        st.session_state.pop("priced_holdings", None)
        st.success("현재 세션에 적용했습니다.")

    with st.expander("전략 추가·삭제"):
        new_code = st.text_input("새 전략 코드").strip().upper()
        new_account = st.text_input("새 전략 계좌명")
        if st.button("새 전략 추가") and new_code:
            if new_code in st.session_state.strategies["code"].astype(str).tolist():
                st.error("이미 존재하는 전략 코드입니다.")
            else:
                row = pd.DataFrame([{"code": new_code, "account": new_account or new_code, "description": "", "dynamic": False, "active": True, "annual_limit": 0, "rule": "static", "params_json": "{}", "version":"1.0", "effective_date":"", "source":"", "change_note":""}])
                st.session_state.strategies = pd.concat([st.session_state.strategies, row], ignore_index=True)
                st.success("전략을 추가했습니다.")
        confirm_delete = st.checkbox(f"{selected} 전략과 소속 종목 삭제 확인")
        if st.button("선택 전략 삭제", disabled=not confirm_delete):
            st.session_state.strategies = st.session_state.strategies[st.session_state.strategies["code"].astype(str) != selected].reset_index(drop=True)
            st.session_state.holdings = st.session_state.holdings[st.session_state.holdings["strategy"].astype(str) != selected].reset_index(drop=True)
            st.session_state.pop("priced_holdings", None)
            st.success("삭제했습니다.")

    st.divider()
    st.markdown("#### 문헌 전략 템플릿 19종")
    st.caption("템플릿은 출발점입니다. 적용 전에 출처와 구성 종목을 검토하고, 기존 전략에 적용하면 해당 전략의 구성 종목이 교체됩니다.")
    template_ids = [item["id"] for item in TEMPLATES]
    template_id = st.selectbox("템플릿", template_ids, format_func=lambda value: next(x["name"] for x in TEMPLATES if x["id"] == value))
    template = next(x for x in TEMPLATES if x["id"] == template_id)
    st.info(f"{template['family']} · {template['rebalance']}\n\n{template['description']}\n\n출처: {template['source']} · 특성: {template['trait']}")
    template_preview = pd.DataFrame(template["assets"])[["ticker","name","market","category","role","target_pct"]]
    st.dataframe(template_preview, use_container_width=True, hide_index=True)
    use_kr = st.checkbox("가능한 종목은 한국 상장 ETF 근사치로 변환", help="동일 지수가 아닐 수 있으므로 적용 후 반드시 검토하세요.")
    replace_confirm = st.checkbox(f"{selected} 전략을 이 템플릿으로 교체하는 데 동의합니다")
    if st.button("선택 템플릿 적용", disabled=not replace_confirm):
        strategy_row, asset_rows = apply_template(template_id, selected, account_edit or selected, use_kr)
        strategy_row["effective_date"] = as_of.isoformat()
        old_strategies = st.session_state.strategies
        for column in old_strategies.columns:
            strategy_row.setdefault(column, "")
        replacement = pd.DataFrame([strategy_row]).reindex(columns=old_strategies.columns)
        st.session_state.strategies = pd.concat([old_strategies[old_strategies["code"].astype(str) != selected], replacement], ignore_index=True)
        st.session_state.holdings = pd.concat([st.session_state.holdings[st.session_state.holdings["strategy"].astype(str) != selected], asset_rows.reindex(columns=st.session_state.holdings.columns)], ignore_index=True)
        st.session_state.pop("priced_holdings", None)
        st.success("템플릿을 적용했습니다. 종목과 규칙을 확인한 뒤 종가를 다시 조회하세요.")

    st.divider()
    st.markdown("#### 전체 자산군 목표비중")
    categories = ["현금", "금", "선진국 주식", "신흥국 주식", "선진국 채권", "신흥국 채권", "기타"]
    existing_targets = dict(zip(st.session_state.category_targets.get("category", []), pd.to_numeric(st.session_state.category_targets.get("target_pct", []), errors="coerce").fillna(0)))
    category_editor = st.data_editor(pd.DataFrame({"category": categories, "target_pct": [existing_targets.get(x, 0.0) for x in categories]}), hide_index=True, use_container_width=True)
    if st.button("자산군 목표비중 적용"):
        st.session_state.category_targets = category_editor
        st.success("적용했습니다.")

    st.divider()
    st.markdown("#### 전체 전략표")
    edited_strategies = st.data_editor(
        st.session_state.strategies, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={"rule": st.column_config.SelectboxColumn(options=list(rule_names))},
    )
    if st.button("전체 전략표 적용"):
        st.session_state.strategies = edited_strategies
        st.session_state.pop("priced_holdings", None)
        st.success("전체 전략표를 적용했습니다.")

with tab_history:
    st.subheader("월별 기록·성과")
    snapshots_history = st.session_state.snapshots.copy()
    actions_history = st.session_state.actions.copy()
    if snapshots_history.empty:
        st.info("Snapshots 탭에 월말 기록을 누적한 뒤 스프레드시트를 다시 읽으면 성과가 표시됩니다.")
    else:
        snapshots_history["date"] = pd.to_datetime(snapshots_history["date"], errors="coerce")
        range_name = st.radio("비교 구간", ["전체", "1년", "6개월", "3개월", "YTD"], horizontal=True)
        last_day = snapshots_history["date"].max()
        cuts = {"1년": last_day-pd.Timedelta(days=365), "6개월": last_day-pd.Timedelta(days=182), "3개월": last_day-pd.Timedelta(days=91), "YTD": pd.Timestamp(f"{last_day.year}-01-01")}
        if range_name != "전체":
            snapshots_history = snapshots_history[snapshots_history["date"] >= cuts[range_name]]
        equity, metrics = performance_summary(snapshots_history)
        cashflows = st.session_state.cashflows.copy()
        irr_value, twr_value, sortino_value = xirr(equity, cashflows), twr(equity, cashflows), sortino(equity)
        m1, m2, m3, m4 = st.columns(4)
        fmt = lambda value: "—" if value is None else f"{value:.2%}"
        m1.metric("평가액 CAGR", fmt(metrics["cagr"]))
        m2.metric("MDD", fmt(metrics["mdd"]))
        m3.metric("연환산 변동성", fmt(metrics["volatility"]))
        m4.metric("Sharpe", "—" if metrics["sharpe"] is None else f"{metrics['sharpe']:.2f}")
        x1, x2, x3 = st.columns(3)
        x1.metric("XIRR", fmt(irr_value))
        x2.metric("TWR", fmt(twr_value))
        x3.metric("Sortino", "—" if sortino_value is None else f"{sortino_value:.2f}")

        benchmark_text = st.text_input("비교 벤치마크", value=st.session_state.benchmarks, help="Yahoo Finance 티커를 쉼표로 구분")
        st.session_state.benchmarks = benchmark_text
        compare, benchmark_warnings = comparison_history(snapshots_history, benchmark_text.split(","), cashflows)
        for warning in benchmark_warnings:
            st.warning(warning)
        if not compare.empty:
            st.caption("벤치마크 비교의 포트폴리오 선은 Cashflows의 입출금을 차감한 기간수익률을 연결합니다. 평가액 CAGR·MDD는 원금 증감이 포함된 잔고 기준입니다.")
            fig = px.line(compare, x="date", y="value", color="series", markers=True, labels={"value": "시작=100", "date": "기준일", "series": "비교"})
            st.plotly_chart(fig, use_container_width=True)

        by_strategy = snapshots_history.copy()
        by_strategy["value"] = pd.to_numeric(by_strategy["value"], errors="coerce").fillna(0)
        by_strategy = by_strategy.groupby(["date", "strategy"], as_index=False)["value"].sum()
        by_strategy["normalized"] = by_strategy.groupby("strategy")["value"].transform(lambda s: s / s.iloc[0] * 100 if len(s) and s.iloc[0] else s)
        st.plotly_chart(px.line(by_strategy, x="date", y="normalized", color="strategy", markers=True, labels={"normalized": "시작=100"}), use_container_width=True)

        st.markdown("#### 자산군별 월말 히스토리")
        asset_history = category_history(snapshots_history)
        if not asset_history.empty:
            st.plotly_chart(
                px.area(asset_history, x="date", y="weight_pct", color="category",
                        labels={"date": "기준일", "weight_pct": "전체 비중(%)", "category": "자산군"}),
                use_container_width=True,
            )
            latest_asset_date = asset_history["date"].max()
            latest_assets = asset_history[asset_history["date"] == latest_asset_date].copy()
            st.dataframe(latest_assets, use_container_width=True, hide_index=True, column_config={
                "value": st.column_config.NumberColumn("평가액", format="%,.0f원"),
                "weight_pct": st.column_config.NumberColumn("전체 비중", format="%.1f%%"),
            })
        strategy_metrics = []
        for code, group in snapshots_history.groupby("strategy"):
            eq_strategy, met = performance_summary(group)
            strategy_metrics.append({"전략": code, "CAGR": met["cagr"], "MDD": met["mdd"], "변동성": met["volatility"], "Sharpe": met["sharpe"]})
        st.dataframe(pd.DataFrame(strategy_metrics), use_container_width=True, hide_index=True)
        st.dataframe(
            snapshots_history.sort_values("date", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "close": st.column_config.NumberColumn("종가", format="%,.0f"),
            },
        )
        if not actions_history.empty:
            st.markdown("#### 실행 이력")
            st.dataframe(actions_history.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("입출금 원장")
    st.caption("입금은 +, 출금은 -로 입력합니다. 기록은 Cashflows 탭에 복사해 누적합니다.")
    cashflows_edit = st.data_editor(
        st.session_state.cashflows, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={"amount": st.column_config.NumberColumn(step=100000.0)},
    )
    if st.button("입출금 원장 적용"):
        st.session_state.cashflows = cashflows_edit
        st.success("현재 세션에 적용했습니다.")

with tab_export:
    st.subheader("Google Sheets 복사용 데이터")
    st.caption("Snapshots·Actions는 매월 아래쪽에 누적하고, Holdings·Strategies는 기존 표 전체를 교체합니다.")
    include_header = st.checkbox("누적 표에 헤더 포함", value=False, help="시트를 처음 만들 때만 켜세요. 기존 표 아래에 추가할 때는 끕니다.")
    snapshots, actions = export_month(as_of, view, edited_plan, st.session_state.get("month_memo", ""), st.session_state.strategies)
    category_month = export_category_month(as_of, view, st.session_state.get("month_memo", ""))
    next_holdings, execution_warnings = next_holdings_after_execution(st.session_state.holdings, edited_plan, view)

    if run_blockers:
        st.error("가격 또는 전략 설정 오류가 있어 이번 달 스냅샷과 액션 출력을 잠갔습니다.")
        for issue in run_blockers:
            st.warning(issue)
    else:
        st.markdown("#### 1 · 월말 스냅샷 — Snapshots 탭에 누적")
        st.code(to_tsv(snapshots, include_header=include_header), language=None)
        st.download_button(
            "스냅샷 CSV 다운로드", to_csv_bytes(snapshots),
            file_name=f"snapshots_{as_of.isoformat()}.csv", mime="text/csv",
        )

        st.markdown("#### 2 · 자산군 월별 요약 — 선택 기록")
        st.caption("선진국 주식·신흥국 주식·채권·금·현금의 월별 평가액과 전체 비중입니다.")
        st.code(to_tsv(category_month, include_header=include_header), language=None)

        st.markdown("#### 3 · 액션 및 체결 이력 — Actions 탭에 누적")
        if actions.empty:
            st.info("이번 달 주문 대상이 없습니다. 장기보유 전략과 유지 종목은 스냅샷에만 기록됩니다.")
        else:
            st.code(to_tsv(actions, include_header=include_header), language=None)
            st.download_button(
                "액션 CSV 다운로드", to_csv_bytes(actions),
                file_name=f"actions_{as_of.isoformat()}.csv", mime="text/csv",
            )

    st.markdown("#### 4 · 다음 달 보유내역 — Holdings 탭 전체 교체")
    st.caption("실행 체크된 주문의 실제수량과 실제체결금액을 반영했습니다. 수수료·세금·잔여 현금은 아래 표에서 최종 확인해 수정하세요.")
    for warning in execution_warnings:
        st.warning(warning)
    next_holdings_editor = st.data_editor(
        next_holdings, key="next_holdings_editor", use_container_width=True, hide_index=True,
        column_config={
            "target_pct": st.column_config.NumberColumn(format="%.2f"),
            "shares": st.column_config.NumberColumn(min_value=0.0, format="%.4f"),
        },
    )
    st.code(to_tsv(next_holdings_editor), language=None)
    st.download_button(
        "다음 달 Holdings CSV 다운로드", to_csv_bytes(next_holdings_editor),
        file_name=f"holdings_after_{as_of.isoformat()}.csv", mime="text/csv",
    )

    st.markdown("#### 5 · 전략 설정 — Strategies 탭 전체 교체")
    st.code(to_tsv(st.session_state.strategies), language=None)
    st.download_button(
        "전략 설정 CSV 다운로드", to_csv_bytes(st.session_state.strategies),
        file_name="strategies.csv", mime="text/csv",
    )

    st.markdown("#### 입출금 원장 — Cashflows 탭 전체 교체")
    st.code(to_tsv(st.session_state.cashflows), language=None)
    st.download_button("입출금 CSV 다운로드", to_csv_bytes(st.session_state.cashflows), file_name="cashflows.csv", mime="text/csv")

    st.markdown("#### 자산군 목표비중 — CategoryTargets 탭 전체 교체")
    st.code(to_tsv(st.session_state.category_targets), language=None)
    st.download_button("자산군 목표 CSV 다운로드", to_csv_bytes(st.session_state.category_targets), file_name="category_targets.csv", mime="text/csv")
