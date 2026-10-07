"""Streamlit strategy studio; the preview and order plan use the same engine."""
import copy
import json
import math
from html import escape
import pandas as pd
import streamlit as st
from streamlit_app.rules import ACTIONS, OPERATORS, FREQUENCIES, evaluate
from streamlit_app.ui import numeric_column_config, prefer_asset_names


def new_spec():
    return {'schema_version':2, 'scope':{'market':'MIX','run':'monthly'},
            'conditions':[{'ticker':'QQQ','op':'sma_above','months':10,'connector':'AND'}],
            'onPass':{'action':'hold_buy','params':{}}, 'onFail':{'action':'hold_buy','params':{}}}


def new_rule(name='규칙 1'):
    return {'name':name, 'scope':[],
            'conditions':[{'ticker':'QQQ','op':'sma_above','months':10,'connector':'AND'}],
            'then':{'action':'hold_buy','params':{}}, 'else':{'action':'hold_buy','params':{}}}


def new_multi_spec():
    return {'schema_version':4, 'scope':{'market':'MIX','run':'monthly'}, 'rules':[new_rule()]}


def select(label, choices, value, key, labels=None):
    return st.selectbox(label, choices, index=choices.index(value) if value in choices else 0,
                        key=key, format_func=(lambda choice: labels.get(choice,str(choice))) if labels else str)


def condition_sentence(condition, names):
    """Describe one condition using the same fields consumed by the rule engine."""
    op=condition.get('op')
    ticker=str(condition.get('ticker') or '')
    asset=escape('조건에서 선정된 자산' if ticker=='__winner__' else names.get(ticker,ticker or '미선택'))
    signal=f'<span class="signal">{asset}</span>'
    number=lambda value:f'<span class="number">{escape(str(value))}</span>'
    if op in ('sma_above','sma_below'):
        return f'{signal} 종가가 {number(condition.get("months",10))}개월 SMA를 {"상회" if op.endswith("above") else "하회"}'
    if op in ('ema_above','ema_below'):
        return f'{signal} 종가가 {number(condition.get("days",200))}일 EMA를 {"상회" if op.endswith("above") else "하회"}'
    if op in ('dd_below','dd_above'):
        return f'{signal} 최근 {number(condition.get("lookback",120))}거래일 낙폭이 {number(condition.get("pct",-10))}% {"이하" if op.endswith("below") else "이상"}'
    if op == 'mom_rank':
        tickers=condition.get('tickers',[])
        if isinstance(tickers,str):tickers=[t.strip() for t in tickers.split(',') if t.strip()]
        candidates=', '.join(escape(names.get(t,t)) for t in tickers) or '미선택'
        return f'[{candidates}] 중 {number(condition.get("months",12))}개월 모멘텀 상위 {number(condition.get("rank",1))}위'
    if op in ('price_above_abs','price_below_abs'):
        return f'{signal} 종가가 {number(condition.get("price",0))} {"이상" if op=="price_above_abs" else "이하"}'
    if op == 'ticker_gt':
        other=str(condition.get('tickerB') or '')
        return f'{signal} 가격이 <span class="signal">{escape(names.get(other,other or "미선택"))}</span> 가격의 {number(condition.get("pct",100))}% 이상'
    if op == 'schedule':
        cadence=condition.get('frequency','monthly')
        return f'{escape(FREQUENCIES.get(cadence,cadence))} 일정 도래'
    if op == 'weight_deviation':
        return f'{signal} 목표 비중과의 차이가 {number(condition.get("pct",2))}%p 이상'
    if op == 'momentum_above':
        return f'{signal} {number(condition.get("months",12))}개월 수익률이 {number(condition.get("pct",0))}% 이상'
    if op == 'external_above':
        return f'수동 지표가 기준값 {number(condition.get("threshold",0))} 이상'
    return escape(OPERATORS.get(op,'조건을 선택하세요'))


