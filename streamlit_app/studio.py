"""Streamlit strategy studio; the preview and order plan use the same engine."""
import copy
import json
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
                        key=key, format_func=(labels or {}).get if labels else str)


def render(strategies, holdings, priced_view, as_of, fetch):
    st.subheader('조건과 행동 편집')
    st.caption('조건 설정, 현재 신호 검증, 주문안 미리보기와 적용을 한 화면에서 순서대로 진행합니다.')
    codes = strategies['code'].astype(str).tolist()
    if not codes:
        st.info('전략 관리에서 전략을 먼저 추가하세요.')
        return
    code = st.selectbox('편집할 전략', codes, key='studio_code')
    row = strategies.loc[strategies['code'].astype(str).eq(code)].iloc[0]
    assets = holdings[holdings['strategy'].astype(str).eq(code)]
    sub = priced_view[priced_view['strategy'].astype(str).eq(code)]
    key = f'studio_{code}_{row.get("version", "1")}'
    if key not in st.session_state:
        try:
            params = json.loads(row.get('params_json') or '{}')
        except (TypeError, ValueError):
            params = {}
        st.session_state[key] = copy.deepcopy(params if params.get('schema_version') == 2 else new_spec())
    spec = st.session_state[key]
    if row['rule'] != 'visual' or json.loads(row.get('params_json') or '{}').get('schema_version') != 2:
        st.info('현재 기존 규칙은 보존되어 있습니다. 아래 초안을 적용할 때만 새 조건 규칙으로 전환됩니다.')
    left, right = st.columns([2, 1])
    with left:
        st.subheader('1 · 조건과 일정')
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
            for i, condition in enumerate(spec['conditions']):
                ck = f'{key}_c{i}'
                with st.container(border=True):
                    st.markdown(f'#### 조건 {i+1}')
                    if i:
                        condition['connector'] = select('앞 조건과 연결', ['AND','OR'], condition.get('connector'), ck+'_connect')
                    condition['op'] = select('조건 종류', list(OPERATORS), condition.get('op'), ck+'_op', OPERATORS)
                    op = condition['op']
                    if op not in ('schedule','external_above'):
                        condition['ticker'] = st.text_input('신호 티커 (1위 참조: __winner__)', value=condition.get('ticker',''), key=ck+'_ticker').strip()
                    if op.startswith('sma') or op in ('mom_rank','momentum_above'):
                        condition['months'] = st.number_input('기간(개월)', 1, 36, int(condition.get('months',10)), key=ck+'_months')
                    if op.startswith('ema'):
                        condition['days'] = st.number_input('EMA 기간(거래일)', 1,750,int(condition.get('days',200)),key=ck+'_days')
                    if op.startswith('dd_'):
                        condition['lookback'] = st.number_input('고점 조회 거래일', 1, 750, int(condition.get('lookback',120)), key=ck+'_lookback')
                        condition['pct'] = st.number_input('낙폭 기준(%, 예: -10)', -100.0, 0.0, float(condition.get('pct',-10)), key=ck+'_dd')
                    if op == 'mom_rank':
                        candidates = condition.get('tickers', [])
                        condition['tickers'] = st.text_input('순위 후보 (쉼표 구분)', ','.join(candidates) if isinstance(candidates,list) else candidates, key=ck+'_candidates')
                        condition['rank'] = st.number_input('순위 이내', 1, 100, int(condition.get('rank',1)), key=ck+'_rank')
                        st.caption('신호 티커를 비우면 후보 중 1위를 선택합니다. 다음 조건·동작에서 __winner__로 참조합니다.')
                    if op.startswith('price_'):
                        condition['price'] = st.number_input('기준 가격(현지통화)', 0.0, value=float(condition.get('price',0)), key=ck+'_price', format='%.0f')
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
            add, remove = st.columns(2)
            if add.button('조건 추가', key=key+'_add'):
                spec['conditions'].append({'ticker':'QQQ','op':'sma_above','months':10,'connector':'AND'})
                st.rerun()
            if remove.button('마지막 조건 삭제', key=key+'_remove', disabled=not spec['conditions']):
                spec['conditions'].pop()
                st.rerun()
    with right:
        st.subheader('2 · 판정별 동작')
        candidates = list(dict.fromkeys(assets['ticker'].astype(str).tolist() + ['__winner__']))
        for branch, title in [('onPass','조건 충족 시'), ('onFail','조건 미충족 시')]:
            with st.container(border=True):
                st.markdown(f'#### {title}')
                b = spec.setdefault(branch, {'action':'hold_buy','params':{}})
                bk = key+branch
                b['action'] = select('동작', list(ACTIONS), b.get('action'), bk+'_action', ACTIONS)
                p = b.setdefault('params', {})
                if b['action'] in ('restore','restore_scope'):
                    p['restore_frequency']=select('목표 복원 주기',list(FREQUENCIES),p.get('restore_frequency','monthly'),bk+'_restore',FREQUENCIES)
                    if p['restore_frequency']=='months':
                        p['restore_months']=st.multiselect('목표 복원 월',list(range(1,13)),default=p.get('restore_months',[3,6,9,12]),key=bk+'_restore_months')
                if b['action'] in ('move_all','set_weight','buy_cash_pct','buy_to_weight','switch_scope'):
                    p['ticker'] = select('대상', candidates, p.get('ticker'), bk+'_ticker')
                if b['action'] in ('set_weight','buy_cash_pct','buy_to_weight'):
                    p['pct'] = st.slider('목표/투입 비율(%)', 0,100,int(p.get('pct',50)), key=bk+'_pct')
                if b['action'] in ('restore_scope','switch_scope'):
                    p['tickers'] = st.multiselect('적용할 종목', [t for t in candidates if t not in ('CASH','__winner__')],default=p.get('tickers',[]),key=bk+'_tickers')
                    p['role'] = st.text_input('또는 적용할 역할 (입력 시 역할 우선)',p.get('role',''),key=bk+'_role')
                if b['action'] == 'move_all':
                    p['cashPct'] = st.slider('유지할 현금 비중(%)',0,100,int(p.get('cashPct',0)),key=bk+'_cash')
                if b['action'] == 'notify':
                    p['message'] = st.text_input('표시할 메시지', p.get('message','전략 점검'), key=bk+'_message')
                    st.caption('앱 내 메시지입니다. 이메일·외부 알림은 전송하지 않습니다.')
        st.caption('특정 비중 설정의 잔여 금액은 나머지 종목의 현재 평가액 비율로 배분합니다.')
    st.subheader('3 · 규칙 요약 및 목표 금액 미리보기')
    st.caption('수량 단위·허용 괴리·CASH 한도를 적용하기 전 목표 금액입니다. 규칙 적용 후 종가를 다시 조회하면 주문안에서 최종 수량을 확인할 수 있습니다.')
    sentences = []
    for i,c in enumerate(spec['conditions']):
        label = f"{c.get('ticker','후보')} {OPERATORS.get(c.get('op'), '조건 미선택')}"
        sentences.append((f"{c.get('connector','AND')} " if i else '') + label)
    summary=st.columns(3)
    with summary[0]:
        with st.container(border=True):
            st.caption('판정 조건')
            st.write(' '.join(sentences) or '조건 없음')
    with summary[1]:
        with st.container(border=True):
            st.caption('조건 충족 시')
            st.write(ACTIONS[spec['onPass']['action']])
    with summary[2]:
        with st.container(border=True):
            st.caption('조건 미충족 시')
            st.write(ACTIONS[spec['onFail']['action']])
    result = evaluate(spec, sub, as_of, fetch)
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
    if st.button('검토한 규칙 적용', type='primary', key=key+'_save', disabled=not spec['conditions'] or result['status']=='계산 차단'):
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
        st.success('세션에 적용했습니다. 기록 화면에서 Strategies를 복사하여 시트에 저장하세요.')
        st.rerun()
