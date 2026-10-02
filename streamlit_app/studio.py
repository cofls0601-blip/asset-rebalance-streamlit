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


def render(strategies, holdings, priced_view, as_of, fetch):
    st.subheader('규칙 빌더')
    st.caption('실행 일정과 조건, 충족·미충족 시 행동을 선택하고 실제 종가로 검증합니다.')
    codes = strategies['code'].astype(str).tolist()
    if not codes:
        st.info('전략 관리에서 전략을 먼저 추가하세요.')
        return
    with st.container(key='builder_toolbar'):
        st.markdown('<div class="builder-section">전략 선택</div>',unsafe_allow_html=True)
        code = st.selectbox('편집할 전략', codes, key='studio_code')
    row = strategies.loc[strategies['code'].astype(str).eq(code)].iloc[0]
    assets = holdings[holdings['strategy'].astype(str).eq(code)]
    sub = priced_view[priced_view['strategy'].astype(str).eq(code)] if priced_view is not None else None
    names=dict(zip(holdings.ticker.astype(str),holdings.name.astype(str)))
    signal_labels={ticker:f'{names.get(ticker,ticker)} · {ticker}' for ticker in names}
    signal_labels['__winner__']='조건에서 선정된 자산'
    spec_key = f'studio_{code}_{row.get("version", "1")}'
    try:
        params = json.loads(row.get('params_json') or '{}')
    except (TypeError, ValueError):
        params = {}
    if spec_key not in st.session_state:
        st.session_state[spec_key] = copy.deepcopy(params if params.get('schema_version') == 2 else new_spec())
    spec = st.session_state[spec_key]
    key=f'{spec_key}_v{st.session_state.get(spec_key+"_revision",0)}'
    st.caption(f'{row.get("account", "")} · 버전 {row.get("version", "1")} · 조건 {len(spec["conditions"])}개')
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
        spec['signal_adjusted'] = st.checkbox('신호에 수정종가 사용', bool(spec.get('signal_adjusted',False)), key=key+'_adjusted')
        spec['completed_months_only'] = st.checkbox('이전 확정 월봉만 사용', bool(spec.get('completed_months_only',False)), key=key+'_completed')
        spec['scope']['market'] = select('신호 시장 분류', ['MIX','KR','US'], spec['scope'].get('market'), key+'_market')
        st.caption('시장 분류는 표시용이며 주문 대상을 제한하지 않습니다. 미국 신호로 한국 ETF를 매매할 수 있습니다. 지정일이 속한 월로 일정을 판정합니다. 매도대금은 이번 주문안의 매수 재원에 포함하지 않습니다.')
        mode = st.radio('조건 편집 방식', ['카드','표'], horizontal=True, key=key+'_mode')
        st.caption('조건 연결은 위에서 아래로 왼쪽부터 계산합니다: (A AND B) OR C. 데이터가 하나라도 없으면 매매를 차단합니다.')
        if mode == '표':
            columns = ['connector','op','ticker','months','days','lookback','pct','price','tickerB','tickers','rank','frequency','value','threshold','source','observed_date','published_date','months_list']
            frame = pd.DataFrame(spec['conditions']).reindex(columns=columns)
            frame['tickers'] = frame['tickers'].map(lambda x: ','.join(x) if isinstance(x,list) else x)
            frame['months_list'] = frame['months_list'].map(lambda x: ','.join(map(str,x)) if isinstance(x,list) else x)
            frame = st.data_editor(frame, num_rows='dynamic', hide_index=True, use_container_width=True,
                key=key+'_table', column_config=numeric_column_config(frame.columns, {'op':st.column_config.SelectboxColumn(options=list(OPERATORS)),
                'connector':st.column_config.SelectboxColumn(options=['AND','OR']),
                'frequency':st.column_config.SelectboxColumn(options=list(FREQUENCIES))}))
            spec['conditions'] = [{k:v for k,v in r.items() if pd.notna(v) and v != ''} for r in frame.to_dict('records')]
        else:
            if not spec['conditions']:
                st.info('조건이 없습니다. 아래 ‘조건 추가’로 시작하세요.')
            for i, condition in enumerate(spec['conditions']):
                ck = f'{key}_c{i}'
                with st.container(border=True,key=f'builder_condition_{i}'):
                    st.markdown(f'<div class="builder-section">IF · 조건 {i+1:02d}</div>',unsafe_allow_html=True)
                    if i:
                        condition['connector'] = st.radio('앞 조건과 연결', ['AND','OR'],
                            index=0 if condition.get('connector','AND')=='AND' else 1,
                            horizontal=True,key=ck+'_connect')
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
                        candidates = condition.get('tickers', [])
                        if isinstance(candidates,str):
                            candidates=[t.strip() for t in candidates.split(',') if t.strip()]
                        ticker_options=list(dict.fromkeys([t for t in assets.ticker.astype(str) if t!='CASH']+
                            [t for t in holdings.ticker.astype(str) if t!='CASH']+candidates))
                        selected=st.multiselect('순위 후보',ticker_options,default=candidates,
                            key=ck+'_candidates',format_func=lambda t:signal_labels.get(t,t))
                        extra=st.text_input('후보 티커 추가 (쉼표 구분)',key=ck+'_candidate_extra',
                            help='보유하지 않은 QQQ, SPY 같은 신호 종목도 추가할 수 있습니다.')
                        added=[t.strip().upper() for t in extra.split(',') if t.strip()]
                        condition['tickers']=list(dict.fromkeys(selected+added))
                        targets=['__winner__']+list(dict.fromkeys(condition['tickers']+
                            ([condition['ticker']] if condition.get('ticker') not in ('','__winner__') else [])))
                        condition['ticker']=select('순위 판정 대상',targets,condition.get('ticker','__winner__'),
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
                        spec['conditions'].pop(i)
                        st.session_state[spec_key+'_revision']=st.session_state.get(spec_key+'_revision',0)+1
                        st.rerun()
            if st.button('＋ 조건 추가', key=key+'_add',use_container_width=True):
                spec['conditions'].append({'ticker':'QQQ','op':'sma_above','months':10,'connector':'AND'})
                st.rerun()
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
                chosen=select('실행할 행동', list(ACTIONS), b.get('action'), key+branch+'_action', ACTIONS)
                if chosen!=b.get('action'):
                    b['action'],b['params']=chosen,{}
                bk = key+branch+'_'+b['action']
                p = b.setdefault('params', {})
                if b['action'] in ('restore','restore_scope'):
                    p['restore_frequency']=select('목표 복원 주기',list(FREQUENCIES),p.get('restore_frequency','monthly'),bk+'_restore',FREQUENCIES)
                    if p['restore_frequency']=='months':
                        p['restore_months']=st.multiselect('목표 복원 월',list(range(1,13)),default=p.get('restore_months',[3,6,9,12]),key=bk+'_restore_months')
                if b['action'] in ('move_all','set_weight','buy_cash_pct','buy_to_weight','switch_scope'):
                    p['ticker'] = select('대상 종목', candidates, p.get('ticker'), bk+'_ticker',signal_labels)
                if b['action'] in ('set_weight','buy_cash_pct','buy_to_weight'):
                    p['pct'] = st.slider('목표/투입 비율(%)', 0,100,int(p.get('pct',50)), key=bk+'_pct')
                if b['action'] in ('restore_scope','switch_scope'):
                    p['tickers'] = st.multiselect('적용할 종목', [t for t in candidates if t not in ('CASH','__winner__')],
                        default=p.get('tickers',[]),key=bk+'_tickers',format_func=lambda t:signal_labels.get(t,t))
                    p['role'] = st.text_input('또는 적용할 역할 (입력 시 역할 우선)',p.get('role',''),key=bk+'_role')
                if b['action'] == 'move_all':
                    p['cashPct'] = st.slider('유지할 현금 비중(%)',0,100,int(p.get('cashPct',0)),key=bk+'_cash')
                if b['action'] == 'notify':
                    p['message'] = st.text_input('표시할 메시지', p.get('message','전략 점검'), key=bk+'_message')
                    st.caption('앱 내 메시지입니다. 이메일·외부 알림은 전송하지 않습니다.')
        st.caption('특정 비중 설정의 잔여 금액은 나머지 종목의 현재 평가액 비율로 배분합니다.')
    preview_slot.markdown(rule_preview_html(spec,names),unsafe_allow_html=True)
    st.subheader('3 · 실제 신호와 목표 금액 검증')
    st.caption('수량 단위·허용 괴리·CASH 한도를 적용하기 전 목표 금액입니다. 규칙 적용 후 종가를 다시 조회하면 주문안에서 최종 수량을 확인할 수 있습니다.')
    result = evaluate(spec, sub, as_of, fetch) if sub is not None and not sub.empty else None
    if result is None:
        st.info('이번 달에서 선택한 기준일의 종가를 조회하면 판정 근거와 목표 금액을 확인하고 규칙을 적용할 수 있습니다.')
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
        st.success('전략 규칙을 세션에 적용했습니다. Sheets에 저장하거나 전체 백업을 내려받으세요.')
        st.rerun()