def action_sentence(branch, names):
    action=branch.get('action','hold_buy')
    params=branch.get('params') or {}
    ticker=str(params.get('ticker') or '')
    target=escape('조건에서 선정된 자산' if ticker=='__winner__' else names.get(ticker,ticker or '대상 미선택'))
    base=escape(ACTIONS.get(action,action))
    if action=='move_all':return f'{target}로 이동 · 현금 {escape(str(params.get("cashPct",0)))}% 유지'
    if action in ('set_weight','buy_to_weight'):
        return f'{target} 비중을 {escape(str(params.get("pct",50)))}%로 {"매수" if action=="buy_to_weight" else "설정"}'
    if action=='buy_cash_pct':return f'현금의 {escape(str(params.get("pct",50)))}%로 {target} 매수'
    if action=='switch_scope':return f'선택한 자산을 {target}로 전환'
    if action in ('restore','restore_scope'):
        frequency=params.get('restore_frequency','monthly')
        when=escape(FREQUENCIES.get(frequency,frequency))
        if action=='restore_scope':
            selected=params.get('role') or ', '.join(names.get(t,t) for t in params.get('tickers',[])) or '대상 미선택'
            return f'{escape(str(selected))} 목표 비중 복원 · {when}'
        return f'전체 목표 비중 복원 · {when}'
    if action=='notify':return f'앱에 메시지 표시: {escape(str(params.get("message") or "내용 미입력"))}'
    return base


def rule_preview_html(spec, names):
    conditions=spec.get('conditions') or []
    parts=[]
    for i,condition in enumerate(conditions):
        if i:parts.append(f'<span class="branch fail"> {escape(str(condition.get("connector") or "AND"))} </span>')
        parts.append(condition_sentence(condition,names))
    cadence=spec.get('scope',{}).get('run','monthly')
    return ('<div class="rule-preview"><div class="rule-preview-label">규칙 문장 미리보기</div>'
        f'<div><span class="branch">{escape(FREQUENCIES.get(cadence,cadence))} · IF</span> '
        f'{" ".join(parts) if parts else "조건을 추가하세요"}</div>'
        f'<div><span class="branch pass">충족하면</span> {action_sentence(spec.get("onPass",{}),names)}</div>'
        f'<div><span class="branch fail">미충족하면</span> {action_sentence(spec.get("onFail",{}),names)}</div></div>')


