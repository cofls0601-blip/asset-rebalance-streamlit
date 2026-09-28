"""Monthly workflow with account isolation and cash-constrained manual proposals."""
from datetime import date
import hashlib
import json
import math
import numpy as np
import pandas as pd
from streamlit_app import engine
from streamlit_app.data import DataError, normalize_holdings, normalize_strategies
from streamlit_app.market import validate_series, next_trade_day
from streamlit_app.rules import due, evaluate

ENGINE_VERSION = '0.3.0'


def stable_id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False).encode()).hexdigest()[:24]


def records(frame):
    return json.loads(frame.to_json(orient='records', date_format='iso', force_ascii=False))


def quantify(target_plan, view, strategy):
    """Sell quantities do not increase the buy budget; never overspend starting CASH."""
    plan = target_plan.copy()
    reserve = float(strategy.get('cash_reserve', 0) or 0)
    tolerance = float(strategy.get('tolerance_pct', 0) or 0)
    fraction = str(strategy.get('fractional_us', False)).lower() in ('true', '1')
    total = float(view['평가액'].sum())
    cash = float(view.loc[view.ticker.eq('CASH'), '평가액'].sum())
    budget = max(0.0, cash - reserve)
    desired = []
    for row in plan.to_dict('records'):
        holding = view.loc[view.ticker.eq(row['티커'])].iloc[0]
        unit = float(holding.close * holding.fx)
        difference = float(row['목표평가액'] - holding['평가액'])
        target_pct = float(row['목표평가액'] / total * 100) if total else 0.0
        gap = target_pct - (float(holding['평가액']) / total * 100 if total else 0.0)
        lot = .0001 if engine.resolved_market(holding.ticker, holding.market) == 'US' and fraction else 1.0
        quantity = 0.0
        if holding.ticker != 'CASH' and unit > 0 and abs(gap) > tolerance + 1e-10:
            quantity = math.copysign(math.floor(abs(difference) / unit / lot + 1e-10) * lot, difference)
            quantity = max(quantity, -math.floor(float(holding.shares)/lot+1e-10)*lot)
        row.update({'목표조정액': difference, '기본목표(%)': float(holding.target_pct),
                    '실행목표(%)': target_pct, '현재비중(%)': float(holding['현재비중']),
                    '기준종가': float(holding.close), '환율': float(holding.fx),
                    '보유수량': float(holding.shares), '단위금액': unit, '거래단위': lot,
                    '제안수량': quantity, '현금제약': False})
        desired.append(row)
    # Deterministic priority: largest underweight first, ticker as tie-breaker.
    for row in sorted(desired, key=lambda r: (-r['목표조정액'], r['티커'])):
        q = row['제안수량']
        if q > 0:
            affordable = math.floor((budget + 1e-8) / row['단위금액'] / row['거래단위']) * row['거래단위']
            allowed = max(0.0, min(q, affordable))
            row['현금제약'] = allowed < q - 1e-9
            row['제안수량'] = allowed
            budget -= allowed * row['단위금액']
    movement = 0.0
    for row in desired:
        amount = row['제안수량'] * row['단위금액']
        row['예상매매액'] = amount
        row['구분'] = '매수' if amount > 0 else '매도' if amount < 0 else '유지'
        row['실행후수량'] = row['보유수량'] + row['제안수량']
        movement += amount
        if row['현금제약']:
            row['근거'] += ' · 기존 CASH 부족으로 매수 축소'
    final_cash = cash - movement
    for row in desired:
        expected = final_cash if row['티커'] == 'CASH' else row['실행후수량'] * row['단위금액']
        row['실행후비중(%)'] = expected / total * 100 if total else 0.0
        row['예상잔여현금'] = final_cash
    return pd.DataFrame(desired)


