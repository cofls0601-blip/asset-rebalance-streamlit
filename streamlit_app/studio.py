"""Streamlit strategy studio; the preview and order plan use the same engine."""
import copy
import json
import pandas as pd
import streamlit as st
from streamlit_app.rules import ACTIONS, OPERATORS, FREQUENCIES, evaluate


def new_spec():
    return {'schema_version':2, 'scope':{'market':'MIX','run':'monthly'},
            'conditions':[{'ticker':'QQQ','op':'sma_above','months':10,'connector':'AND'}],
            'onPass':{'action':'hold_buy','params':{}}, 'onFail':{'action':'hold_buy','params':{}}}


def select(label, choices, value, key, labels=None):
    return st.selectbox(label, choices, index=choices.index(value) if value in choices else 0,
                        key=key, format_func=(labels or {}).get if labels else str)


def render(strategies, holdings, priced_view, as_of, fetch):
    st.title('Strategy Studio')
    st.caption('조건 설정 → 현재 신호 검증 → 주문안 미리보기 → 명시적으로 적용')
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
        spec['scope']['market'] = select('신호 시장 분류', ['MIX','KR','US'], spec['scope'].get('market'), key+'_market')
        st.caption('시장 분류는 표시용이며 주문 대상을 제한하지 않습니다. 미국 신호로 한국 ETF를 매매할 수 있습니다. 일정은 달력 말일 기준, 휴장일 가격은 직전 거래일을 사용합니다.')
        mode = st.radio('조건 편집 방식', ['카드','표'], horizontal=True, key=key+'_mode')
        st.caption('조건 연결은 위에서 아래로 왼쪽부터 계산합니다: (A AND B) OR C. 데이터가 하나라도 없으면 매매를 차단합니다.')
        if mode == '표':
            columns = ['connector','op','ticker','months','days','lookback','pct','price','tickerB','tickers','rank','frequency']
            frame = pd.DataFrame(spec['conditions']).reindex(columns=columns)
            frame['tickers'] = frame['tickers'].map(lambda x: ','.join(x) if isinstance(x,list) else x)
            frame = st.data_editor(frame, num_rows='dynamic', hide_index=True, use_container_width=True,
                key=key+'_table', column_config={'op':st.column_config.SelectboxColumn(options=list(OPERATORS)),
                'connector':st.column_config.SelectboxColumn(options=['AND','OR']),
                'frequency':st.column_config.SelectboxColumn(options=list(FREQUENCIES))})
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
                    if op != 'schedule':
                        condition['ticker'] = st.text_input('신호 티커 (1위 참조: __winner__)', value=condition.get('ticker',''), key=ck+'_ticker').strip()
                    if op.startswith('sma') or op == 'mom_rank':
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
                    if op == 'schedule':
                        condition['frequency'] = select('조건 주기', list(FREQUENCIES), condition.get('frequency','monthly'), ck+'_schedule', FREQUENCIES)
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
                if b['action'] in ('move_all','set_weight','buy_cash_pct'):
                    p['ticker'] = select('대상', candidates, p.get('ticker'), bk+'_ticker')
                if b['action'] in ('set_weight','buy_cash_pct'):
                    p['pct'] = st.slider('목표/투입 비율(%)', 0,100,int(p.get('pct',50)), key=bk+'_pct')
                if b['action'] == 'move_all':
                    p['cashPct'] = st.slider('유지할 현금 비중(%)',0,100,int(p.get('cashPct',0)),key=bk+'_cash')
                if b['action'] == 'notify':
                    p['message'] = st.text_input('표시할 메시지', p.get('message','전략 점검'), key=bk+'_message')
                    st.caption('앱 내 메시지입니다. 이메일·외부 알림은 전송하지 않습니다.')
        st.caption('특정 비중 설정의 잔여 금액은 나머지 종목의 현재 평가액 비율로 배분합니다.')
    st.subheader('3 · 규칙 요약 및 실제 계산 미리보기')
    sentences = []
    for i,c in enumerate(spec['conditions']):
        label = f"{c.get('ticker','후보')} {OPERATORS.get(c.get('op'), '조건 미선택')}"
        sentences.append((f"{c.get('connector','AND')} " if i else '') + label)
    st.info(' → '.join([' '.join(sentences), f"충족: {ACTIONS[spec['onPass']['action']]}", f"미충족: {ACTIONS[spec['onFail']['action']]}"]))
    result = evaluate(spec, sub, as_of, fetch)
    st.write(f"**{result['status']}** · {result['message']} · 다음 기준일: {result.get('next_run','—')}")
    if result['evidence']:
        st.dataframe(pd.DataFrame(result['evidence']).style.format({'현재값':'{:,.0f}','기준값':'{:,.0f}'}), hide_index=True, use_container_width=True)
    if result.get('ranking'):
        st.dataframe(pd.DataFrame(result['ranking']).style.format({'모멘텀':'{:.2%}'}), hide_index=True)
    preview = pd.DataFrame([{'티커':t,'현재평가액':v,'목표평가액':result['targets'][t], '예상매매액':result['targets'][t]-v}
                            for t,v in zip(sub['ticker'],sub['평가액'])])
    st.dataframe(preview, hide_index=True, use_container_width=True)
    version = st.text_input('적용할 버전', str(row.get('version','1.0')), key=key+'_version')
    note = st.text_input('변경 이유', key=key+'_note')
    if st.button('검토한 규칙 적용', type='primary', key=key+'_save', disabled=not spec['conditions']):
        updated = st.session_state.strategies.copy()
        mask = updated['code'].astype(str).eq(code)
        updated.loc[mask,'rule'] = 'visual'
        updated.loc[mask,'params_json'] = json.dumps(spec, ensure_ascii=False)
        updated.loc[mask,'version'] = version
        updated.loc[mask,'change_note'] = note
        updated.loc[mask,'effective_date'] = as_of.isoformat()
        st.session_state.strategies = updated
        st.session_state.pop('priced_holdings',None)
        st.success('세션에 적용했습니다. Data 화면에서 Strategies를 복사하여 시트에 저장하세요.')
        st.rerun()