def edit_conditions(conditions, key, spec_key, assets, holdings, signal_labels, names, mode):
    """Render & edit one AND/OR-chained condition list ('카드' or '표' mode); returns the list.

    Shared by the single-condition editor and each independent rule's condition group
    in the multi-rule editor — identical fields and behavior either way.
    """
    if mode == '표':
        columns = ['connector','op','ticker','months','days','lookback','pct','price','tickerB','tickers','rank','frequency','value','threshold','source','observed_date','published_date','months_list']
        frame = pd.DataFrame(conditions).reindex(columns=columns)
        frame['tickers'] = frame['tickers'].map(lambda x: ','.join(x) if isinstance(x,list) else x)
        frame['months_list'] = frame['months_list'].map(lambda x: ','.join(map(str,x)) if isinstance(x,list) else x)
        frame = st.data_editor(frame, num_rows='dynamic', hide_index=True, use_container_width=True,
            key=key+'_table', column_config=numeric_column_config(frame.columns, {'op':st.column_config.SelectboxColumn(options=list(OPERATORS)),
            'connector':st.column_config.SelectboxColumn(options=['AND','OR']),
            'frequency':st.column_config.SelectboxColumn(options=list(FREQUENCIES))}))
        return [{k:v for k,v in r.items() if pd.notna(v) and v != ''} for r in frame.to_dict('records')]
    if not conditions:
        st.info('조건이 없습니다. 아래 ‘조건 추가’로 시작하세요.')
    for i, condition in enumerate(conditions):
        ck = f'{key}_c{i}'
        if i:
            with st.container(key=f'builder_connector_{key}_{i}'):
                condition['connector'] = st.radio('앞 조건과 연결', ['AND','OR'],
                    index=0 if condition.get('connector','AND')=='AND' else 1,
                    horizontal=True,key=ck+'_connect',
                    format_func=lambda value:'AND · 모두 충족' if value=='AND' else 'OR · 하나 이상 충족')
        with st.container(border=True,key=f'builder_condition_{key}_{i}'):
            st.markdown(f'<div class="builder-section">IF · 조건 {i+1:02d}</div>',unsafe_allow_html=True)
            previous_op=condition.get('op')
            condition['op'] = select('조건 종류', list(OPERATORS), previous_op, ck+'_op', OPERATORS)
            op = condition['op']
            if op!=previous_op and op=='mom_rank':
                condition['ticker']='__winner__'
            if op not in ('schedule','external_above','mom_rank'):
                current=str(condition.get('ticker') or '')
                options=list(dict.fromkeys([t for t in assets.ticker.astype(str) if t!='CASH']+
                    [t for t in holdings.ticker.astype(str) if t!='CASH']+
                    ([current] if current else [])+['__winner__','직접 입력']))
                chosen=select('신호 종목',options,current or '직접 입력',ck+'_ticker_choice',signal_labels)
                condition['ticker']=(st.text_input('직접 입력할 티커',value=current,
                    key=ck+'_ticker').strip().upper() if chosen=='직접 입력' else chosen)
            if op.startswith('sma') or op in ('mom_rank','momentum_above'):
                condition['months'] = st.number_input('기간(개월)', 1, 36, int(condition.get('months',10)), key=ck+'_months')
            if op.startswith('ema'):
                condition['days'] = st.number_input('EMA 기간(거래일)', 1,750,int(condition.get('days',200)),key=ck+'_days')
            if op.startswith('dd_'):
                condition['lookback'] = st.number_input('고점 조회 거래일', 1, 750, int(condition.get('lookback',120)), key=ck+'_lookback')
                condition['pct'] = st.number_input('낙폭 기준(%, 예: -10)', -100.0, 0.0, float(condition.get('pct',-10)), key=ck+'_dd')
            if op == 'mom_rank':
                rank_candidates = condition.get('tickers', [])
                if isinstance(rank_candidates,str):
                    rank_candidates=[t.strip() for t in rank_candidates.split(',') if t.strip()]
                ticker_options=list(dict.fromkeys([t for t in assets.ticker.astype(str) if t!='CASH']+
                    [t for t in holdings.ticker.astype(str) if t!='CASH']+rank_candidates))
                selected=st.multiselect('순위 후보',ticker_options,default=rank_candidates,
                    key=ck+'_candidates',format_func=lambda t:signal_labels.get(t,t))
                extra=st.text_input('후보 티커 추가 (쉼표 구분)',key=ck+'_candidate_extra',
                    help='보유하지 않은 QQQ, SPY 같은 신호 종목도 추가할 수 있습니다.')
                added=[t.strip().upper() for t in extra.split(',') if t.strip()]
                condition['tickers']=list(dict.fromkeys(selected+added))
                rank_targets=['__winner__']+list(dict.fromkeys(condition['tickers']+
                    ([condition['ticker']] if condition.get('ticker') not in ('','__winner__') else [])))
                condition['ticker']=select('순위 판정 대상',rank_targets,condition.get('ticker','__winner__'),
                    ck+'_rank_target',signal_labels)
                condition['rank'] = st.number_input('순위 이내', 1, 100, int(condition.get('rank',1)), key=ck+'_rank')
                st.caption('후보의 1위 자산을 다음 조건·행동에서 ‘조건에서 선정된 자산’으로 참조합니다.')
            if op.startswith('price_'):
                try:
                    initial_price=f'{float(condition.get("price",0)):,.0f}'
                except (TypeError,ValueError):
                    initial_price=str(condition.get('price',''))
                entered=st.text_input('기준 가격(현지통화)',value=initial_price,key=ck+'_price')
                try:
                    price=float(entered.replace(',','').strip())
                    if not math.isfinite(price):raise ValueError()
                    condition['price']=price
                except ValueError:
                    condition['price']=entered
                    st.error('기준 가격에는 숫자를 입력하세요.')
            if op == 'ticker_gt':
                condition['tickerB'] = st.text_input('비교 티커 B', condition.get('tickerB','SPY'), key=ck+'_other')
                condition['pct'] = st.number_input('B 가격 대비 비율(%)', 0.0, value=float(condition.get('pct',100)), key=ck+'_ratio')
                st.caption('현지통화의 가격 수준 비교입니다. 수익률 상대강도나 환율환산 비교가 아닙니다.')
            if op == 'weight_deviation':
                condition['pct'] = st.number_input('비중 괴리 (%p)',0.,100.,float(condition.get('pct',2)),key=ck+'_weight')
            if op == 'momentum_above':
                condition['pct'] = st.number_input('기간 수익률 기준 (%)',value=float(condition.get('pct',0)),key=ck+'_return')
            if op == 'external_above':
                condition['value'] = st.number_input('지표 관측값',value=float(condition.get('value',0)),key=ck+'_val')
                condition['threshold'] = st.number_input('지표 기준값',value=float(condition.get('threshold',0)),key=ck+'_threshold')
                for field,label in [('source','출처'),('observed_date','관측일 YYYY-MM-DD'),('published_date','발표일 YYYY-MM-DD')]:
                    condition[field] = st.text_input(label,condition.get(field,''),key=ck+'_'+field)
            if op == 'schedule':
                condition['frequency'] = select('조건 주기', list(FREQUENCIES), condition.get('frequency','monthly'), ck+'_schedule', FREQUENCIES)
                if condition['frequency'] == 'months':
                    condition['months_list'] = st.multiselect('조건 실행 월',list(range(1,13)),default=condition.get('months_list',[3,6,9,12]),key=ck+'_schedule_months')
            st.markdown('<div class="builder-section">조건 해석</div>',unsafe_allow_html=True)
            st.markdown(condition_sentence(condition,names),unsafe_allow_html=True)
            if st.button('이 조건 삭제',key=ck+'_remove'):
                conditions.pop(i)
                st.session_state[spec_key+'_revision']=st.session_state.get(spec_key+'_revision',0)+1
                st.rerun()
    if st.button('＋ 조건 추가', key=key+'_add',use_container_width=True):
        conditions.append({'ticker':'QQQ','op':'sma_above','months':10,'connector':'AND'})
        st.rerun()
    return conditions


