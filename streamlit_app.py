"""Personal allocation desk — explicit evaluation, manual orders, portable records."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json
import hashlib
import hmac
import pandas as pd
import plotly.express as px
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

st.set_page_config(page_title='Rebalance · 자산배분', page_icon='◈', layout='wide')
st.markdown('''<style>
:root{
  font-size:16px;color-scheme:light;
  --warm-bg:#f7f3ee;--warm-surface:#fffcf8;--warm-ink:#2e312f;
  --warm-muted:#77736d;--warm-border:#e7ded5;
  --terracotta:#c86b45;--terracotta-dark:#8b4d32;--terracotta-soft:#f6e4db;
  --sage:#587064;--deep-green:#24312b;
}
html,body,[class*="st-"]{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;line-height:1.55}
[data-testid="stAppViewContainer"]{background:var(--warm-bg);color:var(--warm-ink)}
[data-testid="stHeader"]{background:color-mix(in srgb,var(--warm-bg) 88%,transparent)}
.block-container{max-width:1360px;padding:2.5rem 2rem 4rem}
h1{font-size:clamp(2rem,3vw,2.55rem)!important;line-height:1.2!important;letter-spacing:-.035em!important;margin-bottom:.45rem!important}
h2{font-size:1.5rem!important;line-height:1.35!important;letter-spacing:-.025em!important;margin-top:1.8rem!important}
h3{font-size:1.2rem!important;line-height:1.4!important;letter-spacing:-.015em!important}
p,li{font-size:1rem;line-height:1.6}
[data-testid="stCaptionContainer"] p{font-size:.9rem!important;line-height:1.55!important;color:var(--warm-muted)!important}
[data-testid="stWidgetLabel"] p{font-size:.95rem!important;font-weight:650!important;line-height:1.45!important}
[data-testid="stMetricValue"]{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1.72rem!important;line-height:1.25!important}
[data-testid="stMetricLabel"] p{font-size:.9rem!important;font-weight:650!important}
[data-testid="stMetric"]{padding:1rem 1.05rem;border:1px solid var(--warm-border);border-radius:14px;background:var(--warm-surface)}
[data-testid="stSidebar"]{border-right:1px solid #3a4b43;background:var(--deep-green);color:#f9f5ef}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,[data-testid="stSidebar"] label{color:#f9f5ef!important}
[data-testid="stSidebar"] [role="radiogroup"] label{min-height:42px;padding:.3rem .45rem;border-radius:8px}
[data-testid="stSidebar"] [role="radiogroup"] p{font-size:.96rem!important;font-weight:600!important}
.stButton>button,.stDownloadButton>button,[data-testid="stFormSubmitButton"]>button{min-height:44px;border-radius:10px;border-color:color-mix(in srgb,var(--terracotta) 55%,var(--warm-border));font-size:.96rem!important;font-weight:650!important;padding:.55rem 1rem!important}
[data-baseweb="input"] input,[data-baseweb="select"] *{font-size:.96rem!important}
[data-baseweb="tab-list"] button{min-height:44px;padding:.65rem .9rem!important}
[data-baseweb="tab-list"] button p{font-size:.96rem!important;font-weight:650!important}
[data-testid="stExpander"] summary p{font-size:1rem!important;font-weight:650!important}
[data-testid="stAlert"] p{font-size:.95rem!important;line-height:1.55!important}
.eyebrow{font-size:.78rem;line-height:1.4;letter-spacing:.14em;color:var(--terracotta);font-weight:750;margin-bottom:.45rem}
.page-description{font-size:1rem;line-height:1.6;color:var(--warm-muted);margin:0 0 1.5rem}
.workflow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.65rem;margin:.25rem 0 1.5rem}
.workflow-step{display:flex;align-items:center;gap:.65rem;min-height:54px;padding:.7rem .8rem;border:1px solid var(--warm-border);border-radius:14px;background:var(--warm-surface);box-shadow:0 4px 18px rgba(55,45,35,.035)}
.workflow-step:first-child{border-color:#d99b7b;background:var(--terracotta-soft)}
.workflow-index{display:grid;place-items:center;flex:0 0 26px;height:26px;border-radius:999px;background:var(--terracotta);color:#fff;font-size:.78rem;font-weight:800}
.workflow-label{font-size:.9rem;font-weight:680;line-height:1.35;word-break:keep-all}
@media(max-width:800px){
  .block-container{padding:1.25rem 1rem 4.5rem}
  h1{font-size:2rem!important}
  h2{font-size:1.35rem!important}
  [data-testid="stMetric"]{padding:.85rem .9rem}
  [data-testid="stMetricValue"]{font-size:1.42rem!important}
  [data-baseweb="tab-list"]{overflow-x:auto;flex-wrap:nowrap;scrollbar-width:none}
  .workflow{display:flex;overflow-x:auto;gap:.55rem;margin-right:-1rem;padding-right:1rem;padding-bottom:.35rem;scroll-snap-type:x mandatory;scrollbar-width:none}
  .workflow::-webkit-scrollbar,[data-baseweb="tab-list"]::-webkit-scrollbar{display:none}
  .workflow-step{flex:0 0 8.5rem;min-height:78px;align-items:flex-start;flex-direction:column;gap:.35rem;scroll-snap-align:start}
}
@media(max-width:460px){
  .page-description{font-size:.94rem;margin-bottom:1.15rem}
  [data-testid="stHorizontalBlock"]{gap:.7rem}
  .stButton>button,.stDownloadButton>button,[data-testid="stFormSubmitButton"]>button{width:100%}
}
</style>''',unsafe_allow_html=True)

PAGE_DESCRIPTIONS={
    '이번 달':'보유내역과 실제 종가를 확인하고 이번 평가의 주문안을 준비합니다.',
    '자산 현황':'전략·역할·자산 분류별 평가액과 목표 비중의 차이를 살펴봅니다.',
    '주문안':'다음 거래일에 직접 입력할 수량과 예상 잔여현금을 검토합니다.',
    '전략실':'조건, 실행 주기와 판정별 동작을 한 화면에서 설계하고 검증합니다.',
    '기록':'평가와 체결 내역을 확정하고 기간별 성과를 확인합니다.',
    '설정':'Google Sheets 연결, 백업·복원과 수동 가격을 관리합니다.',
}


def workflow_steps(labels):
    items=''.join(f'<div class="workflow-step"><span class="workflow-index">{i}</span><span class="workflow-label">{label}</span></div>' for i,label in enumerate(labels,1))
    st.markdown(f'<div class="workflow" aria-label="운영 단계">{items}</div>',unsafe_allow_html=True)

@st.cache_data(ttl=900,show_spinner=False)
def prices(ticker,market,day,adjusted=False):
    return engine._series(ticker,market,day,adjusted)


def workspace():
    return {k:st.session_state[k] for k in TABLES}


def working_draft():
    keys=['run','fills','fills_run_id','overrides','demo','post_execution']
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


def run_ready():
    if 'run' not in st.session_state:
        st.info('보유내역을 확인한 뒤 ‘이번 달’에서 지정일 종가를 조회하세요.')
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

with st.sidebar:
    st.markdown('### ◈ REBALANCE')
    st.caption('개인 자산배분 운영')
    page=st.radio('작업 공간',['이번 달','자산 현황','주문안','전략실','기록','설정'],label_visibility='collapsed')
    st.divider()
    today=datetime.now(ZoneInfo('Asia/Seoul')).date()
    as_of=st.date_input('평가 기준일',today,max_value=today,help='월말에 한정하지 않습니다. 분기 규칙은 선택한 달이 3·6·9·12월인지 확인합니다.')
    st.caption('CASH = 원화 잔액 · 가격 1\n\n매도대금 재사용·거래 비용 계산 없음')
    if st.session_state.demo:
        st.warning('DEMO · 예시 보유내역')
    if st.session_state.get('dirty'):
        st.caption('저장할 변경사항 있음')
    if remote_enabled:
        if st.button('Sheets에 저장',type='primary',disabled=st.session_state.demo,use_container_width=True):
            try:
                with st.spinner('원장을 저장하고 다시 확인합니다…'):
                    st.session_state.remote_token=save_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'],workspace(),st.session_state.remote_token)
                st.session_state.dirty=False
                st.session_state.sync_message='Sheets 저장·재조회 확인 완료'
            except DataError as e:st.error(str(e))
        if st.session_state.get('sync_message') and not st.session_state.get('dirty'):
            st.success(st.session_state.sync_message)
    else:st.caption('Sheets 수동 기록 모드')
    st.download_button('전체 작업 백업',backup_bytes(workspace(),working_draft()),'rebalance-backup.json','application/json',use_container_width=True)

st.markdown('<div class="eyebrow">ALLOCATION WORKSPACE</div>',unsafe_allow_html=True)
st.title(page)
st.markdown(f'<p class="page-description">{PAGE_DESCRIPTIONS[page]}</p>',unsafe_allow_html=True)
if 'run' in st.session_state and st.session_state.run['date']!=str(as_of):
    st.warning(f"현재 평가 결과는 {st.session_state.run['date']} 기준입니다. 새 기준일로 다시 조회하세요.")

if page=='이번 달':
    workflow_steps(['보유내역 확인','종가 확정','규칙 판정','주문안 검토','기록'])
    with st.expander('1 · 보유수량과 현금 확인',expanded='run' not in st.session_state):
        with st.form('holdings_form'):
            edited=st.data_editor(st.session_state.holdings,num_rows='dynamic',hide_index=True,use_container_width=True,
                column_config={'shares':st.column_config.NumberColumn('보유수량 / CASH 원화 잔액',min_value=0.),
                               'ticker':st.column_config.TextColumn('티커'),'target_pct':st.column_config.NumberColumn('기본 목표 (%)',min_value=0.,max_value=100.)})
            if st.form_submit_button('보유내역 확인·적용'):
                try:
                    install({'holdings':normalize_holdings(edited)})
                    st.session_state.demo=False
                    st.success('입력 검증 완료. 지정일 종가를 조회하세요.')
                except DataError as e:
                    st.error(str(e))
    manual_candidates=[]
    for _,strategy_row in st.session_state.strategies.iterrows():
        try:
            strategy_params=json.loads(strategy_row.params_json or '{}')
            cadence=strategy_params.get('scope',{}).get('run',strategy_params.get('frequency','monthly'))
            if cadence=='manual':manual_candidates.append(str(strategy_row.code))
        except (TypeError,ValueError):pass
    manual_codes=st.multiselect('이번 평가에서 수동 실행할 전략',manual_candidates,help='선택하지 않은 수동 전략은 자산만 평가하고 주문을 만들지 않습니다.') if manual_candidates else []
    if st.button('2 · 지정일 종가 조회·판정',type='primary',use_container_width=True):
        prices.clear()
        try:
            with st.spinner('실제 종가와 전략별 신호를 확인하는 중입니다…'):
                run=run_evaluation(st.session_state.holdings,st.session_state.strategies,as_of,fetch=prices,overrides=st.session_state.overrides,manual_codes=manual_codes)
            st.session_state.run=run
            st.session_state.pop('post_execution',None)
            if st.session_state.get('fills_run_id')!=run['id']:
                st.session_state.fills=execution_draft(run)
                st.session_state.fills_run_id=run['id']
        except (DataError,ValueError) as e:
            st.error(str(e))
    run=st.session_state.get('run')
    if run:
        view,plan=run['view'],run['plan']
        for code,message in run['errors'].items():
            st.error(f'{code} · 확정 차단: {message}')
        if not view.empty:
            a,b,c,d=st.columns(4)
            a.metric('평가 가능 자산' if run['errors'] else '총자산',format_won(view['평가액'].sum()))
            b.metric('실제 CASH',format_won(view.loc[view.ticker.eq('CASH'),'평가액'].sum()))
            c.metric('주문 대상',f"{int(plan['제안수량'].ne(0).sum())}종목")
            d.metric('확인 필요',f"{len(run['errors'])}계좌")
            st.caption(f"요청일 {run['date']} · 실제 가격일 {', '.join(sorted(view.price_date.astype(str).unique()))}")
            st.subheader('3 · 계좌별 판정')
            for decision in run['decisions']:
                code=decision['strategy'];sub=view[view.strategy.eq(code)]
                with st.container(border=True):
                    c1,c2=st.columns([3,1])
                    c1.markdown(f"**{code} · {sub.account.iloc[0]}**")
                    c1.caption(f"{decision['status']} · {decision['message']}")
                    c2.markdown(f"**{format_won(sub['평가액'].sum())}**")
                    if decision.get('evidence'):
                        with st.expander('판정 근거'):
                            st.dataframe(pd.DataFrame(decision['evidence']),hide_index=True,use_container_width=True)
            st.info('다음: 주문안에서 수량과 기존 현금을 검토한 뒤 기록 화면에서 평가를 확정하세요.')
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
        st.dataframe(grouped,hide_index=True,use_container_width=True)
        if col=='category':
            with st.expander('전체 분류 목표 편집'):
                with st.form('category_targets_form'):
                    target_edit=st.data_editor(st.session_state.category_targets,num_rows='dynamic',hide_index=True)
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
        st.dataframe(detail[['strategy','ticker','name','shares','close','currency','fx','평가액','현재비중','target_pct','실행목표(%)','실행후비중(%)','price_date','price_source']],hide_index=True,use_container_width=True)

elif page=='주문안':
    run=run_ready()
    if run and not run['plan'].empty:
        st.caption('실제 종가로 산정한 수동 주문안입니다. 비용·세금은 계산하지 않으며 매수는 기존 CASH 잔액으로 제한합니다.')
        plan=run['plan']
        st.dataframe(plan[['전략','티커','구분','기준종가','보유수량','기본목표(%)','실행목표(%)','목표조정액','제안수량','예상매매액','실행후비중(%)','예상잔여현금','주문예정일','근거']],hide_index=True,use_container_width=True)
        with st.expander('제안 수량 수정'):
            with st.form('revise_order_'+run['id']):
                edited_order=st.data_editor(plan[['주문ID','전략','티커','제안수량']],disabled=['주문ID','전략','티커'],hide_index=True,use_container_width=True)
                edit_reason=st.text_input('주문안 수정 사유')
                if st.form_submit_button('수량·현금 검증 후 주문안 수정'):
                    try:
                        revised=revise_proposal(run,edited_order,edit_reason)
                        st.session_state.run=revised
                        st.session_state.fills=execution_draft(revised)
                        st.session_state.fills_run_id=revised['id']
                        st.rerun()
                    except (DataError,ValueError) as e:st.error(str(e))
        st.download_button('주문안 CSV 다운로드',to_csv_bytes(plan),'manual-orders.csv','text/csv')
        if plan['현금제약'].any():
            st.warning('일부 매수 수량이 CASH 한도에 따라 축소되었습니다. 매도대금은 같은 주문안에서 재사용하지 않습니다.')
        st.divider();st.subheader('실제 체결 반영')
        status=order_status(run,st.session_state.actions)
        if not status.empty:
            st.dataframe(status.drop(columns='주문ID'),hide_index=True,use_container_width=True)
            with st.expander('미실행·부분 체결 주문 취소 기록'):
                choices=status[status['상태'].isin(['미실행','부분 체결'])]
                cancel_ids=st.multiselect('남은 주문을 취소한 종목',choices['주문ID'].tolist(),format_func=lambda v:choices.set_index('주문ID').loc[v,'티커'])
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
            show=['실행','전략','티커','구분','제안수량','체결ID','체결일','실제수량','실제단가','실제환율','실제체결금액','메모']
            edited=st.data_editor(fills[show],hide_index=True,use_container_width=True,disabled=[c for c in show if c not in editable],key='fill_editor_'+run['id'])
            saved=fills.copy()
            for c in editable:saved[c]=edited[c]
            st.session_state.fills=saved
            if st.button('검증한 실제 체결만 반영',type='primary'):
                try:
                    if workspace()['evaluations'].empty or run['id'] not in set(workspace()['evaluations'].run_id):
                        raise DataError('먼저 기록 화면에서 체결 전 평가를 확정하세요')
                    install(apply_executions(workspace(),saved,run),invalidate=False)
                    st.success('실제 체결을 반영했습니다. 기록은 유지되며 변경된 Holdings·Actions를 시트에 저장해야 합니다.')
                    st.session_state.post_execution=True
                except (DataError,ValueError) as e:st.error(str(e))
        else:st.info('현재 제안된 거래가 없습니다.')
        if st.session_state.get('post_execution'):
            st.info('이 주문안은 체결 전 평가의 기록입니다. 다시 계산하려면 이번 달 화면에서 종가를 새로 조회하세요.')

elif page=='전략실':
    st.caption('현재 운용 규칙을 편집합니다. 연간 전략 연구와 AI 보조는 이번 범위에 포함되지 않습니다.')
    st.subheader('전략별 운영 설정')
    with st.form('strategy_settings'):
        edited=st.data_editor(st.session_state.strategies,hide_index=True,num_rows='dynamic',use_container_width=True,
            column_config={'tolerance_pct':st.column_config.NumberColumn('허용 괴리 (%p)',min_value=0.,max_value=100.),
                           'cash_reserve':st.column_config.NumberColumn('현금 유보액 (원)',min_value=0.),
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
    run=st.session_state.get('run')
    if run and not run['view'].empty:
        def studio_prices(t,m,d):
            code=st.session_state.get('studio_code',st.session_state.strategies.code.iloc[0])
            row=st.session_state.strategies[st.session_state.strategies.code.eq(code)].iloc[0]
            key=f'studio_{code}_{row.get("version","1")}'
            adjusted=st.session_state.get(key,{}).get('signal_adjusted',False)
            from streamlit_app.market import validate_series
            return validate_series(prices(t,engine.resolved_market(t,m),d,adjusted),d,engine.resolved_market(t,m))
        studio.render(st.session_state.strategies,st.session_state.holdings,run['view'],as_of,studio_prices)
    else:st.info('종가 조회 후 규칙 편집과 실제 신호 미리보기가 열립니다. JSON 파라미터는 위 표에서도 편집할 수 있습니다.')

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
            selected_run=st.selectbox('확정 주문안 다시 열기',saved_runs.run_id.drop_duplicates().tolist())
            if st.button('확정한 평가·주문안 불러오기'):
                try:
                    st.session_state.run=load_frozen_run(saved_runs,selected_run)
                    st.session_state.fills=execution_draft(st.session_state.run)
                    st.session_state.fills_run_id=selected_run
                    st.success('원래 평가일의 주문안을 불러왔습니다. 주문안 화면에서 실제 체결을 기록하세요.')
                except DataError as e:st.error(str(e))
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
                    st.dataframe(eq,hide_index=True,use_container_width=True)
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
                with st.expander('원본 기록·개정'):st.dataframe(history,hide_index=True,use_container_width=True)
                st.subheader('실제 체결 이력');st.dataframe(st.session_state.actions,hide_index=True,use_container_width=True)
            except DataError as e:st.error(str(e))
    with tabs[2]:
        st.caption('입금은 양수, 출금은 음수. 계좌 간 이체는 transfer와 같은 transfer_id로 양쪽 계좌를 기록합니다. 이 표는 잔고를 자동 변경하지 않습니다.')
        with st.form('flows_form'):
            edited=st.data_editor(st.session_state.cashflows,num_rows='dynamic',hide_index=True,use_container_width=True)
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
                st.dataframe(pd.DataFrame([{'표':k,'현재 행':len(st.session_state[k]),'시트 행':len(v)} for k,v in loaded.items()]),hide_index=True)
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
            st.dataframe(pd.DataFrame([{'탭':k,'기존 행':len(st.session_state[k]),'가져올 행':len(v)} for k,v in preview.items()]),hide_index=True)
            st.dataframe(preview['holdings'],hide_index=True,use_container_width=True)
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
                st.dataframe(frame.head(10),hide_index=True)
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
                st.dataframe(pd.DataFrame([{'데이터':k,'행':len(v)} for k,v in restored.items()]),hide_index=True)
                if st.button('검증한 백업으로 복원'):
                    install(restored)
                    st.session_state.overrides={};st.session_state.demo=False
                    for key in ['run','fills','fills_run_id','overrides','demo','post_execution']:
                        if key in drafts:st.session_state[key]=drafts[key]
                    st.success('기록과 작업 중인 평가·주문안을 복원했습니다.')
            except DataError as e:st.error(str(e))
    with tab3:
        st.caption('자동 조회 실패 시 실제 종가만 보완합니다. 신호 시계열 부족은 별도로 차단합니다.')
        with st.form('manual_price'):
            code=st.selectbox('전략',st.session_state.strategies.code.tolist())
            ticker=st.text_input('수동 입력 티커').upper().strip()
            observed=st.date_input('실제 가격일',as_of,max_value=as_of)
            close=st.number_input('실제 종가',min_value=0.,value=0.)
            source=st.text_input('가격 출처')
            reason=st.text_input('수동 입력 사유')
            if st.form_submit_button('수동 가격 등록'):
                if ticker and ticker!='CASH' and close>0 and source and reason:
                    st.session_state.overrides[f'{code}:{ticker}']={'date':str(observed),'close':close,'source':source,'reason':reason}
                    st.session_state.pop('run',None);st.success('등록했습니다. 종가 조회를 다시 실행하세요.')
                else:st.error('CASH 외 종목, 양수 가격, 출처와 사유가 필요합니다.')
        if st.session_state.overrides:
            st.json(st.session_state.overrides)
            if st.button('수동 가격 해제'):
                st.session_state.overrides={};st.session_state.pop('run',None);st.rerun()

st.divider()
st.caption('수동 주문 전용 · Google Sheets 원장 · 선택한 기준일의 실제 종가 · 연간 연구는 후속 개발')