def run_evaluation(holdings, strategies, as_of, fetch=None, now=None, overrides=None, manual_codes=None):
    """Freeze valid account results; failures in one account never block others."""
    fetch = fetch or engine._series
    fetched_at = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    views, plans, decisions, errors, observations = [], [], [], {}, []
    strategies = normalize_strategies(strategies)
    manual_codes=set(map(str,manual_codes or []))
    all_codes = list(dict.fromkeys(holdings.strategy.astype(str).tolist()))
    cache = {}
    def source(ticker, market, adjusted=False):
        key = (ticker, market, adjusted)
        if key not in cache:
            prices = validate_series(fetch(ticker, market, as_of, adjusted), as_of, market, now)
            cache[key] = prices
            observations.append({'ticker': ticker, 'market': market, 'adjusted': adjusted,
                                 'dates': [d.date().isoformat() for d in prices.index], 'values': prices.tolist()})
        return cache[key]
    for code in all_codes:
        try:
            config = strategies.loc[strategies.code.astype(str).eq(code)]
            if config.empty:
                raise DataError('전략 규칙이 없습니다')
            row = config.iloc[0].to_dict()
            if not row['active']:
                config=config.copy();config.loc[:,'rule']='hold';row['rule']='hold'
            h = normalize_holdings(holdings.loc[holdings.strategy.astype(str).eq(code)])
            if 'CASH' not in set(h.ticker):
                raise DataError('현금 잔액 0이라도 CASH 행을 추가하세요')
            params = json.loads(row['params_json'] or '{}')
            warnings = engine.validate_configuration(h, config)
            if warnings:
                raise DataError(' / '.join(warnings))
            adjusted = bool(params.get('signal_adjusted', False))
            priced = h.copy()
            for idx, asset in h.iterrows():
                t = asset.ticker
                market = engine.resolved_market(t, asset.market)
                override = (overrides or {}).get(f'{code}:{t}')
                if t == 'CASH':
                    close, fx, actual, fx_date, signal_close = 1., 1., as_of, as_of, 1.
                    series = pd.Series(dtype=float)
                    provenance = 'CASH 고정값'
                else:
                    if override:
                        if not override.get('source') or not override.get('reason'):
                            raise DataError('수동 가격에는 출처와 사유가 필요합니다')
                        actual = date.fromisoformat(override['date'])
                        if actual > as_of:
                            raise DataError('미래 수동 가격은 사용할 수 없습니다')
                        from streamlit_app.market import closed_session
                        if actual != closed_session(as_of, market, now).date():
                            raise DataError('수동 가격일이 요청한 거래일과 다릅니다')
                        close = float(override['close'])
                        if not math.isfinite(close) or close <= 0:
                            raise DataError('수동 종가는 유한한 양수여야 합니다')
                        provenance = f"수동 · {override['source']} · {override['reason']}"
                        try:
                            series = source(t, market, adjusted)
                        except Exception:
                            series = pd.Series(dtype=float)
                    else:
                        raw = source(t, market, False)
                        close, actual = float(raw.iloc[-1]), raw.index[-1].date()
                        series = source(t, market, True) if adjusted else raw
                        provenance = 'Yahoo Finance'
                    signal_close = float(series.iloc[-1]) if not series.empty else np.nan
                    if market == 'US':
                        # FX is daily rather than an exchange close; insist on as-of freshness.
                        if 'FX' not in cache:
                            f = fetch('KRW=X', 'US', as_of, False).copy()
                            f.index = pd.to_datetime(f.index).tz_localize(None).normalize()
                            f=pd.to_numeric(f,errors='coerce').sort_index()
                            if f.index.duplicated().any():raise DataError('환율 관측일이 중복됩니다')
                            cutoff=pd.Timestamp(as_of).tz_localize('America/New_York')+pd.Timedelta(hours=17,minutes=20)
                            ceiling=pd.Timestamp(as_of) if fetched_at>=cutoff else pd.Timestamp(as_of)-pd.Timedelta(days=1)
                            f = f[f.index <= ceiling].dropna()
                            cache['FX']=f
                            observations.append({'ticker':'KRW=X','market':'FX','adjusted':False,'source':'Yahoo Finance',
                                'dates':[d.date().isoformat() for d in f.index],'values':f.tolist()})
                        f=cache['FX']
                        if f.empty or not math.isfinite(float(f.iloc[-1])) or float(f.iloc[-1]) <= 0 or (as_of - f.index[-1].date()).days > 3:
                            raise DataError('유효한 기준일 환율이 없습니다')
                        fx, fx_date = float(f.iloc[-1]), f.index[-1].date()
                    else:
                        fx, fx_date = 1., actual
                months = series.resample('ME').last().dropna() if not series.empty else series
                if params.get('completed_months_only', False) and not months.empty:
                    months = months[months.index < pd.Timestamp(as_of).replace(day=1)]
                n = int(params.get('sma_months', 10))
                priced.loc[idx, ['close','fx','signal_close','sma_period']] = [close, fx, signal_close, n]
                priced.loc[idx, 'sma10'] = float(months.tail(n).mean()) if n > 0 and len(months) >= n else np.nan
                priced.loc[idx, 'momentum12'] = float(months.iloc[-1] / months.iloc[-13] - 1) if len(months) >= 13 else np.nan
                priced.loc[idx, 'drawdown120'] = float(series.iloc[-1] / series.tail(120).max() - 1) if len(series) >= 120 else np.nan
                for k,v in {'price_date':str(actual),'fx_date':str(fx_date),'price_status':'확정',
                            'price_source':provenance, 'requested_date':str(as_of),'fetched_at':fetched_at.isoformat(),
                            'signal_adjusted':adjusted,'currency':'USD' if market=='US' else 'KRW'}.items():
                    priced.loc[idx,k] = v
                priced.loc[idx,'fx_source']='Yahoo Finance' if market=='US' else 'KRW 고정값'
            view = engine.portfolio_view(priced)
            # Every signal fetch is validated too, including instruments not held.
            def signals(t, m, d):
                return source(t, engine.resolved_market(t,m), adjusted)
            rule = row['rule']
            if rule not in {'static','hold','sma_filter_rebalance','momentum_rotate','drawdown_buy','drawdown_shift','visual'}:
                raise DataError('지원하지 않는 전략 규칙입니다: '+str(rule))
            if rule == 'visual' and params.get('schema_version') != 2:
                raise DataError('이전 시각 규칙은 전략실에서 검토 후 schema_version 2로 적용하세요')
            if rule == 'sma_filter_rebalance':
                required = view[view.ticker.isin(params.get('sma_tickers',[]))]
                if required.sma10.isna().any():
                    raise DataError('SMA 계산 시계열이 부족합니다')
            cadence = params.get('scope', {}).get('run', params.get('frequency','monthly'))
            allowed = code in manual_codes if cadence == 'manual' else due(as_of, cadence, params.get('scope',{}).get('months',params.get('months')))
            decision = {'status':'일정 대기','message':'지정일이 실행 대상 월이 아닙니다','evidence':[]}
            if rule == 'visual' and params.get('schema_version') == 2:
                decision = evaluate(params, view, as_of, signals)
                if decision['status'] == '계산 차단':
                    raise DataError(decision['message'])
            elif allowed:
                if rule == 'momentum_rotate' and view.loc[view.ticker.ne('CASH'), ['sma10','momentum12']].isna().any().any():
                    raise DataError('모멘텀 후보의 시계열이 부족합니다')
                decision = {'status':'판정 완료','message':rule,'evidence':[]}
                if not row['active']:decision.update(status='비활성',message='보유 평가만 수행 · 주문 없음')
            # Legacy engines use the injected, validated signal function as well.
            if not allowed and rule != 'sma_filter_rebalance':
                c = config.copy();c.loc[:,'rule'] = 'hold'
            else:
                c = config
            plan = engine.build_action_plan(view, c, as_of, signal_fetch=signals)
            plan = quantify(plan, view, row)
            plan['주문예정일'] = plan['티커'].map(lambda t: '' if t == 'CASH' else str(next_trade_day(as_of, engine.resolved_market(t, 'KR'))))
            views.append(view);plans.append(plan)
            decisions.append({'strategy':code, **decision})
        except Exception as exc:
            errors[code] = str(exc)
    view = pd.concat(views,ignore_index=True) if views else pd.DataFrame()
    plan = pd.concat(plans,ignore_index=True) if plans else pd.DataFrame()
    if not view.empty:
        view['전체비중'] = view['평가액'] / view['평가액'].sum() * 100 if view['평가액'].sum() else 0.
    run_id = stable_id({'date':str(as_of),'holdings':records(holdings),'strategies':records(strategies),
                        'prices':records(view.drop(columns=['fetched_at'],errors='ignore')),
                        'observations':observations,'plan':records(plan),'engine':ENGINE_VERSION})
    if not plan.empty:
        plan['주문ID'] = plan.apply(lambda r: stable_id([run_id,r['전략'],r['티커']]),axis=1)
    return {'id':run_id,'date':str(as_of),'engine_version':ENGINE_VERSION,'view':view,'plan':plan,
            'decisions':decisions,'errors':errors,'holdings':holdings.copy(),'strategies':strategies.copy(),
            'observations':observations,'created_at':fetched_at.isoformat()}