def edit_action(branch, key, candidates, signal_labels):
    """Render & edit one then/else action's fields; mutates and returns the branch dict.

    Shared by the single-spec THEN/ELSE editor and each independent rule's
    then/else editor in the multi-rule editor.
    """
    chosen=select('실행할 행동', list(ACTIONS), branch.get('action'), key+'_action', ACTIONS)
    if chosen!=branch.get('action'):
        branch['action'],branch['params']=chosen,{}
    bk = key+'_'+branch['action']
    p = branch.setdefault('params', {})
    if branch['action'] in ('restore','restore_scope'):
        p['restore_frequency']=select('목표 복원 주기',list(FREQUENCIES),p.get('restore_frequency','monthly'),bk+'_restore',FREQUENCIES)
        if p['restore_frequency']=='months':
            p['restore_months']=st.multiselect('목표 복원 월',list(range(1,13)),default=p.get('restore_months',[3,6,9,12]),key=bk+'_restore_months')
    if branch['action'] in ('move_all','set_weight','buy_cash_pct','buy_to_weight','switch_scope'):
        p['ticker'] = select('대상 종목', candidates, p.get('ticker'), bk+'_ticker',signal_labels)
    if branch['action'] in ('set_weight','buy_cash_pct','buy_to_weight'):
        p['pct'] = st.slider('목표/투입 비율(%)', 0,100,int(p.get('pct',50)), key=bk+'_pct')
    if branch['action'] in ('restore_scope','switch_scope'):
        p['tickers'] = st.multiselect('적용할 종목', [t for t in candidates if t not in ('CASH','__winner__')],
            default=p.get('tickers',[]),key=bk+'_tickers',format_func=lambda t:signal_labels.get(t,t))
        p['role'] = st.text_input('또는 적용할 역할 (입력 시 역할 우선)',p.get('role',''),key=bk+'_role')
    if branch['action'] == 'move_all':
        p['cashPct'] = st.slider('유지할 현금 비중(%)',0,100,int(p.get('cashPct',0)),key=bk+'_cash')
    if branch['action'] == 'notify':
        p['message'] = st.text_input('표시할 메시지', p.get('message','전략 점검'), key=bk+'_message')
        st.caption('앱 내 메시지입니다. 이메일·외부 알림은 전송하지 않습니다.')
    return branch


