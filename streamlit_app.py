"""Personal allocation desk — explicit evaluation, manual orders, portable records."""
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import hashlib
import hmac
import math
from html import escape
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st
from streamlit_app import engine, studio
from streamlit_app.data import (DataError, load_default_holdings, load_default_strategies,
    normalize_holdings, normalize_strategies, normalize_category_targets, map_columns, HOLDING_COLUMNS,
    read_workbook, to_csv_bytes, to_tsv)
from streamlit_app.workflow import run_evaluation, records, stable_id, revise_proposal, classification_view
from streamlit_app.ledger import (TABLES, empty_workspace, backup_bytes, restore_backup,
    freeze_run, execution_draft, apply_executions, latest_snapshots, parse_table,
    validate_actions, snapshots_match, load_frozen_run, order_status, cancel_orders)
from streamlit_app.performance import summarize, validate_flows, monthly_risk, benchmark_index
from streamlit_app.sheets_sync import load_workspace, save_workspace
import importlib

import streamlit_app.ui as ui_helpers

# Streamlit Cloud can rerun this entrypoint while retaining an older imported
# helper module during a multi-file deployment. Reload once when the newly
# deployed allocation helpers are not present so the app does not fail during
# that short-lived mixed-version state.
if not hasattr(ui_helpers, 'allocation_status_frame'):
    ui_helpers = importlib.reload(ui_helpers)

numeric_column_config = ui_helpers.numeric_column_config
allocation_status_frame = ui_helpers.allocation_status_frame
style_allocation_rows = ui_helpers.style_allocation_rows

pio.templates.default='plotly_white'
st.set_page_config(page_title='Rebalance · 자산배분', page_icon='◈', layout='wide')
st.markdown('<style>'+Path(__file__).with_name('streamlit_app').joinpath('theme.css').read_text(encoding='utf-8')+'</style>',unsafe_allow_html=True)

PAGE_DESCRIPTIONS={
    '이번 달':'보유내역과 실제 종가를 확인하고 이번 평가의 주문안을 준비합니다.',
    '자산 현황':'전략·역할·자산 분류별 평가액과 목표 비중의 차이를 살펴봅니다.',
    '주문안':'다음 거래일에 직접 입력할 수량과 예상 잔여현금을 검토합니다.',
    '전략실':'조건, 실행 주기와 판정별 동작을 한 화면에서 설계하고 검증합니다.',
    '기록':'평가와 체결 내역을 확정하고 기간별 성과를 확인합니다.',
    '설정':'Google Sheets 연결, 백업·복원과 수동 가격을 관리합니다.',
}
PAGES=list(PAGE_DESCRIPTIONS)


def workflow_steps(labels, active=1, completed=0):
    """Show progress as a status tracker; navigation is provided by real buttons."""
    bars=[]
    for i,_ in enumerate(labels,1):
        state=' is-done' if i<=completed else ' is-active' if i==active else ''
        bars.append(f'<span class="workflow-bar{state}"></span>')
    active=max(1,min(active,len(labels)))
    next_step=f'다음: {escape(labels[active])}' if active<len(labels) else '마지막 단계'
    st.markdown(
        '<div class="workflow" role="status" aria-label="운영 진행 상태">'
        f'<div class="workflow-bars" aria-hidden="true">{"".join(bars)}</div>'
        f'<div class="workflow-meta"><span>단계 {active}/{len(labels)} · <strong>{escape(labels[active-1])}</strong></span>'
        f'<span>{next_step}</span></div></div>',unsafe_allow_html=True)


def navigate(page, account=None):
    st.session_state.workspace_page=page
    st.session_state.mobile_workspace_page=page
    if account is not None:
        st.session_state.order_account=account


def use_result_date():
    day=date.fromisoformat(st.session_state.run['date'])
    st.session_state.sidebar_as_of=day
    st.session_state.mobile_as_of=day


def open_saved_evaluation():
    try:
        run=load_frozen_run(st.session_state.evaluations,st.session_state.saved_run_choice)
        st.session_state.run=run
        st.session_state.fills=execution_draft(run)
        st.session_state.fills_run_id=run['id']
        use_result_date()
        navigate('주문안','전체 계좌')
    except DataError as e:st.session_state.record_error=str(e)


def holding_identity(row):
    return json.dumps([str(row.strategy),str(row.account),str(row.ticker)],ensure_ascii=False)


def remember_holding_input(identity, widget, original):
    drafts=st.session_state.setdefault('holding_drafts',{})
    raw=st.session_state[widget]
    try:
        unchanged=parse_mobile_quantity(raw,'보유수량')==original
    except DataError:
        unchanged=False
    if unchanged:drafts.pop(identity,None)
    else:drafts[identity]=raw


def discard_holding_inputs(identities):
    for identity in identities:
        st.session_state.setdefault('holding_drafts',{}).pop(identity,None)
    st.session_state.holdings_revision=st.session_state.get('holdings_revision',0)+1


def sync_page(source, target):
    st.session_state[target]=st.session_state[source]


def sync_date(source, target):
    st.session_state[target]=st.session_state[source]


def target_legend(frame):
    counts=frame['목표상태'].value_counts() if not frame.empty else {}
    st.markdown(
        '<div class="target-legend" aria-label="목표 비중 상태 범례">'
        f'<span class="target-chip under">미달 {int(counts.get("미달",0))}</span>'
        f'<span class="target-chip met">충족 {int(counts.get("충족",0))}</span>'
        f'<span class="target-chip over">초과 {int(counts.get("초과",0))}</span>'
        '</div>',unsafe_allow_html=True)


def show_allocation_status(frame, columns, key):
    visible=frame[columns].copy()
    with st.container(key='desktop_'+key):
        st.dataframe(style_allocation_rows(visible),hide_index=True,use_container_width=True,key=key,
            column_config=numeric_column_config(visible.columns))
    with st.container(key='mobile_'+key):
        st.markdown(mobile_allocation_cards(frame),unsafe_allow_html=True)


def mobile_allocation_cards(frame):
    """Show the decision and proposed order without horizontal table scrolling."""
    if frame.empty:
        return ''
    quantities=pd.to_numeric(frame['제안수량'],errors='coerce').fillna(0)
    ordered=frame.assign(_needs_order=quantities.ne(0)).sort_values('_needs_order',ascending=False)
    cards=[]
    for _,row in ordered.iterrows():
        status=str(row['목표상태'])
        status_class={'미달':'under','초과':'over','충족':'met'}.get(status,'met')
        name=escape(str(row['종목']))
        strategy=escape(str(row['전략']))
        ticker=escape(str(row['티커']))
        action=escape(str(row['구분']))
        quantity=float(row['제안수량'])
        shares=f'{abs(quantity):,.4f}'.rstrip('0').rstrip('.')
        amount=float(row['예상매매액']) if '예상매매액' in row and pd.notna(row['예상매매액']) else 0.
        order=(f'{action} {shares}주' if quantity else '이번 주문 없음')
        money=f'{abs(amount):,.0f}원' if quantity else ''
        cards.append(
            f'<article class="asset-card status-{status_class}" aria-label="{strategy} {name} {escape(status)}">'
            f'<div class="asset-card-head"><span class="asset-card-name">{name}</span>'
            f'<span class="target-chip {status_class}">{escape(status)}</span></div>'
            f'<div class="asset-card-meta">{strategy} · {ticker}</div>'
            f'<div class="asset-card-weights"><div><span>현재 비중</span><strong>{float(row["현재비중(%)"]):.2f}%</strong></div>'
            f'<span class="asset-card-arrow" aria-hidden="true">→</span>'
            f'<div><span>실행 목표</span><strong>{float(row["실행목표(%)"]):.2f}%</strong></div></div>'
            f'<div class="asset-card-gap">목표와 차이 {float(row["괴리(%p)"]):+.2f}%p</div>'
            f'<div class="asset-card-order"><span>{order}</span><strong>{money}</strong></div></article>'
        )
    return '<div class="asset-card-list">'+''.join(cards)+'</div>'


