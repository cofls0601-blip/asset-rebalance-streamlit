"""Executable contract for the project.zip visual rule catalogue.

No brokerage writes. Unknown signals block both pass and fail actions.
Connectors evaluate left-to-right, matching the ordered condition cards.
"""
from datetime import date, timedelta
import math
import pandas as pd

OPERATORS = {
    'sma_above':'가격 > SMA', 'sma_below':'가격 < SMA',
    'ema_above':'가격 > EMA', 'ema_below':'가격 < EMA',
    'dd_below':'낙폭 ≤ 기준', 'dd_above':'낙폭 ≥ 기준',
    'mom_rank':'모멘텀 순위', 'price_above_abs':'가격 ≥ 기준',
    'price_below_abs':'가격 ≤ 기준', 'ticker_gt':'A 가격 ≥ B 가격 × 비율',
    'schedule':'일정 도래',
}
ACTIONS = {'hold_buy':'보유 유지', 'sell_all':'전량 현금화', 'move_all':'대상 종목으로 이동',
           'set_weight':'대상 비중 설정', 'buy_cash_pct':'현금 일부 매수',
           'restore':'목표비중 복원', 'trigger_only':'트리거 표시', 'notify':'메시지 표시'}
FREQUENCIES = {'daily':'매일', 'monthly':'매월 말일', 'quarterly':'분기 말일', 'yearly':'연말'}


def due(day, frequency):
    if frequency not in FREQUENCIES:
        raise ValueError('지원하지 않는 실행 주기')
    end = (pd.Timestamp(day) + pd.offsets.MonthEnd(0)).date() == day
    return frequency == 'daily' or (end and (frequency == 'monthly' or
           frequency == 'quarterly' and day.month in (3, 6, 9, 12) or
           frequency == 'yearly' and day.month == 12))


def next_run(day, frequency):
    for offset in range(1, 367):
        candidate = day + timedelta(days=offset)
        if due(candidate, frequency):
            return candidate
    raise ValueError('다음 실행일 계산 실패')