def render(strategies, holdings, priced_view, as_of, fetch, go_to_monthly=None):
    st.subheader('규칙 빌더')
    st.caption('실행 일정과 조건, 충족·미충족 시 행동을 선택하고 실제 종가로 검증합니다.')
    codes = strategies['code'].astype(str).tolist()
    if not codes:
        st.info('전략 관리에서 전략을 먼저 추가하세요.')
        return
    with st.container(key='builder_toolbar'):
        st.markdown('<div class="builder-section">전략 선택</div>',unsafe_allow_html=True)
        accounts=holdings.groupby('strategy',sort=False)['account'].first().to_dict()
        code = st.selectbox('편집할 전략', codes, key='studio_code',
            format_func=lambda value:f'{value} · {accounts.get(value,"계좌 미지정")}')
    row = strategies.loc[strategies['code'].astype(str).eq(code)].iloc[0]
    assets = holdings[holdings['strategy'].astype(str).eq(code)]
    sub = priced_view[priced_view['strategy'].astype(str).eq(code)] if priced_view is not None else None
    names=dict(zip(holdings.ticker.astype(str),holdings.name.astype(str)))
    signal_labels={ticker:f'{names.get(ticker,ticker)} · {ticker}' for ticker in names}
    signal_labels['__winner__']='조건에서 선정된 자산'
    try:
        params = json.loads(row.get('params_json') or '{}')
    except (TypeError, ValueError):
        params = {}
    mode_choice = st.radio('조건 구성 방식', ['단일 조건 묶음','독립 규칙 여러 개 (종목별 분리)'],
        index=1 if params.get('schema_version')==4 else 0, key=f'studio_{code}_rule_mode', horizontal=True,
        help='서로 다른 종목을 각각 독립적인 조건으로 담당시키려면 두 번째를 선택하세요. 예: 주식 신호 따로, 채권 신호 따로.')
    if mode_choice=='독립 규칙 여러 개 (종목별 분리)':
        render_multi(code, row, assets, holdings, sub, as_of, fetch, go_to_monthly, names, signal_labels, params)
        return
    spec_key = f'studio_{code}_{row.get("version", "1")}'
    if spec_key not in st.session_state:
        st.session_state[spec_key] = copy.deepcopy(params if params.get('schema_version') == 2 else new_spec())
    spec = st.session_state[spec_key]
    key=f'{spec_key}_v{st.session_state.get(spec_key+"_revision",0)}'
    st.caption(f'편집 중인 초안 · 버전 {row.get("version", "1")} · 조건 {len(spec["conditions"])}개 · 적용 전까지 현재 전략은 유지됩니다.')
    if row['rule'] != 'visual' or params.get('schema_version') != 2:
        st.info('현재 기존 규칙은 보존되어 있습니다. 아래 초안을 적용할 때만 새 조건 규칙으로 전환됩니다.')
    preview_slot=st.empty()
    left, right = st.columns([2, 1])
    with left:
        st.subheader('1 · IF · 조건과 일정')
        st.markdown('<div class="builder-section">SCOPE · 실행 주기</div>',unsafe_allow_html=True)
        spec['scope']['run'] = select('판정 주기', list(FREQUENCIES), spec['scope'].get('run'), key+'_run', FREQUENCIES)
        if spec['scope']['run'] == 'months':
            spec['scope']['months'] = st.multiselect('실행 월', list(range(1,13)), default=spec['scope'].get('months',[3,6,9,12]), key=key+'_months')
        with st.expander('고급 설정 · 시계열과 표 편집'):
            spec['signal_adjusted'] = st.checkbox('신호에 수정종가 사용', bool(spec.get('signal_adjusted',False)), key=key+'_adjusted')
            spec['completed_months_only'] = st.checkbox('이전 확정 월봉만 사용', bool(spec.get('completed_months_only',False)), key=key+'_completed')
            spec['scope']['market'] = select('신호 시장 분류', ['MIX','KR','US'], spec['scope'].get('market'), key+'_market')
            st.caption('시장 분류는 표시용이며 주문 대상을 제한하지 않습니다. 미국 신호로 한국 ETF를 매매할 수 있습니다. 지정일이 속한 월로 일정을 판정합니다.')
            mode = st.radio('조건 편집 방식', ['카드','표'], horizontal=True, key=key+'_mode')
        if len(spec['conditions'])>1:
            st.caption('위에서 아래로 연결합니다: (A AND B) OR C. AND는 모두 충족, OR는 하나 이상 충족입니다.')
        spec['conditions'] = edit_conditions(spec['conditions'], key, spec_key, assets, holdings, signal_labels, names, mode)
    with right:
        st.subheader('2 · THEN / ELSE · 행동')
        candidates = list(dict.fromkeys(assets['ticker'].astype(str).tolist() + ['__winner__']))
        for branch, title in [('onPass','조건 충족 시'), ('onFail','조건 미충족 시')]:
            with st.container(border=True,key='builder_then' if branch=='onPass' else 'builder_else'):
                style='then' if branch=='onPass' else 'else'
                st.markdown(f'<div class="builder-section"><span class="{style}">'
                    f'{"THEN · 조건 충족" if branch=="onPass" else "ELSE · 조건 미충족"}'
                    '</span></div>',unsafe_allow_html=True)
                b = spec.setdefault(branch, {'action':'hold_buy','params':{}})
                edit_action(b, key+branch, candidates, signal_labels)
        st.caption('특정 비중 설정의 잔여 금액은 나머지 종목의 현재 평가액 비율로 배분합니다.')
    preview_slot.markdown(rule_preview_html(spec,names),unsafe_allow_html=True)
    st.subheader('3 · 실제 신호와 목표 금액 검증')
    st.caption('수량 단위·허용 괴리·CASH 한도를 적용하기 전 목표 금액입니다. 규칙 적용 후 종가를 다시 조회하면 주문안에서 최종 수량을 확인할 수 있습니다.')
    result = evaluate(spec, sub, as_of, fetch) if sub is not None and not sub.empty else None
    if result is None:
        st.info('이번 달에서 선택한 기준일의 종가를 조회하면 판정 근거와 목표 금액을 확인하고 규칙을 적용할 수 있습니다.')
        if go_to_monthly:
            st.button('이번 달에서 종가 확인',on_click=go_to_monthly,use_container_width=True)
    else:
        st.write(f"**{result['status']}** · {result['message']} · 다음 기준일: {result.get('next_run','—')}")
        if result['evidence']:
            evidence = prefer_asset_names(pd.DataFrame(result['evidence']), holdings)
            st.dataframe(evidence, column_config=numeric_column_config(evidence.columns), hide_index=True, use_container_width=True)
        if result.get('ranking'):
            ranking = prefer_asset_names(pd.DataFrame(result['ranking']), holdings)
            st.dataframe(ranking.style.format({'모멘텀':'{:.2%}'}), hide_index=True)
        preview = pd.DataFrame([{'티커':t,'현재평가액':v,'목표평가액':result['targets'][t], '예상매매액':result['targets'][t]-v}
                                for t,v in zip(sub['ticker'],sub['평가액'])])
        preview = prefer_asset_names(preview, holdings)
        st.dataframe(preview, column_config=numeric_column_config(preview.columns), hide_index=True, use_container_width=True)
    with st.expander('버전과 변경 기록'):
        version = st.text_input('적용할 버전', str(row.get('version','1.0')), key=key+'_version')
        note = st.text_input('변경 이유', key=key+'_note')
    if st.button('검토한 규칙 적용', type='primary', key=key+'_save',
                 disabled=not spec['conditions'] or result is None or result['status']=='계산 차단'):
        updated = st.session_state.strategies.copy()
        mask = updated['code'].astype(str).eq(code)
        updated.loc[mask,'rule'] = 'visual'
        updated.loc[mask,'params_json'] = json.dumps(spec, ensure_ascii=False)
        updated.loc[mask,'version'] = version
        updated.loc[mask,'change_note'] = note
        updated.loc[mask,'effective_date'] = as_of.isoformat()
        archive = st.session_state.strategies.copy()
        archive['archived_at'] = pd.Timestamp.now(tz='UTC').isoformat()
        st.session_state.strategy_versions = pd.concat([st.session_state.strategy_versions,archive],ignore_index=True)
        st.session_state.strategies = updated
        st.session_state.pop('priced_holdings',None)
        st.session_state.pop('run',None)
        st.session_state.dirty = True
        st.session_state.studio_notice='전략 규칙을 적용했습니다. 이번 달에서 종가를 다시 조회하면 변경된 규칙의 주문안이 생성됩니다.'
        st.rerun()