def parse_mobile_quantity(raw, label):
    try:
        quantity=float(raw.replace(',','').strip())
    except ValueError as exc:
        raise DataError(f'{label}: 수량 또는 현금에 숫자를 입력하세요.') from exc
    if not math.isfinite(quantity) or quantity<0:
        raise DataError(f'{label}: 0 이상의 유한한 숫자를 입력하세요.')
    return quantity

@st.cache_data(ttl=900,show_spinner=False)
def prices(ticker,market,day,adjusted=False):
    return engine._series(ticker,market,day,adjusted)


def workspace():
    return {k:st.session_state[k] for k in TABLES}


def working_draft():
    keys=['run','fills','fills_run_id','overrides','demo','post_execution','holding_drafts']
    return {k:st.session_state[k] for k in keys if k in st.session_state}


def remote_settings():
    try:
        return {key:str(st.secrets.get(key,'')) for key in ['SHEETS_WEBAPP_URL','SHEETS_SECRET','APP_PASSWORD']}
    except FileNotFoundError:
        return {}


remote=remote_settings()
remote_enabled=bool(remote.get('SHEETS_WEBAPP_URL'))
if remote_enabled:
    if len(remote.get('APP_PASSWORD',''))<12:
        st.error('개인 원장을 연결하려면 Streamlit Secrets에 12자 이상의 APP_PASSWORD를 설정하세요.')
        st.stop()
    auth_version=hashlib.sha256(remote['APP_PASSWORD'].encode()).hexdigest()
    if st.session_state.get('_authenticated')!=auth_version:
        st.title('자산배분 작업 공간')
        with st.form('login'):
            password=st.text_input('앱 비밀번호',type='password',key='_login_password')
            if st.form_submit_button('열기'):
                if hmac.compare_digest(password.encode(),remote['APP_PASSWORD'].encode()):
                    st.session_state._authenticated=auth_version
                    st.rerun()
                else:st.error('비밀번호를 확인하세요.')
        st.stop()
    st.session_state.pop('_login_password',None)


def install(data, invalidate=True):
    for k,v in data.items():
        st.session_state[k]=v
    if 'holdings' in data:
        st.session_state.holdings_revision=st.session_state.get('holdings_revision',0)+1
        st.session_state.pop('holding_drafts',None)
    if invalidate:
        st.session_state.pop('run',None)
        st.session_state.pop('fills',None)
        st.session_state.pop('post_execution',None)
    st.session_state.pop('sheet_verified',None)
    st.session_state.dirty=True


def export_table(label,frame,key):
    st.caption(f'{label} · {len(frame)}행')
    header=st.checkbox('헤더 포함',True,key=key+'_header')
    st.code(to_tsv(frame,include_header=header),language=None)
    st.download_button(f'{label} CSV 다운로드',to_csv_bytes(frame),file_name=f'{key}.csv',mime='text/csv',key=key+'_download')


def format_won(value):
    return f'{value:,.0f}원'


def monthly_summary_html(run):
    view,plan=run['view'],run['plan']
    total=float(view['평가액'].sum())
    cash=float(view.loc[view.ticker.eq('CASH'),'평가액'].sum())
    orders=int(plan['제안수량'].ne(0).sum()) if not plan.empty else 0
    label='평가 가능 자산' if run['errors'] else '총자산'
    return (f'<div class="monthly-summary" aria-label="이번 평가 요약">'
        f'<div class="summary-hero"><span>{label}</span><strong>{format_won(total)}</strong>'
        f'<small>실제 가격일 {escape(", ".join(sorted(view.price_date.astype(str).unique())))}</small></div>'
        f'<div class="summary-mini"><span>실제 CASH</span><strong>{format_won(cash)}</strong></div>'
        f'<div class="summary-mini"><span>주문 대상</span><strong>{orders}종목</strong></div></div>')


def order_cards_html(plan):
    """Compact manual order review; the detailed table remains available below."""
    orders=plan.loc[pd.to_numeric(plan['제안수량'],errors='coerce').fillna(0).ne(0)].copy()
    if orders.empty:
        return '<p class="decision-note">선택한 범위에 남은 주문이 없습니다.</p>'
    orders=orders.sort_values('제안수량',ascending=False)
    rows=[]
    for _,row in orders.iterrows():
        buy=float(row['제안수량'])>0
        quantity=f'{abs(float(row["제안수량"])):,.4f}'.rstrip('0').rstrip('.')
        amount=f'{float(row["예상매매액"]):+,.0f}원'
        gap=f'{float(row["괴리(%p)"]):+.1f}%p'
        name=escape(str(row['종목']))
        rows.append(
            f'<div class="order-row"><span class="order-side {"buy" if buy else "sell"}">{"매수" if buy else "매도"}</span>'
            f'<div class="order-name"><strong>{name}</strong><small>{escape(str(row["전략"]))} · '
            f'{escape(str(row["티커"]))} · {escape(str(row["목표상태"]))} {gap}'
            f' · {escape(str(row.get("상태","미실행")))}</small></div>'
            f'<div class="order-amount"><strong>{"+" if buy else "-"}{quantity}주</strong>'
            f'<small>{amount}</small></div></div>')
    return '<div class="order-list" aria-label="남은 수동 주문">'+''.join(rows)+'</div>'


def remaining_order_frame(plan, status):
    result=plan.copy()
    if status.empty:return result
    lookup=status.set_index('주문ID')
    result['상태']=result['주문ID'].map(lookup['상태']).fillna('유지')
    remaining=result['주문ID'].map(lookup['잔여수량']).fillna(0)
    remaining=remaining.where(~result['상태'].isin(['완료','취소']),0)
    result['제안수량']=remaining.where(result['제안수량'].ge(0),-remaining)
    result['예상매매액']=result['제안수량']*result['단위금액']
    return result


def show_frame(frame, **kwargs):
    """Render a table with consistent numeric display formats."""
    custom = kwargs.pop('column_config', None)
    return st.dataframe(frame, column_config=numeric_column_config(frame.columns, custom), **kwargs)


def edit_frame(frame, **kwargs):
    """Render an editor with consistent numeric display formats."""
    custom = kwargs.pop('column_config', None)
    return st.data_editor(frame, column_config=numeric_column_config(frame.columns, custom), **kwargs)


def run_ready():
    if 'run' not in st.session_state:
        st.info('보유내역을 확인한 뒤 ‘이번 달’에서 지정일 종가를 조회하세요.')
        st.button('이번 달에서 종가 확인',on_click=navigate,args=('이번 달',))
        return None
    if st.session_state.get('holding_drafts'):
        st.warning('아직 적용하지 않은 보유수량이 있습니다. 입력을 적용하거나 취소한 뒤 주문을 확인하세요.')
        st.button('보유수량 입력으로 돌아가기',on_click=navigate,args=('이번 달',))
        return None
    if st.session_state.run['date']!=str(as_of):
        st.info('선택한 기준일과 평가 결과의 날짜가 다릅니다.')
        st.button('선택한 기준일로 다시 평가',on_click=navigate,args=('이번 달',))
        st.button('기존 평가일로 돌아가기',on_click=use_result_date)
        return None
    return st.session_state.run


if 'holdings' not in st.session_state:
    install(empty_workspace())
    st.session_state.holdings=load_default_holdings()
    st.session_state.strategies=normalize_strategies(load_default_strategies())
    st.session_state.cashflows=pd.DataFrame(columns=['date','amount','memo','strategy','kind','transfer_id'])
    st.session_state.category_targets=pd.DataFrame(columns=['category','target_pct'])
    st.session_state.demo=True
    st.session_state.dirty=False
if 'overrides' not in st.session_state:
    st.session_state.overrides={}