def evaluate(spec, holdings, day, fetch):
    """Return condition evidence AND capital-conserving targets in KRW."""
    current = dict(zip(holdings['ticker'].astype(str), holdings['평가액'].astype(float)))
    total = sum(current.values())
    result = {'status':'보유 유지', 'passed':None, 'winner':None, 'evidence':[],
              'targets':current.copy(), 'message':'', 'action':'hold_buy'}
    cache = {}
    def series(ticker):
        ticker = str(ticker).strip().upper()
        if ticker == '__WINNER__':
            ticker = result['winner']
        if not ticker:
            raise ValueError('모멘텀 1위 또는 티커가 없습니다')
        if ticker not in cache:
            if ticker == 'CASH':
                data = pd.Series([1.0], index=[pd.Timestamp(day)])
            else:
                data = fetch(ticker, 'KR' if ticker.isdigit() or ticker.endswith(('.KS','.KQ')) else 'US', day)
            data = pd.to_numeric(data, errors='coerce').dropna().sort_index()
            if not data.empty:
                data.index = pd.to_datetime(data.index).tz_localize(None)
                data = data[data.index.normalize() <= pd.Timestamp(day)]
            if data.empty or (data <= 0).any() or not all(math.isfinite(x) for x in data):
                raise ValueError(f'{ticker}: 유효한 가격 없음')
            if (pd.Timestamp(day) - data.index[-1].normalize()).days > 7:
                raise ValueError(f'{ticker}: 7일 초과 오래된 가격')
            cache[ticker] = data
        return cache[ticker]

    try:
        frequency = spec.get('scope', {}).get('run', 'monthly')
        result['next_run'] = next_run(day, frequency).isoformat()
        if not due(day, frequency):
            result.update(status='일정 대기', message=f'다음 기준일 {result["next_run"]}')
            return result
        flags = []
        for index, c in enumerate(spec.get('conditions', [])):
            op = c.get('op')
            value, threshold = None, None
            if op == 'schedule':
                cadence = c.get('frequency', c.get('every', c.get('run', frequency)))
                cadence = {'monthend':'monthly','quarterend':'quarterly','yearend':'yearly'}.get(cadence, cadence)
                passed = due(day, cadence)
                value, threshold = int(passed), 1
            elif op == 'mom_rank':
                tickers = c.get('tickers', [])
                if isinstance(tickers, str):
                    tickers = [t.strip().upper() for t in tickers.split(',') if t.strip()]
                if not tickers:
                    raise ValueError('모멘텀 후보를 입력하세요')
                months = int(c.get('months', 12))
                scores = {}
                for ticker in tickers:
                    monthly = series(ticker).resample('ME').last().dropna()
                    if months < 1 or len(monthly) <= months:
                        raise ValueError(f'{ticker}: 모멘텀 기간 부족')
                    scores[ticker] = float(monthly.iloc[-1] / monthly.iloc[-months-1] - 1)
                ranked = sorted(scores, key=lambda t: (-scores[t], t))
                result['winner'] = ranked[0]
                target = c.get('ticker') or ranked[0]
                if target == '__winner__':
                    target = ranked[0]
                value = ranked.index(target) + 1 if target in ranked else len(ranked) + 1
                threshold = int(c.get('rank', 1))
                if threshold < 1:
                    raise ValueError('순위는 1 이상이어야 합니다')
                passed = value <= threshold
                result['ranking'] = [{'티커':t, '모멘텀':scores[t]} for t in ranked]
            else:
                prices = series(c.get('ticker', ''))
                close = float(prices.iloc[-1])
                value = close
                if op in ('ema_above','ema_below'):
                    days = int(c.get('days',200))
                    if days < 1 or len(prices) < days:
                        raise ValueError('EMA 계산 기간 부족')
                    threshold = float(prices.ewm(span=days, adjust=False).mean().iloc[-1])
                    passed = close > threshold if op.endswith('above') else close < threshold
                elif op in ('sma_above','sma_below'):
                    months = int(c.get('months', 10))
                    monthly = prices.resample('ME').last().dropna()
                    if months < 1 or len(monthly) < months:
                        raise ValueError('이동평균 계산 기간 부족')
                    threshold = float(monthly.tail(months).mean())
                    passed = close > threshold if op.endswith('above') else close < threshold
                elif op in ('dd_below','dd_above'):
                    lookback = int(c.get('lookback',120))
                    if lookback < 1 or len(prices) < lookback:
                        raise ValueError('낙폭 계산 기간 부족')
                    value = float(close / prices.tail(lookback).max() - 1) * 100
                    threshold = float(c.get('pct',-10))
                    passed = value <= threshold if op == 'dd_below' else value >= threshold
                elif op in ('price_above_abs','price_below_abs'):
                    threshold = float(c.get('price', c.get('value',0)))
                    passed = close >= threshold if op == 'price_above_abs' else close <= threshold
                elif op == 'ticker_gt':
                    other = series(c.get('tickerB', c.get('compare_ticker','')))
                    aligned = pd.concat([prices, other], axis=1, join='inner').dropna()
                    if aligned.empty:
                        raise ValueError('두 티커의 공통 가격일 없음')
                    value = float(aligned.iloc[-1,0])
                    threshold = float(aligned.iloc[-1,1]) * float(c.get('pct',100)) / 100
                    passed = value >= threshold
                else:
                    raise ValueError(f'지원하지 않는 조건: {op}')
            connector = c.get('connector') or 'AND'
            if connector not in ('AND','OR'):
                raise ValueError('조건 연결은 AND 또는 OR여야 합니다')
            flags.append((bool(passed), connector))
            result['evidence'].append({'조건':index+1,'티커':c.get('ticker',''), '연산':OPERATORS[op],
                                       '현재값':value, '기준값':threshold, '판정':'충족' if passed else '미충족'})
        if not flags:
            raise ValueError('조건이 없습니다')
        passed = flags[0][0]
        for flag, connector in flags[1:]:
            passed = passed and flag if connector == 'AND' else passed or flag
        result['passed'] = passed
        branch = spec.get('onPass' if passed else 'onFail', {'action':'hold_buy'})
        action, p = branch.get('action','hold_buy'), branch.get('params',{})
        if action not in ACTIONS:
            raise ValueError('지원하지 않는 동작')
        target = str(p.get('ticker','')).strip().upper()
        if target == '__WINNER__':
            target = result['winner']
        targets = current.copy()
        if action in ('move_all','set_weight','buy_cash_pct') and target not in current:
            raise ValueError('동작 대상이 전략 구성 종목에 없습니다')
        if action == 'restore':
            weights = dict(zip(holdings['ticker'], holdings['target_pct'].astype(float)))
            if any(x < 0 or x > 100 for x in weights.values()) or abs(sum(weights.values())-100) > .01:
                raise ValueError('목표비중 합계는 100%여야 합니다')
            targets = {t: total*w/100 for t,w in weights.items()}
        elif action == 'sell_all':
            if 'CASH' not in current:
                raise ValueError('현금화에는 CASH 행이 필요합니다')
            targets = {t:total if t == 'CASH' else 0 for t in current}
        elif action == 'move_all':
            cash_pct = float(p.get('cashPct', 0))
            if not 0 <= cash_pct <= 100 or cash_pct and 'CASH' not in current:
                raise ValueError('현금 비중 또는 CASH 구성을 확인하세요')
            targets = {t:0.0 for t in current}
            targets[target] = total*(1-cash_pct/100)
            if 'CASH' in targets:
                targets['CASH'] += total*cash_pct/100
        elif action == 'set_weight':
            pct = float(p.get('pct',50))
            if not 0 <= pct <= 100:
                raise ValueError('비중은 0~100%여야 합니다')
            others = [t for t in current if t != target]
            if not others and pct != 100:
                raise ValueError('잔여 비중을 배분할 종목이 없습니다')
            remaining = sum(current[t] for t in others)
            targets[target] = total*pct/100
            for t in others:
                targets[t] = total*(1-pct/100)*(current[t]/remaining if remaining else 1/len(others))
        elif action == 'buy_cash_pct':
            pct = float(p.get('pct',50))
            if 'CASH' not in current or not 0 <= pct <= 100:
                raise ValueError('CASH 구성과 매수 비율을 확인하세요')
            buy = current['CASH']*pct/100
            targets['CASH'] -= buy
            targets[target] += buy
        if any(not math.isfinite(v) or v < -1e-7 for v in targets.values()) or abs(sum(targets.values())-total) > .01:
            raise ValueError('목표 금액 보존 검증 실패')
        result.update(targets=targets, action=action, status='조건 충족' if passed else '조건 미충족',
                      message=str(p.get('message') or ACTIONS[action]))
    except Exception as exc:
        result.update(status='계산 차단', passed=None, action='hold_buy', targets=current.copy(), message=str(exc))
    return result