def revise_proposal(run, edited, reason):
    """Explicit revision of signed quantities; recalculate amounts and cash atomically."""
    if not reason.strip():
        raise DataError('주문안 수정 사유를 입력하세요')
    plan=run['plan'].copy()
    if len(edited)!=len(plan) or list(edited['주문ID'])!=list(plan['주문ID']):
        raise DataError('주문 행을 추가하거나 제거할 수 없습니다')
    for idx,r in edited.iterrows():
        qty=float(r['제안수량']);p=plan.loc[idx]
        if not math.isfinite(qty):raise DataError('수량은 유한한 숫자여야 합니다')
        if p['티커']=='CASH' and qty!=0:raise DataError('CASH는 주문 종목이 아닙니다')
        if abs(qty/p['거래단위']-round(qty/p['거래단위']))>1e-6:raise DataError('거래 단위에 맞는 수량을 입력하세요')
        if qty < -p['보유수량']-1e-8:raise DataError('보유수량 초과 매도입니다')
        plan.loc[idx,'제안수량']=qty
        plan.loc[idx,'예상매매액']=qty*p['단위금액']
        plan.loc[idx,'구분']='매수' if qty>0 else '매도' if qty<0 else '유지'
        plan.loc[idx,'실행후수량']=p['보유수량']+qty
        plan.loc[idx,'근거']=str(p['근거'])+' · 사용자 수정: '+reason
    for code,g in plan.groupby('전략'):
        v=run['view'][run['view'].strategy.eq(code)]
        cash=float(v.loc[v.ticker.eq('CASH'),'평가액'].sum())
        reserve=float(run['strategies'].loc[run['strategies'].code.eq(code),'cash_reserve'].iloc[0])
        if g.loc[g['예상매매액']>0,'예상매매액'].sum()>max(0.,cash-reserve)+1e-8:
            raise DataError(code+': 기존 CASH 한도를 초과합니다')
        final_cash=cash-g['예상매매액'].sum();total=v['평가액'].sum()
        plan.loc[g.index,'예상잔여현금']=final_cash
        for idx,r in g.iterrows():
            value=final_cash if r['티커']=='CASH' else r['실행후수량']*r['단위금액']
            plan.loc[idx,'실행후비중(%)']=value/total*100 if total else 0.
    updated={**run,'plan':plan,'original_plan':run.get('original_plan',run['plan']).copy(),'revision_reason':reason}
    updated['id']=stable_id([run['id'],records(edited),reason])
    plan['주문ID']=plan.apply(lambda r:stable_id([updated['id'],r['전략'],r['티커']]),axis=1)
    return updated


def classification_view(view):
    rows=[]
    for r in view.to_dict('records'):
        mapping=json.loads(r.get('classification_json') or '{}') if pd.notna(r.get('classification_json','')) else {}
        if not mapping:mapping={r['category']:100.}
        for category,pct in mapping.items():
            rows.append({**r,'category':category,'평가액':r['평가액']*float(pct)/100})
    return pd.DataFrame(rows)