if remote_enabled and not st.session_state.get('remote_loaded'):
    try:
        with st.spinner('Sheets 원장을 불러오는 중입니다…'):
            loaded,token=load_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'])
        st.session_state.remote_token=token
        if any(not table.empty for table in loaded.values()):
            install(loaded)
            st.session_state.demo=False
        st.session_state.remote_loaded=True
        st.session_state.dirty=False
    except DataError as e:
        st.error(str(e))
        st.button('원장 다시 읽기')
        st.stop()

def save_remote_workspace():
    if st.session_state.get('holding_drafts'):
        st.warning('입력 중인 보유수량을 이번 달에서 적용하거나 취소한 뒤 저장하세요. 전체 작업 백업에는 입력 중인 값도 포함됩니다.')
        return
    try:
        with st.spinner('원장을 저장하고 다시 확인합니다…'):
            st.session_state.remote_token=save_workspace(
                remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'],workspace(),st.session_state.remote_token)
        st.session_state.dirty=False
        st.session_state.sync_message='Sheets 저장·재조회 확인 완료'
    except DataError as e:
        st.error(str(e))


today=datetime.now(ZoneInfo('Asia/Seoul')).date()
st.session_state.setdefault('workspace_page',PAGES[0])
st.session_state.setdefault('mobile_workspace_page',st.session_state.workspace_page)
st.session_state.setdefault('sidebar_as_of',today)
st.session_state.setdefault('mobile_as_of',st.session_state.sidebar_as_of)

with st.sidebar:
    st.markdown('<div class="terminal-brand"><span class="terminal-brand-mark">R</span>'
        '<span><span class="terminal-brand-name">Rebalance</span><br>'
        '<span class="terminal-brand-sub">ALLOCATION DESK</span></span></div>',unsafe_allow_html=True)
    page=st.radio('작업 공간',PAGES,key='workspace_page',label_visibility='collapsed',
        on_change=sync_page,args=('workspace_page','mobile_workspace_page'))
    st.divider()
    as_of=st.date_input('평가 기준일',max_value=today,key='sidebar_as_of',
        on_change=sync_date,args=('sidebar_as_of','mobile_as_of'),
        help='월말에 한정하지 않습니다. 분기 규칙은 선택한 달이 3·6·9·12월인지 확인합니다.')
    st.caption('CASH = 원화 잔액 · 가격 1\n\n매도대금 재사용·거래 비용 계산 없음')
    if st.session_state.demo:
        st.warning('DEMO · 예시 보유내역')
    if st.session_state.get('dirty'):
        st.caption('저장할 변경사항 있음')
    if remote_enabled:
        if st.button('Sheets에 저장',type='primary',disabled=st.session_state.demo,use_container_width=True):
            save_remote_workspace()
        if st.session_state.get('sync_message') and not st.session_state.get('dirty'):
            st.success(st.session_state.sync_message)
    else:st.caption('Sheets 수동 기록 모드')
    st.download_button('전체 작업 백업',backup_bytes(workspace(),working_draft()),'rebalance-backup.json','application/json',use_container_width=True)

with st.container(key='mobile_toolbar'):
    badge=('입력 미적용' if st.session_state.get('holding_drafts') else 'DEMO' if st.session_state.demo else
        '저장 필요' if st.session_state.get('dirty') else '원장 연결' if remote_enabled else '수동 기록')
    st.markdown('<div class="mobile-brand"><strong><span>◈</span> REBALANCE</strong>'
                f'<em>{escape(badge)}</em></div>',unsafe_allow_html=True)
    menu_col,date_col=st.columns([1.25,1])
    with menu_col:
        st.selectbox('메뉴',PAGES,key='mobile_workspace_page',
            format_func=lambda value:f'메뉴  {value}',
            on_change=sync_page,args=('mobile_workspace_page','workspace_page'))
    with date_col:
        st.date_input('평가 기준일',max_value=today,key='mobile_as_of',
            on_change=sync_date,args=('mobile_as_of','sidebar_as_of'))
    with st.popover('원장 저장 · 백업',use_container_width=True):
        if remote_enabled:
            if st.button('Sheets 저장',key='mobile_save',type='primary',
                         disabled=st.session_state.demo,use_container_width=True):
                save_remote_workspace()
            if st.session_state.get('sync_message') and not st.session_state.get('dirty'):
                st.success(st.session_state.sync_message)
        st.download_button('전체 작업 백업',backup_bytes(workspace(),working_draft()),
            'rebalance-backup.json','application/json',key='mobile_backup',use_container_width=True)

current_status=st.session_state.get('run')
if current_status and current_status['date']==str(as_of):
    status_text='일부 계좌 확인 필요' if current_status['errors'] else '평가 완료'
    status_class='blocked' if current_status['errors'] else 'ready'
else:
    status_text='종가 조회 대기'
    status_class='waiting'
record_text='DEMO' if st.session_state.demo else '저장할 변경사항' if st.session_state.get('dirty') else '원장 확인'
st.markdown(
    '<div class="terminal-status" aria-label="평가 상태">'
    f'<span class="{status_class}">● {escape(status_text)}</span>'
    f'<span>기준일 <b>{as_of.isoformat()}</b></span>'
    f'<span>기록 <b>{escape(record_text)}</b></span>'
    '<span>수동 주문</span></div>',unsafe_allow_html=True)
st.markdown('<div class="eyebrow">ALLOCATION WORKSPACE</div>',unsafe_allow_html=True)
st.title(page)
st.markdown(f'<p class="page-description">{PAGE_DESCRIPTIONS[page]}</p>',unsafe_allow_html=True)
if 'run' in st.session_state and st.session_state.run['date']!=str(as_of):
    st.warning(f"현재 평가 결과는 {st.session_state.run['date']} 기준입니다. 새 기준일로 다시 조회하세요.")

if page=='이번 달':
    current_run=st.session_state.get('run')
    if current_run and current_run['date']!=str(as_of):current_run=None
    if st.session_state.get('holding_drafts'):
        workflow_steps(['보유내역 확인','종가 확정','규칙 판정','주문안 검토','기록'],active=1,completed=0)
    elif current_run and not current_run.get('errors'):
        workflow_steps(['보유내역 확인','종가 확정','규칙 판정','주문안 검토','기록'],active=4,completed=3)
    elif current_run:
        workflow_steps(['보유내역 확인','종가 확정','규칙 판정','주문안 검토','기록'],active=3,completed=2)
    else:
        workflow_steps(['보유내역 확인','종가 확정','규칙 판정','주문안 검토','기록'],active=2,completed=1)
    with st.expander('1 · 보유수량과 현금 확인',expanded=current_run is None or bool(st.session_state.get('holding_drafts'))):
        st.caption('계좌를 선택해 수량과 원화 현금만 확인하세요. 종목 추가와 목표 비중 변경은 전체 표에서 합니다.')
        edit_mode=st.radio('보유내역 입력 방식',['계좌별 입력','전체 표'],horizontal=True,key='holdings_edit_mode',label_visibility='collapsed')
        holdings=st.session_state.holdings
        if edit_mode=='계좌별 입력':
            accounts=list(holdings[['strategy','account']].drop_duplicates().itertuples(index=False,name=None))
            if accounts:
                selected=st.selectbox('수량을 확인할 계좌',accounts,
                    format_func=lambda pair:f'{pair[0]} · {pair[1]}',key='mobile_holdings_account')
                subset=holdings[holdings.strategy.eq(selected[0]) & holdings.account.eq(selected[1])]
                entries={}
                identities=[]
                revision=st.session_state.get('holdings_revision',0)
                for idx,row in subset.iterrows():
                    cash=str(row.ticker)=='CASH'
                    identity=holding_identity(row)
                    identities.append(identity)
                    display=f'{float(row.shares):,.0f}' if cash else f'{float(row.shares):,.8f}'.rstrip('0').rstrip('.')
                    label=f'{row["name"]} · {row.ticker} ({"원" if cash else "주"})'
                    widget=f'mobile_qty_{revision}_{idx}'
                    with st.container(key=f'holding_item_{idx}'):
                        st.markdown('<div class="holding-head">'
                            f'<strong>{escape(str(row["name"]))} · {escape(str(row.ticker))}</strong>'
                            f'<span>목표 {float(row.target_pct):g}% · {"원" if cash else "주"}</span></div>',unsafe_allow_html=True)
                        raw=st.text_input(label,value=st.session_state.get('holding_drafts',{}).get(identity,display),
                            key=widget,label_visibility='collapsed',on_change=remember_holding_input,
                            args=(identity,widget,float(row.shares)))
                        entries[idx]=(label,raw)
                pending=sum(identity in st.session_state.get('holding_drafts',{}) for identity in identities)
                st.caption(f'이 계좌에서 {pending}개 입력이 아직 적용되지 않았습니다.' if pending else '현재 보유수량과 현금입니다.')
                apply_col,cancel_col=st.columns([2,1])
                if apply_col.button('선택 계좌 보유내역 적용',type='primary',use_container_width=True):
                    try:
                        updated=holdings.copy()
                        for idx,(label,raw) in entries.items():
                            updated.at[idx,'shares']=parse_mobile_quantity(raw,label)
                        remaining={k:v for k,v in st.session_state.get('holding_drafts',{}).items() if k not in identities}
                        install({'holdings':normalize_holdings(updated)})
                        st.session_state.holding_drafts=remaining
                        st.session_state.demo=False
                        st.session_state.input_notice='선택 계좌의 보유내역을 적용했습니다. 종가를 조회해 주세요.'
                        st.rerun()
                    except DataError as e:st.error(str(e))
                cancel_col.button('입력 취소',disabled=not pending,use_container_width=True,
                    on_click=discard_holding_inputs,args=(identities,))
        else:
            st.caption('전체 표는 아래 적용 버튼을 누른 뒤 화면을 이동하세요.')
            if st.session_state.get('holding_drafts'):
                st.warning('계좌별 입력의 미적용 수량을 먼저 적용하거나 취소하세요.')
            with st.form('holdings_form'):
                edited=edit_frame(holdings,num_rows='dynamic',hide_index=True,use_container_width=True,
                    key=f'holdings_editor_{st.session_state.get("holdings_revision",0)}',
                    column_config={'shares':st.column_config.NumberColumn('보유수량 / CASH 원화 잔액',min_value=0.,format='%,.0f'),
                                   'ticker':st.column_config.TextColumn('티커'),'target_pct':st.column_config.NumberColumn('기본 목표 (%)',min_value=0.,max_value=100.)})
                if st.form_submit_button('보유내역 확인·적용',disabled=bool(st.session_state.get('holding_drafts'))):
                    try:
                        install({'holdings':normalize_holdings(edited)})
                        st.session_state.demo=False
                        st.session_state.input_notice='전체 보유내역을 적용했습니다. 종가를 조회해 주세요.'
                        st.rerun()
                    except DataError as e:st.error(str(e))
    if st.session_state.get('input_notice'):
        st.success(st.session_state.pop('input_notice'))
    manual_candidates=[]
    for _,strategy_row in st.session_state.strategies.iterrows():
        try:
            strategy_params=json.loads(strategy_row.params_json or '{}')
            cadence=strategy_params.get('scope',{}).get('run',strategy_params.get('frequency','monthly'))
            if cadence=='manual':manual_candidates.append(str(strategy_row.code))
        except (TypeError,ValueError):pass
    manual_codes=st.multiselect('이번 평가에서 수동 실행할 전략',manual_candidates,help='선택하지 않은 수동 전략은 자산만 평가하고 주문을 만들지 않습니다.') if manual_candidates else []
    if st.session_state.get('holding_drafts'):
        st.warning('입력 중인 보유수량을 모두 적용하거나 취소하면 종가를 조회할 수 있습니다.')
    if st.button('2 · 지정일 종가 조회·판정',type='secondary' if current_run else 'primary',use_container_width=True,disabled=bool(st.session_state.get('holding_drafts'))):
        prices.clear()
        try:
            with st.spinner('실제 종가와 전략별 신호를 확인하는 중입니다…'):
                run=run_evaluation(st.session_state.holdings,st.session_state.strategies,as_of,fetch=prices,overrides=st.session_state.overrides,manual_codes=manual_codes)
            st.session_state.run=run
            st.session_state.pop('post_execution',None)
            if st.session_state.get('fills_run_id')!=run['id']:
                st.session_state.fills=execution_draft(run)
                st.session_state.fills_run_id=run['id']
            st.rerun()
        except (DataError,ValueError) as e:
            st.error(str(e))
    run=current_run
    if run and not st.session_state.get('holding_drafts'):
        view,plan=run['view'],run['plan']
        for code,message in run['errors'].items():
            st.error(f'{code} · 확정 차단: {message}')
        if not view.empty:
            with st.container(key='desktop_monthly_metrics'):
                a,b,c,d=st.columns(4)
                a.metric('평가 가능 자산' if run['errors'] else '총자산',format_won(view['평가액'].sum()))
                b.metric('실제 CASH',format_won(view.loc[view.ticker.eq('CASH'),'평가액'].sum()))
                c.metric('주문 대상',f"{int(plan['제안수량'].ne(0).sum())}종목")
                d.metric('확인 필요',f"{len(run['errors'])}계좌")
            with st.container(key='mobile_monthly_summary'):
                st.markdown(monthly_summary_html(run),unsafe_allow_html=True)
            st.caption(f"요청일 {run['date']} · 실제 가격일 {', '.join(sorted(view.price_date.astype(str).unique()))}")
            st.button('주문안 검토하기',type='primary',use_container_width=True,
                on_click=navigate,args=('주문안','전체 계좌'))
            st.subheader('3 · 계좌별 판정')
            for decision in run['decisions']:
                code=decision['strategy'];sub=view[view.strategy.eq(code)]
                account_plan=plan.loc[plan['전략'].eq(code)]
                order_count=int(account_plan['제안수량'].ne(0).sum())
                label=('주문 생성' if order_count else '일정 대기' if decision['status']=='일정 대기' else '보유 유지')
                tone={'주문 생성':'order','일정 대기':'wait','보유 유지':'hold'}[label]
                messages={'sma_filter_rebalance':'SMA 필터와 분기말 목표 복원 판정',
                    'momentum_rotate':'모멘텀 순위와 이동평균 조건 판정','drawdown_buy':'낙폭 매수 조건 판정',
                    'drawdown_shift':'낙폭에 따른 목표 비중 판정','hold':'매매 없이 보유 유지','static':'목표 비중 복원 판정'}
                message=messages.get(decision['message'],decision['message'])
                with st.container(border=True,key=f'decision_card_{code}'):
                    st.markdown('<div class="decision-top">'
                        f'<strong>{escape(code)} · {escape(str(sub.account.iloc[0]))}</strong>'
                        f'<b>{format_won(sub["평가액"].sum())}</b></div>'
                        f'<div class="decision-note"><span class="decision-badge {tone}">{label}</span> '
                        f'{escape(str(message))}</div>',unsafe_allow_html=True)
                    target_legend(allocation_status_frame(account_plan,run['strategies']))
                    if order_count:
                        st.button(f'{order_count}개 주문 보기',key='account_orders_'+code,
                            on_click=navigate,args=('주문안',code),use_container_width=True)
                    elif decision.get('next_run'):
                        st.caption(f'다음 기준일 {decision["next_run"]}')
                    with st.expander('판정 근거 보기'):
                        st.caption(f'{decision["status"]} · {message}')
                        if decision.get('evidence'):
                            show_frame(pd.DataFrame(decision['evidence']),hide_index=True,use_container_width=True)
                        show_frame(account_plan[['종목','현재비중(%)','실행목표(%)','제안수량','근거']],hide_index=True,use_container_width=True)
            if not plan.empty:
                with st.expander('전체 종목의 목표 비중 비교'):
                    st.caption('현재 비중과 이번 규칙 판정의 실행 목표를 비교합니다. 전략별 허용 괴리 안은 충족입니다.')
                    status_frame=allocation_status_frame(plan,run['strategies'])
                    target_legend(status_frame)
                    show_allocation_status(status_frame,
                        ['전략','종목','티커','목표상태','현재비중(%)','실행목표(%)','괴리(%p)','구분','제안수량'],
                        'monthly_allocation_status')
                st.button('자산 현황 자세히 보기',use_container_width=True,
                    on_click=navigate,args=('자산 현황',))
            else:
                st.info('이번 평가에서 생성된 주문안이 없습니다.')
        else:
            st.info('가격이 확정된 계좌가 없습니다. 입력값 또는 종가 확정 시점을 확인하세요.')

elif page=='자산 현황':
    run=run_ready()
    if run and not run['view'].empty:
        if run['errors']:
            st.warning('오류 계좌를 제외한 부분 현황입니다: '+', '.join(run['errors']))
        view=run['view'];total=float(view['평가액'].sum())
        grouping=st.radio('집계 기준',['분류','역할','계좌'],horizontal=True)
        col={'분류':'category','역할':'role','계좌':'account'}[grouping]
        grouped=(classification_view(view) if col=='category' else view).groupby(col,dropna=False,as_index=False)['평가액'].sum()
        grouped['비중(%)']=grouped['평가액']/total*100 if total else 0.
        if col=='category' and not st.session_state.category_targets.empty:
            grouped=grouped.merge(st.session_state.category_targets,on='category',how='outer').fillna(0)
            grouped['목표대비괴리(%p)']=grouped['비중(%)']-grouped.target_pct
        st.plotly_chart(px.bar(grouped,x='비중(%)',y=col,orientation='h',color=col,
            color_discrete_sequence=['#f7931a','#38bdf8','#a855f7','#22c55e','#eab308','#64748b']),use_container_width=True)
        show_frame(grouped,hide_index=True,use_container_width=True)
        if col=='category':
            with st.expander('전체 분류 목표 편집'):
                with st.form('category_targets_form'):
                    target_edit=edit_frame(st.session_state.category_targets,num_rows='dynamic',hide_index=True)
                    if st.form_submit_button('분류 목표 검증·적용'):
                        try:
                            install({'category_targets':normalize_category_targets(target_edit)},invalidate=False)
                            st.rerun()
                        except DataError as e:st.error(str(e))
        st.subheader('종목별 평가와 목표')
        detail=view.merge(run['plan'][['전략','티커','실행목표(%)','실행후비중(%)']],left_on=['strategy','ticker'],right_on=['전략','티커'])
        query=st.text_input('종목코드·종목명 검색')
        if query:
            detail=detail[detail.ticker.str.contains(query,case=False,regex=False,na=False)|detail.name.str.contains(query,case=False,regex=False,na=False)]
        detail_view=detail[['strategy','name','ticker','shares','close','currency','fx','평가액','현재비중','target_pct','실행목표(%)','실행후비중(%)','price_date','price_source']].rename(columns={'name':'종목명','ticker':'티커'})
        show_frame(detail_view,hide_index=True,use_container_width=True)

elif page=='주문안':
    run=run_ready()
    if run and not run['plan'].empty:
        plan=run['plan']
        frozen=not st.session_state.evaluations.empty and run['id'] in set(st.session_state.evaluations.run_id)
        workflow_steps(['보유내역 확인','종가 확정','규칙 판정','주문안 검토','기록'],
            active=5 if frozen else 4,completed=4 if frozen else 3)
        status_plan=allocation_status_frame(plan,run['strategies'])
        accounts=run['view'].groupby('strategy').account.first().to_dict()
        choices=['전체 계좌']+list(dict.fromkeys(plan['전략'].astype(str)))
        if st.session_state.get('order_account') not in choices:st.session_state.order_account='전체 계좌'
        account=st.selectbox('주문할 계좌',choices,key='order_account',
            format_func=lambda code:code if code=='전체 계좌' else f'{code} · {accounts.get(code,code)}')
        scoped=status_plan if account=='전체 계좌' else status_plan[status_plan['전략'].eq(account)]
        counts=scoped['목표상태'].value_counts()
        selected_status=st.radio('목표 비중 상태',['전체','미달','충족','초과'],horizontal=True,
            format_func=lambda value:f'{value} {len(scoped) if value=="전체" else int(counts.get(value,0))}',key='order_target_filter')
        status=order_status(run,st.session_state.actions)
        remaining=remaining_order_frame(scoped,status)
        visible=remaining if selected_status=='전체' else remaining[remaining['목표상태'].eq(selected_status)]
        order_count=int(visible['제안수량'].ne(0).sum())
        st.subheader(f'입력할 주문 {order_count}개')
        dates=sorted(visible.loc[visible['제안수량'].ne(0),'주문예정일'].astype(str).unique())
        if dates:st.caption('주문 예정일 '+', '.join(dates)+' · 남은 수량 기준')
        st.markdown(order_cards_html(visible),unsafe_allow_html=True)
        st.caption('매수는 파랑, 매도는 빨강입니다. 완료·취소한 주문은 제외하고 부분 체결은 남은 수량을 표시합니다.')
        with st.expander('계좌별 현금 계획',expanded=True):
            st.caption('평가 당시 주문안 전체를 기준종가로 실행했을 때의 예상입니다. 필터를 바꿔도 계획 금액은 같습니다.')
            for code,group in scoped.groupby('전략',sort=False):
                expected=float(group['예상잔여현금'].iloc[0])
                st.markdown('<div class="cash-forecast">'
                    f'<span>{escape(code)} · {escape(str(accounts.get(code,code)))}<br>계획 완료 후 예상 현금</span>'
                    f'<strong>{format_won(expected)}</strong></div>',unsafe_allow_html=True)
            st.caption('비용·세금 미포함 · 매도대금은 이번 주문안의 매수 재원에 포함하지 않습니다.')
        with st.expander('전체 주문 · 목표 비중 비교'):
            st.caption('파랑은 목표 미달, 초록은 허용 괴리 이내, 빨강은 목표 초과입니다. 평가 당시 제안 수량을 표시합니다.')
            show_allocation_status(scoped,
                ['전략','종목','티커','목표상태','현재비중(%)','실행목표(%)','괴리(%p)','구분','기준종가','보유수량','목표조정액','제안수량','예상매매액','실행후비중(%)','예상잔여현금','주문예정일','근거'],
                'order_allocation_status')
        with st.expander('제안 수량 수정'):
            st.caption('전체 계좌의 평가 당시 제안을 수정합니다. 이미 체결한 주문은 실제 체결 기록에서 관리하세요.')
            with st.form('revise_order_'+run['id']):
                edited_order=edit_frame(plan[['주문ID','전략','종목','티커','제안수량']],disabled=['주문ID','전략','종목','티커'],hide_index=True,use_container_width=True)
                edit_reason=st.text_input('주문안 수정 사유')
                if st.form_submit_button('수량·현금 검증 후 주문안 수정'):
                    try:
                        revised=revise_proposal(run,edited_order,edit_reason)
                        st.session_state.run=revised
                        st.session_state.fills=execution_draft(revised)
                        st.session_state.fills_run_id=revised['id']
                        st.rerun()
                    except (DataError,ValueError) as e:st.error(str(e))
        st.download_button('전체 주문안 CSV 다운로드',to_csv_bytes(plan),'manual-orders.csv','text/csv')
        if plan['현금제약'].any():
            st.warning('일부 매수 수량이 CASH 한도에 따라 축소되었습니다. 매도대금은 같은 주문안에서 재사용하지 않습니다.')
        if st.session_state.get('fills_run_id')!=run['id']:
            st.session_state.fills=execution_draft(run);st.session_state.fills_run_id=run['id']
        if not frozen:
            st.subheader('검토를 마치면 평가 확정')
            st.caption('전체 계좌의 평가와 주문안을 기록한 뒤 실제 체결을 입력합니다. 필터는 확정할 계좌를 제한하지 않습니다.')
            if run['errors']:st.warning('오류가 없는 계좌만 확정됩니다: '+', '.join(accounts))
            with st.expander('평가 메모 · 같은 날짜 개정 사유'):
                memo=st.text_input('평가 메모',key='order_snapshot_memo')
                reason=st.text_input('개정 사유',key='order_revision_reason')
            if st.button('평가 확정하고 체결 입력',type='primary',use_container_width=True):
                try:
                    updated,_=freeze_run(run,workspace(),memo,reason)
                    install(updated,invalidate=False)
                    st.rerun()
                except DataError as e:st.error(str(e))
        else:
            st.success('평가 확정 완료 · 실제 체결 내역을 입력할 수 있습니다.')
            if remote_enabled and st.session_state.get('dirty'):
                if st.button('확정 기록 Sheets에 저장',type='primary',use_container_width=True,
                             disabled=st.session_state.demo):save_remote_workspace()
            elif not remote_enabled:
                st.caption('확정 기록을 보존하려면 전체 작업 백업을 받거나 기록 화면에서 시트로 내보내세요.')
            with st.expander('실제 체결 반영',expanded=True):
                status=order_status(run,st.session_state.actions)
                if not status.empty:
                    show_frame(status.drop(columns='주문ID'),hide_index=True,use_container_width=True)
                    with st.expander('미실행·부분 체결 주문 취소 기록'):
                        choices=status[status['상태'].isin(['미실행','부분 체결'])]
                        cancel_ids=st.multiselect('남은 주문을 취소한 종목',choices['주문ID'].tolist(),format_func=lambda v:choices.set_index('주문ID').loc[v,'종목'])
                        cancel_reason=st.text_input('취소 사유')
                        if st.button('잔여 주문 취소 기록'):
                            try:
                                install(cancel_orders(workspace(),run,cancel_ids,cancel_reason),invalidate=False)
                                st.rerun()
                            except DataError as e:st.error(str(e))
                st.caption('체결일·수량·현지통화 단가·환율·원화 금액을 입력합니다. 부분 체결을 추가할 때는 체결 ID를 변경하세요.')
                if st.session_state.get('fills_run_id')!=run['id']:
                    st.session_state.fills=execution_draft(run);st.session_state.fills_run_id=run['id']
                fills=st.session_state.fills
                if not fills.empty:
                    editable=['실행','체결ID','체결일','실제수량','실제단가','실제환율','실제체결금액','메모']
                    show=['실행','전략','종목','티커','구분','제안수량','체결ID','체결일','실제수량','실제단가','실제환율','실제체결금액','메모']
                    edited=edit_frame(fills[show],hide_index=True,use_container_width=True,disabled=[c for c in show if c not in editable],key='fill_editor_'+run['id'])
                    saved=fills.copy()
                    for c in editable:saved[c]=edited[c]
                    st.session_state.fills=saved
                    if st.button('검증한 실제 체결만 반영',type='primary'):
                        try:
                            if workspace()['evaluations'].empty or run['id'] not in set(workspace()['evaluations'].run_id):
                                raise DataError('먼저 기록 화면에서 체결 전 평가를 확정하세요')
                            install(apply_executions(workspace(),saved,run),invalidate=False)
                            st.session_state.post_execution=True
                            st.rerun()
                        except (DataError,ValueError) as e:st.error(str(e))
                else:st.info('현재 제안된 거래가 없습니다.')
        if st.session_state.get('post_execution'):
            st.info('실제 체결을 반영했습니다. 변경된 보유내역과 체결 기록을 저장하세요. 이 주문안은 체결 전 평가이며 새 잔고로 계산하려면 이번 달에서 종가를 다시 조회하세요.')
        st.button('기록 화면으로 이동',use_container_width=True,on_click=navigate,args=('기록',))
    elif run:
        st.info('이번 평가에는 검토할 주문안이 없습니다. 이번 달에서 계좌별 확인 사항을 해결한 뒤 다시 조회하세요.')
        st.button('이번 달 확인 사항 보기',on_click=navigate,args=('이번 달',))

elif page=='전략실':
    st.caption('조건과 행동은 카드에서 편집합니다. 실제 종가를 조회하면 신호와 목표 금액을 검증할 수 있습니다.')
    if st.session_state.get('studio_notice'):st.success(st.session_state.pop('studio_notice'))
    run=st.session_state.get('run')
    def studio_prices(t,m,d):
        code=st.session_state.get('studio_code',st.session_state.strategies.code.iloc[0])
        row=st.session_state.strategies[st.session_state.strategies.code.eq(code)].iloc[0]
        key=f'studio_{code}_{row.get("version","1")}'
        adjusted=st.session_state.get(key,{}).get('signal_adjusted',False)
        from streamlit_app.market import validate_series
        return validate_series(prices(t,engine.resolved_market(t,m),d,adjusted),d,engine.resolved_market(t,m))
    if st.session_state.get('holding_drafts'):
        st.warning('입력 중인 보유수량을 이번 달에서 적용하거나 취소한 뒤 규칙을 검증하세요.')
    priced_view=(run['view'] if run and run['date']==str(as_of) and not run['view'].empty
        and not st.session_state.get('holding_drafts') else None)
    studio.render(st.session_state.strategies,st.session_state.holdings,priced_view,as_of,studio_prices,
        go_to_monthly=lambda:navigate('이번 달'))
    with st.expander('고급 전략 설정 · 표 편집'):
        st.caption('규칙 JSON을 직접 관리하거나 허용 괴리·현금 유보액을 바꿀 때 사용합니다.')
        with st.form('strategy_settings'):
            edited=edit_frame(st.session_state.strategies,hide_index=True,num_rows='dynamic',use_container_width=True,
                column_config={'tolerance_pct':st.column_config.NumberColumn('허용 괴리 (%p)',min_value=0.,max_value=100.),
                               'cash_reserve':st.column_config.NumberColumn('현금 유보액 (원)',min_value=0.,format='%,.0f'),
                               'fractional_us':st.column_config.CheckboxColumn('미국 소수점 수량 허용')})
            st.caption('허용 괴리 2는 목표 대비 2%p를 뜻합니다. CASH는 원화만 지원하며 외화 현금은 원화 환산 후 직접 입력합니다.')
            if st.form_submit_button('전략 설정 검증·적용'):
                try:
                    normalized=normalize_strategies(edited)
                    old=st.session_state.strategies
                    versions=st.session_state.strategy_versions.copy()
                    if not old.equals(normalized):
                        archive=old.copy();archive['archived_at']=pd.Timestamp.now(tz='UTC').isoformat()
                        versions=pd.concat([versions,archive],ignore_index=True).drop_duplicates()
                    install({'strategies':normalized,'strategy_versions':versions})
                    st.success('설정을 적용했습니다. Sheets 저장 또는 전체 백업이 필요합니다.')
                except DataError as e:st.error(str(e))

elif page=='기록':
    tabs=st.tabs(['평가 확정·Sheets 출력','기록·성과','입출금'])
    with tabs[0]:
        run=st.session_state.get('run')
        if run and not run['view'].empty:
            st.caption('평가를 먼저 확정하고 실제 체결은 나중에 반영합니다. 확정은 이 세션에 기록하며 Sheets에는 직접 붙여넣어야 합니다.')
            if run['errors']:st.warning('정상 계좌만 확정합니다. 전체 자산 성과에는 모든 계좌 기록이 필요합니다.')
            memo=st.text_input('평가 메모',key='snapshot_memo')
            reason=st.text_input('동일 날짜 기록을 수정하는 경우 개정 사유',key='revision_reason')
            if st.button('평가 스냅샷 확정',type='primary',disabled=run['date']!=str(as_of)):
                try:
                    updated,changed=freeze_run(run,workspace(),memo,reason)
                    install(updated,invalidate=False)
                    st.success('평가를 확정했습니다. 아래 표를 시트에 저장하세요.' if changed else '이미 확정된 평가입니다. 중복 생성하지 않았습니다.')
                except DataError as e:st.error(str(e))
        st.subheader('시트별 내보내기')
        st.caption('사이드바의 Sheets 저장으로 전체 원장을 보존하거나 아래 표를 직접 복사할 수 있습니다. 과거 기록과 개정도 포함합니다.' if remote_enabled else '기록 원본 전체를 출력합니다. 기존 탭을 교체할 때는 헤더부터 붙여넣으세요. 과거 기록과 개정도 포함합니다.')
        names={'holdings':'Holdings','strategies':'Strategies','snapshots':'Snapshots','actions':'Actions','cashflows':'Cashflows','category_targets':'CategoryTargets','evaluations':'Evaluations','strategy_versions':'StrategyVersions'}
        selected=st.selectbox('출력할 탭',TABLES,format_func=names.get)
        export_table(names[selected],workspace()[selected],selected)
        st.caption('Evaluations에는 원자료·규칙·주문안을 셀 길이 제한에 맞춰 나누어 보존합니다. 조각을 모두 복사하세요.')
        saved_runs=st.session_state.evaluations
        if not saved_runs.empty:
            selected_run=st.selectbox('확정 주문안 다시 열기',saved_runs.run_id.drop_duplicates().tolist(),key='saved_run_choice',
                format_func=lambda value:f'{saved_runs.loc[saved_runs.run_id.eq(value),"date"].iloc[0]} · {value[:8]}')
            st.button('확정한 평가·주문안 불러오기',on_click=open_saved_evaluation)
            if st.session_state.get('record_error'):st.error(st.session_state.pop('record_error'))
        if st.session_state.get('sheet_verified'):st.success(st.session_state.sheet_verified)
    with tabs[1]:
        history=st.session_state.snapshots
        if history.empty:st.info('평가 기록을 확정하거나 Snapshots를 불러오세요.')
        else:
            codes=['전체']+sorted(history.strategy.astype(str).unique().tolist())
            selected=st.selectbox('성과 계좌',codes)
            try:
                effective=latest_snapshots(history)
                dates=sorted(effective.date.astype(str).unique())
                a,b=st.columns(2)
                start=a.selectbox('분석 시작일',dates,index=0)
                end=b.selectbox('분석 종료일',dates,index=len(dates)-1)
                effective=effective[effective.date.astype(str).between(start,end)]
                if effective.empty:raise DataError('시작일 이후의 종료일을 선택하세요')
                if selected!='전체' and not effective.strategy.eq(selected).any():raise DataError('이 기간에는 선택한 계좌의 기록이 없습니다')
                if selected!='전체' and 'strategy_version' in effective:
                    timeline=effective.loc[effective.strategy.eq(selected)].groupby('date').strategy_version.first().astype(str).sort_index()
                    periods={}
                    for _,series in timeline.groupby(timeline.ne(timeline.shift()).cumsum()):
                        periods[f'{series.iloc[0]} · {series.index[0]} ~ {series.index[-1]}']=set(series.index)
                    version=st.selectbox('전략 버전 기간',['전체 버전']+list(periods))
                    if version!='전체 버전':effective=effective[effective.strategy.eq(selected)&effective.date.isin(periods[version])]
                if selected=='전체' and effective.groupby('date').strategy.apply(lambda s:tuple(sorted(set(s)))).nunique()>1:
                    st.warning('날짜별 기록 계좌 구성이 달라 전체 성과를 계산하지 않습니다. 누락 계좌를 기록하세요.')
                else:
                    eq,metrics=summarize(effective,st.session_state.cashflows,None if selected=='전체' else selected)
                    fmt=lambda v:'—' if v is None else f'{v:.2%}'
                    a,b,c,d=st.columns(4)
                    a.metric('기간 수익률 · Dietz 근사',fmt(metrics['total_return']))
                    b.metric('연환산 · 근사',fmt(metrics['cagr']))
                    c.metric('MDD · 관측일 기준',fmt(metrics['mdd']))
                    d.metric('XIRR',fmt(metrics['xirr']))
                    st.caption('불규칙한 평가일 사이의 입출금을 날짜 가중한 Modified Dietz 근사입니다. 배당·비용은 별도로 추적하지 않습니다.')
                    st.plotly_chart(px.line(eq,x='date',y='index',markers=True,labels={'index':'시작 100','date':'평가일'}),use_container_width=True)
                    show_frame(eq,hide_index=True,use_container_width=True)
                    risk=monthly_risk(eq)
                    with st.expander('월간 위험 지표·벤치마크'):
                        a,b,c=st.columns(3)
                        a.metric('연 변동성',fmt(risk['volatility']))
                        b.metric('Sharpe','—' if risk['sharpe'] is None else f"{risk['sharpe']:.2f}")
                        c.metric('Sortino','—' if risk['sortino'] is None else f"{risk['sortino']:.2f}")
                        st.caption('입출금 보정 수익률 기준, 연 12회·위험무이자율 0%. 같은 일자 또는 월말의 연속 월간 수익률이 12개 이상일 때만 표시합니다.')
                        benchmark=st.text_input('비교 ETF 티커',value='SPY').strip().upper()
                        if st.button('동일 평가일·원화 기준 벤치마크 조회'):
                            try:
                                compare=eq[['date','index']].merge(benchmark_index(benchmark,eq.date,prices),on='date')
                                st.plotly_chart(px.line(compare,x='date',y=['index','benchmark']),use_container_width=True)
                                st.caption('벤치마크는 원화 환산 비수정 종가·배당 제외입니다. 계좌 안에 남은 분배금은 포트폴리오 잔고에 포함될 수 있어 총수익률과 차이가 있습니다.')
                            except (DataError,ValueError) as e:st.error(str(e))
                st.subheader('분류별 기록')
                cat_history=effective if selected=='전체' else effective[effective.strategy.eq(selected)]
                cats=classification_view(cat_history.rename(columns={'value':'평가액'})).groupby(['date','category'],as_index=False)['평가액'].sum().rename(columns={'평가액':'value'})
                st.plotly_chart(px.area(cats,x='date',y='value',color='category'),use_container_width=True)
                with st.expander('원본 기록·개정'):show_frame(history,hide_index=True,use_container_width=True)
                st.subheader('실제 체결 이력');show_frame(st.session_state.actions,hide_index=True,use_container_width=True)
            except DataError as e:st.error(str(e))
    with tabs[2]:
        st.caption('입금은 양수, 출금은 음수. 계좌 간 이체는 transfer와 같은 transfer_id로 양쪽 계좌를 기록합니다. 이 표는 잔고를 자동 변경하지 않습니다.')
        with st.form('flows_form'):
            edited=edit_frame(st.session_state.cashflows,num_rows='dynamic',hide_index=True,use_container_width=True)
            if st.form_submit_button('입출금 검증·적용'):
                try:install({'cashflows':validate_flows(edited)},invalidate=False);st.success('입출금 기록을 적용했습니다.')
                except DataError as e:st.error(str(e))

elif page=='설정':
    tab1,tab2,tab3=st.tabs(['Sheets·파일 입력','백업·복원','수동 가격'])
    with tab1:
        if remote_enabled:
            st.subheader('Apps Script 양방향 원장')
            st.caption('세션 시작 시 한 번 읽고, 사이드바의 저장 버튼으로 원장을 저장·재조회합니다. Sheets 직접 수정이나 다른 세션 저장이 있으면 충돌을 알립니다.')
            st.caption('Google Cloud 콘솔·서비스계정 설정은 필요하지 않습니다. Apps Script 자체는 Google 관리형 Cloud 프로젝트를 사용합니다.')
            if st.button('최신 원장 미리보기'):
                try:
                    loaded,token=load_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'])
                    st.session_state.remote_preview=(loaded,token)
                except DataError as e:st.error(str(e))
            if st.session_state.get('remote_preview'):
                loaded,token=st.session_state.remote_preview
                show_frame(pd.DataFrame([{'표':k,'현재 행':len(st.session_state[k]),'시트 행':len(v)} for k,v in loaded.items()]),hide_index=True)
                st.caption('최신 원장 적용은 현재 세션 자료를 교체합니다. 저장하지 않은 작업은 전체 백업으로 보존하세요.')
                if st.button('검토한 최신 원장 적용'):
                    install(loaded);st.session_state.remote_token=token
                    st.session_state.demo=False;st.session_state.dirty=False
                    st.session_state.pop('remote_preview',None)
                    st.success('최신 원장을 적용했습니다.')
            st.divider()
        else:
            st.info('Apps Script 저장을 사용하려면 배포 안내에 따라 SHEETS_WEBAPP_URL · SHEETS_SECRET · APP_PASSWORD를 Streamlit Secrets에 설정하세요.')
        st.subheader('Google Sheets 읽기')
        st.caption('공개 링크 읽기는 별도 입력 경로입니다. 링크가 있는 모든 사용자: 뷰어로 공유한 문서만 읽습니다. Apps Script 연결 문서는 공개 공유할 필요가 없습니다.')
        url=st.text_input('스프레드시트 URL')
        st.caption('Holdings, Strategies, Snapshots, Actions, Cashflows, CategoryTargets 여섯 기본 탭을 준비하세요. 기록이 없는 탭에도 헤더가 필요합니다.')
        audit=st.checkbox('Evaluations · StrategyVersions도 함께 읽기',value=True,help='확정 주문안과 당시 규칙을 다시 열기 위한 두 탭입니다. 기존 여섯 탭 문서를 사용할 때는 해제하세요.')
        if st.button('시트 읽기·미리보기'):
            try:
                imported=read_workbook(url,include_audit=audit)
                imported['holdings']=normalize_holdings(imported['holdings'])
                imported['strategies']=normalize_strategies(imported['strategies'])
                latest_snapshots(imported['snapshots'])
                validate_flows(imported['cashflows'])
                validate_actions(imported['actions'])
                imported['category_targets']=normalize_category_targets(imported['category_targets'])
                st.session_state.sheet_preview=imported
            except DataError as e:st.error(str(e))
        preview=st.session_state.get('sheet_preview')
        if preview:
            show_frame(pd.DataFrame([{'탭':k,'기존 행':len(st.session_state[k]),'가져올 행':len(v)} for k,v in preview.items()]),hide_index=True)
            show_frame(preview['holdings'],hide_index=True,use_container_width=True)
            st.caption('적용하면 읽어온 탭의 세션 데이터를 바꿉니다. 먼저 전체 백업을 내려받으세요.')
            if st.button('검토한 시트 데이터 적용'):
                matched=snapshots_match(st.session_state.snapshots,preview['snapshots'])
                install(preview)
                st.session_state.demo=False
                st.session_state.sheet_verified='평가 기록의 ID·수량·가격·환율·평가액이 Sheets와 일치합니다.' if matched else '시트를 불러왔습니다. 기존 평가 기록과 일치를 확인하지 못했습니다.'
                del st.session_state.sheet_preview
                st.success(st.session_state.sheet_verified)
        st.divider();st.subheader('CSV·TSV·표 붙여넣기')
        kind=st.selectbox('가져올 데이터',TABLES)
        file=st.file_uploader('표 파일',type=['csv','tsv'])
        pasted=st.text_area('표 붙여넣기',height=130)
        if file or pasted:
            try:
                frame=parse_table(file.getvalue() if file else pasted)
                required=HOLDING_COLUMNS if kind=='holdings' else ['code','rule','params_json'] if kind=='strategies' else []
                missing=[col for col in required if col not in frame.columns]
                if missing:
                    with st.expander('필수 열 이름 연결',expanded=True):
                        mapping={col:st.selectbox(col+'에 사용할 원본 열',['']+list(frame.columns),key='column_map_'+kind+'_'+col) for col in missing}
                    frame=map_columns(frame,mapping)
                show_frame(frame.head(10),hide_index=True)
                if st.button('검토한 표 적용'):
                    if kind=='holdings':frame=normalize_holdings(frame)
                    elif kind=='strategies':frame=normalize_strategies(frame)
                    elif kind=='snapshots':latest_snapshots(frame)
                    elif kind=='cashflows':frame=validate_flows(frame)
                    elif kind=='actions':frame=validate_actions(frame)
                    elif kind=='category_targets':frame=normalize_category_targets(frame)
                    install({kind:frame})
                    if kind=='holdings':st.session_state.demo=False
                    st.success('표를 적용했습니다.')
            except (DataError,ValueError) as e:st.error(str(e))
    with tab2:
        st.caption('이 앱의 세션은 영구 저장소가 아닙니다. 종료 전 Sheets에 저장하거나 전체 백업을 내려받으세요.')
        st.download_button('전체 백업 JSON 다운로드',backup_bytes(workspace(),working_draft()),'rebalance-backup.json','application/json')
        file=st.file_uploader('전체 백업 복원',type=['json'])
        if file:
            try:
                restored,drafts=restore_backup(file.getvalue(),include_drafts=True)
                show_frame(pd.DataFrame([{'데이터':k,'행':len(v)} for k,v in restored.items()]),hide_index=True)
                if st.button('검증한 백업으로 복원'):
                    install(restored)
                    st.session_state.overrides={};st.session_state.demo=False
                    for key in ['run','fills','fills_run_id','overrides','demo','post_execution','holding_drafts']:
                        if key in drafts:st.session_state[key]=drafts[key]
                    st.success('기록과 작업 중인 평가·주문안을 복원했습니다.')
            except DataError as e:st.error(str(e))
    with tab3:
        st.caption('자동 조회 실패 시 실제 종가만 보완합니다. 신호 시계열 부족은 별도로 차단합니다.')
        with st.form('manual_price'):
            code=st.selectbox('전략',st.session_state.strategies.code.tolist())
            ticker=st.text_input('수동 입력 티커').upper().strip()
            observed=st.date_input('실제 가격일',as_of,max_value=as_of)
            close_text=st.text_input('실제 종가',value='0',help='예: 12,345')
            source=st.text_input('가격 출처')
            reason=st.text_input('수동 입력 사유')
            if st.form_submit_button('수동 가격 등록'):
                try:
                    close=float(close_text.replace(',','').strip())
                except ValueError:
                    close=0.
                if ticker and ticker!='CASH' and math.isfinite(close) and close>0 and source and reason:
                    st.session_state.overrides[f'{code}:{ticker}']={'date':str(observed),'close':close,'source':source,'reason':reason}
                    st.session_state.pop('run',None);st.success('등록했습니다. 종가 조회를 다시 실행하세요.')
                else:st.error('CASH 외 종목, 양수 가격, 출처와 사유가 필요합니다.')
        if st.session_state.overrides:
            st.json(st.session_state.overrides)
            if st.button('수동 가격 해제'):
                st.session_state.overrides={};st.session_state.pop('run',None);st.rerun()

st.divider()
st.caption('수동 주문 전용 · Google Sheets 원장 · 선택한 기준일의 실제 종가 · 연간 연구는 후속 개발')