def render_multi(code, row, assets, holdings, sub, as_of, fetch, go_to_monthly, names, signal_labels, params):
    """독립 규칙 여러 개(schema_version 4) 편집 화면.

    규칙마다 담당 종목(scope)을 지정하고, 각자 조건과 THEN/ELSE 동작을 독립적으로
    결정한다. 모든 규칙이 동시에 적용되며, scope가 겹치는 규칙은 저장을 막는다.
    """
    spec_key = f'studio_{code}_{row.get("version", "1")}_multi'
    if spec_key not in st.session_state:
        st.session_state[spec_key] = copy.deepcopy(params if params.get('schema_version') == 4 else new_multi_spec())
    spec = st.session_state[spec_key]
    rules = spec.setdefault('rules', [])
    key = f'{spec_key}_v{st.session_state.get(spec_key+"_revision",0)}'
    st.caption(f'편집 중인 초안 · 버전 {row.get("version", "1")} · 규칙 {len(rules)}개 · 적용 전까지 현재 전략은 유지됩니다.')
    if row['rule'] != 'visual' or params.get('schema_version') != 4:
        st.info('현재 기존 규칙은 보존되어 있습니다. 아래 초안을 적용할 때만 새 조건 규칙으로 전환됩니다.')

    st.markdown('<div class="builder-section">SCOPE · 실행 주기 (모든 규칙 공통)</div>',unsafe_allow_html=True)
    spec['scope']['run'] = select('판정 주기', list(FREQUENCIES), spec['scope'].get('run'), key+'_run', FREQUENCIES)
    if spec['scope']['run'] == 'months':
        spec['scope']['months'] = st.multiselect('실행 월', list(range(1,13)), default=spec['scope'].get('months',[3,6,9,12]), key=key+'_months')
    with st.expander('고급 설정 · 시계열과 표 편집'):
        spec['signal_adjusted'] = st.checkbox('신호에 수정종가 사용', bool(spec.get('signal_adjusted',False)), key=key+'_adjusted')
        spec['completed_months_only'] = st.checkbox('이전 확정 월봉만 사용', bool(spec.get('completed_months_only',False)), key=key+'_completed')
        spec['scope']['market'] = select('신호 시장 분류', ['MIX','KR','US'], spec['scope'].get('market'), key+'_market')
        condition_mode = st.radio('조건 편집 방식', ['카드','표'], horizontal=True, key=key+'_mode')

    st.caption('규칙마다 담당 종목(scope)을 지정하세요. 같은 종목을 두 규칙이 동시에 담당할 수 없고, 어떤 규칙에도 속하지 않은 보유 종목은 그대로 유지됩니다.')
    all_tickers = list(dict.fromkeys(assets['ticker'].astype(str).tolist()))
    used_scope = set()
    for rule in rules:
        used_scope |= set(rule.get('scope') or [])

    for i, rule in enumerate(rules):
        rk = f'{key}_r{i}'
        with st.container(border=True):
            st.markdown(f'<div class="builder-section">규칙 {i+1}</div>',unsafe_allow_html=True)
            rule['name'] = st.text_input('규칙 이름', rule.get('name', f'규칙 {i+1}'), key=rk+'_name')
            others_scope = used_scope - set(rule.get('scope') or [])
            scope_options = [t for t in all_tickers if t not in others_scope]
            rule['scope'] = st.multiselect('담당 종목 (scope)', scope_options,
                default=[t for t in (rule.get('scope') or []) if t in scope_options],
                key=rk+'_scope', format_func=lambda t: signal_labels.get(t,t),
                help='이 규칙이 THEN/ELSE로 비중을 조정할 종목들입니다. 다른 규칙과 겹칠 수 없습니다.')
            if len(rule.get('conditions',[]))>1:
                st.caption('위에서 아래로 연결합니다: (A AND B) OR C.')
            rule['conditions'] = edit_conditions(rule.get('conditions',[]), rk, spec_key, assets, holdings, signal_labels, names, condition_mode)
            scope_candidates = list(dict.fromkeys((rule.get('scope') or [])+['__winner__']))
            for branch_key, label in [('then','THEN · 조건 충족'), ('else','ELSE · 조건 미충족')]:
                with st.container(border=True):
                    style='then' if branch_key=='then' else 'else'
                    st.markdown(f'<div class="builder-section"><span class="{style}">{label}</span></div>',unsafe_allow_html=True)
                    b = rule.setdefault(branch_key, {'action':'hold_buy','params':{}})
                    edit_action(b, rk+'_'+branch_key, scope_candidates, signal_labels)
            if st.button('이 규칙 삭제', key=rk+'_remove', disabled=len(rules)<=1,
                         help=None if len(rules)>1 else '최소 1개의 규칙이 필요합니다'):
                rules.pop(i)
                st.session_state[spec_key+'_revision']=st.session_state.get(spec_key+'_revision',0)+1
                st.rerun()
    if st.button('＋ 규칙 추가', key=key+'_add_rule', use_container_width=True):
        rules.append(new_rule(f'규칙 {len(rules)+1}'))
        st.rerun()

    st.subheader('실제 신호와 목표 금액 검증')
    st.caption('수량 단위·허용 괴리·CASH 한도를 적용하기 전 목표 금액입니다. 규칙 적용 후 종가를 다시 조회하면 주문안에서 최종 수량을 확인할 수 있습니다.')
    result = evaluate(spec, sub, as_of, fetch) if sub is not None and not sub.empty else None
    if result is None:
        st.info('이번 달에서 선택한 기준일의 종가를 조회하면 판정 근거와 목표 금액을 확인하고 규칙을 적용할 수 있습니다.')
        if go_to_monthly:
            st.button('이번 달에서 종가 확인',on_click=go_to_monthly,use_container_width=True,key=key+'_goto')
    else:
        st.write(f"**{result['status']}** · {result['message']} · 다음 기준일: {result.get('next_run','—')}")
        if result.get('rules'):
            st.dataframe(pd.DataFrame(result['rules']), hide_index=True, use_container_width=True)
        if result['evidence']:
            evidence = prefer_asset_names(pd.DataFrame(result['evidence']), holdings)
            st.dataframe(evidence, column_config=numeric_column_config(evidence.columns), hide_index=True, use_container_width=True)
        preview = pd.DataFrame([{'티커':t,'현재평가액':v,'목표평가액':result['targets'][t], '예상매매액':result['targets'][t]-v}
                                for t,v in zip(sub['ticker'],sub['평가액'])])
        preview = prefer_asset_names(preview, holdings)
        st.dataframe(preview, column_config=numeric_column_config(preview.columns), hide_index=True, use_container_width=True)
    with st.expander('버전과 변경 기록'):
        version = st.text_input('적용할 버전', str(row.get('version','1.0')), key=key+'_version')
        note = st.text_input('변경 이유', key=key+'_note')
    seen=set();overlap_found=False
    for rule in rules:
        s=set(rule.get('scope') or [])
        if s & seen: overlap_found=True
        seen |= s
    disabled = (not rules) or any(not r.get('scope') for r in rules) or overlap_found or result is None or result['status']=='계산 차단'
    if overlap_found:
        st.error('규칙끼리 담당 종목이 겹칩니다. 각 규칙의 담당 종목을 다시 확인하세요.')
    elif any(not r.get('scope') for r in rules):
        st.warning('담당 종목이 비어 있는 규칙이 있습니다.')
    if st.button('검토한 규칙 적용', type='primary', key=key+'_save', disabled=disabled):
        updated = st.session_state.strategies.copy()
        mask = updated['code'].astype(str).eq(code)
        updated.loc[mask,'rule'] = 'visual'
        updated.loc[mask,'params_json'] = json.dumps(spec, ensure_ascii=False)
        updated.loc[mask,'version'] = version
        updated.loc[mask,'change_note'] = note
        updated.loc[mask,'effective_date'] = as_of.isoformat()
        archive = st.session_state.strategies.copy()
        archive['archived_at'] = pd.Timestamp.now(tz='UTC').isoformat()
        st.session_state.strategy_versions = pd.concat([st.session_state.strategy_versions,archive],ignore_index=True)
        st.session_state.strategies = updated
        st.session_state.pop('priced_holdings',None)
        st.session_state.pop('run',None)
        st.session_state.dirty = True
        st.session_state.studio_notice='전략 규칙을 적용했습니다. 이번 달에서 종가를 다시 조회하면 변경된 규칙의 주문안이 생성됩니다.'
        st.rerun()
