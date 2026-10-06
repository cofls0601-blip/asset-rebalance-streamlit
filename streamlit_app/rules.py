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
    'schedule':'일정 도래', 'weight_deviation':'목표 비중 괴리 ≥ %p',
    'external_above':'수동 지표 ≥ 기준',
    'momentum_above':'기간 수익률 ≥ 기준',
}
ACTIONS = {'hold_buy':'보유 유지', 'sell_all':'전량 현금화', 'move_all':'대상 종목으로 이동',
           'set_weight':'대상 비중 설정', 'buy_cash_pct':'현금 일부 매수',
           'restore':'목표비중 복원', 'restore_scope':'지정 자산 목표 복원',
           'switch_scope':'지정 자산을 대체 자산으로 전환', 'buy_to_weight':'현금으로 목표 비중까지 매수', 'trigger_only':'트리거 표시', 'notify':'메시지 표시'}
FREQUENCIES = {'daily':'매일', 'monthly':'매월 지정일', 'quarterly':'3·6·9·12월 지정일', 'yearly':'12월 지정일', 'manual':'수동', 'months':'지정 월'}


def due(day, frequency, months=None):
    if frequency not in FREQUENCIES:
        raise ValueError('지원하지 않는 실행 주기')
    if frequency == 'months':
        if isinstance(months,str):
            months = [m.strip() for m in months.split(',') if m.strip()]
        if not months or any(not 1 <= int(m) <= 12 for m in months):
            raise ValueError('실행 월을 1~12에서 선택하세요')
        return day.month in [int(m) for m in months]
    return frequency in ('daily', 'monthly', 'manual') or (
        frequency == 'quarterly' and day.month in (3, 6, 9, 12)) or (
        frequency == 'yearly' and day.month == 12)


def next_run(day, frequency, months=None):
    for offset in range(1, 367):
        candidate = day + timedelta(days=offset)
        if due(candidate, frequency, months):
            return candidate
    raise ValueError('다음 실행 가능일 계산 실패')


def evaluate(spec, holdings, day, fetch):
    """Return condition evidence AND capital-conserving targets in KRW."""
    current = dict(zip(holdings['ticker'].astype(str), holdings['평가액'].astype(float)))
    total = sum(current.values())
    result = {'status':'보유 유지', 'passed':None, 'winner':None, 'evidence':[],
              'targets':current.copy(), 'message':'', 'action':'hold_buy'}
    cache = {}
    used = set()
    def month_values(prices):
        monthly = prices.resample('ME').last().dropna()
        if spec.get('completed_months_only', False):
            monthly = monthly[monthly.index < pd.Timestamp(day).replace(day=1)]
        return monthly
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
        used.add(ticker)
        return cache[ticker]

    def evaluate_branch(conditions, branch_no):
        # Evaluate one branch's AND/OR condition chain; append evidence rows (with
        # group label branch_no) to result in place; return whether the branch passed.
        nonlocal used
        flags = []
        for index, c in enumerate(conditions):
            used=set()
            op = c.get('op')
            value, threshold = None, None
            if op == 'weight_deviation':
                target_ticker = str(c.get('ticker','')).strip().upper()
                selected = holdings[holdings.ticker.astype(str).eq(target_ticker)]
                if selected.empty or total <= 0:
                    raise ValueError('비중 괴리 대상 또는 평가액이 없습니다')
                value = abs(float(selected['평가액'].sum())/total*100-float(selected.target_pct.sum()))
                threshold = float(c.get('pct',0))
                passed = value >= threshold
            elif op == 'external_above':
                if not c.get('source') or not c.get('observed_date') or not c.get('published_date'):
                    raise ValueError('수동 지표의 출처·관측일·발표일이 필요합니다')
                observed, published = pd.Timestamp(c['observed_date']), pd.Timestamp(c['published_date'])
                if pd.isna(observed) or pd.isna(published) or observed.date() > published.date():
                    raise ValueError('지표 관측일·발표일 순서를 확인하세요')
                if published.date() > day:
                    raise ValueError('기준일 이후 발표된 지표입니다')
                value, threshold = float(c['value']), float(c.get('threshold',0))
                if not math.isfinite(value) or not math.isfinite(threshold):
                    raise ValueError('수동 지표값은 유한한 숫자여야 합니다')
                passed = value >= threshold
            elif op == 'schedule':
                cadence = c.get('frequency', c.get('every', c.get('run', frequency)))
                cadence = {'monthend':'monthly','quarterend':'quarterly','yearend':'yearly'}.get(cadence, cadence)
                passed = due(day, cadence, c.get('months_list'))
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
                    monthly = month_values(series(ticker))
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
                elif op == 'momentum_above':
                    months=int(c.get('months',12))
                    monthly=month_values(prices)
                    if months < 1 or len(monthly)<=months:raise ValueError('모멘텀 계산 기간 부족')
                    value=float(monthly.iloc[-1]/monthly.iloc[-months-1]-1)*100
                    threshold=float(c.get('pct',0))
                    passed=value>=threshold
                elif op in ('sma_above','sma_below'):
                    months = int(c.get('months', 10))
                    monthly = month_values(prices)
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
            dates=', '.join(t+': '+str(cache[t].index[-1].date()) for t in sorted(used))
            result['evidence'].append({'그룹':branch_no,'조건':index+1,'티커':c.get('ticker',''), '연산':OPERATORS[op],
                                       '현재값':value, '기준값':threshold, '판정':'충족' if passed else '미충족',
                                       '사용일':dates or str(c.get('observed_date',day)),
                                       '발표일':c.get('published_date',''),'출처':c.get('source','시계열' if used else '입력값'),
                                       '신호조정':'수정종가' if spec.get('signal_adjusted') else '비수정',
                                       '기간':c.get('months',c.get('days',c.get('lookback','')))})
        if not flags:
            raise ValueError(f'{branch_no}번 조건 그룹에 조건이 없습니다')
        branch_passed = flags[0][0]
        for flag, connector in flags[1:]:
            branch_passed = branch_passed and flag if connector == 'AND' else branch_passed or flag
        return branch_passed

    try:
        frequency = spec.get('scope', {}).get('run', 'monthly')
        result['next_run'] = next_run(day, frequency, spec.get('scope', {}).get('months')).isoformat()
        if not due(day, frequency, spec.get('scope', {}).get('months')):
            result.update(status='일정 대기', message=f'다음 기준일 {result["next_run"]}')
            return result

        # schema_version 4: 서로 담당 종목이 겹치지 않는 완전히 독립적인 규칙들.
        # 각 규칙은 자신의 scope(담당 종목) 안에서만 then/else 동작을 적용하고,
        # 다른 규칙의 scope에는 손대지 않는다. scope에 포함되지 않은 종목은 그대로 유지된다.
        if spec.get('rules') is not None:
            return _evaluate_independent_rules(spec, holdings, day, current, total, result, evaluate_branch)

        # schema_version 2(단일 조건 그룹: conditions/onPass/onFail)는 branches가 하나뿐인
        # schema_version 3 형태로 간주해 평가한다 — 기존에 저장된 전략을 다시 저장하지
        # 않아도 계속 동작하게 하기 위함이다.
        branches = spec.get('branches')
        if branches is None:
            branches = [{'conditions': spec.get('conditions', []), 'action': spec.get('onPass', {'action': 'hold_buy'})}]
            default_action = spec.get('onFail', {'action': 'hold_buy'})
        else:
            if not branches:
                raise ValueError('조건 그룹이 없습니다')
            default_action = spec.get('default_action', {'action': 'hold_buy'})

        matched_branch = None
        for branch_no, branch in enumerate(branches, start=1):
            if evaluate_branch(branch.get('conditions', []), branch_no):
                matched_branch = branch
                result['matched_branch'] = branch_no
                break
        result['passed'] = matched_branch is not None
        branch_action = matched_branch['action'] if matched_branch else default_action
        action, p = branch_action.get('action','hold_buy'), branch_action.get('params',{})
        restore_wait = _restore_due_check(action, p, day)
        if restore_wait:
            result.update(status='일정 대기', message=restore_wait)
            return result
        targets = _apply_action(action, p, current, total, holdings, result)
        result.update(targets=targets, action=action, status='조건 충족' if matched_branch else '조건 미충족',
                      message=str(p.get('message') or ACTIONS[action]))
    except Exception as exc:
        result.update(status='계산 차단', passed=None, action='hold_buy', targets=current.copy(), message=str(exc))
    return result


def _restore_due_check(action, p, day):
    # Return a wait-message if a restore-type action's own cadence hasn't arrived yet, else None.
    if action in ('restore', 'restore_scope') and not due(day, p.get('restore_frequency', 'monthly'), p.get('restore_months')):
        return '조건은 판정했지만 목표 복원 주기가 아닙니다'
    return None


def _apply_action(action, p, current, total, holdings, result):
    # Apply one action's effect to a (possibly scoped) current/total/holdings universe.
    # Used both for the single whole-portfolio decision (legacy/branches modes) and,
    # with a ticker-scoped current/total/holdings, for each independent rule in the
    # 'rules' (parallel) mode — so every action keeps exactly the same validation and
    # capital-conservation guarantees regardless of which mode calls it.
    if action not in ACTIONS:
        raise ValueError('지원하지 않는 동작')
    target = str(p.get('ticker', '')).strip().upper()
    if target == '__WINNER__':
        target = result['winner']
    targets = current.copy()
    if action in ('move_all', 'set_weight', 'buy_cash_pct') and target not in current:
        raise ValueError('동작 대상이 전략 구성 종목에 없습니다')
    if action in ('restore_scope', 'switch_scope'):
        tickers = p.get('tickers', [])
        if p.get('role'):
            tickers = holdings.loc[holdings['role'].eq(p['role']), 'ticker'].tolist()
        if not tickers or any(t not in current or t == 'CASH' for t in tickers):
            raise ValueError('전환/복원할 종목 또는 역할을 선택하세요')
        if action == 'switch_scope':
            if target not in current or target in tickers:
                raise ValueError('별도의 대체 대상이 필요합니다')
            amount = sum(current[t] for t in tickers)
            for t in tickers: targets[t] = 0.
            targets[target] += amount
        else:
            if 'CASH' not in current:
                raise ValueError('지정 자산 복원에는 CASH 행이 필요합니다')
            for t in tickers:
                targets[t] = total * float(holdings.loc[holdings.ticker.eq(t), 'target_pct'].sum()) / 100
            targets['CASH'] = total - sum(v for t, v in targets.items() if t != 'CASH')
    elif action == 'buy_to_weight':
        pct = float(p.get('pct', 50))
        if target not in current or target == 'CASH' or 'CASH' not in current or not 0 <= pct <= 100:
            raise ValueError('매수 대상·비율·CASH 구성을 확인하세요')
        amount = min(current['CASH'], max(0., total * pct / 100 - current[target]))
        targets[target] += amount
        targets['CASH'] -= amount
    elif action == 'restore':
        weights = dict(zip(holdings['ticker'], holdings['target_pct'].astype(float)))
        if any(x < 0 or x > 100 for x in weights.values()) or abs(sum(weights.values()) - 100) > .01:
            raise ValueError('목표비중 합계는 100%여야 합니다')
        targets = {t: total * w / 100 for t, w in weights.items()}
    elif action == 'sell_all':
        if 'CASH' not in current:
            raise ValueError('현금화에는 CASH 행이 필요합니다')
        targets = {t: total if t == 'CASH' else 0 for t in current}
    elif action == 'move_all':
        cash_pct = float(p.get('cashPct', 0))
        if not 0 <= cash_pct <= 100 or cash_pct and 'CASH' not in current:
            raise ValueError('현금 비중 또는 CASH 구성을 확인하세요')
        targets = {t: 0.0 for t in current}
        targets[target] = total * (1 - cash_pct / 100)
        if 'CASH' in targets:
            targets['CASH'] += total * cash_pct / 100
    elif action == 'set_weight':
        pct = float(p.get('pct', 50))
        if not 0 <= pct <= 100:
            raise ValueError('비중은 0~100%여야 합니다')
        others = [t for t in current if t != target]
        if not others and pct != 100:
            raise ValueError('잔여 비중을 배분할 종목이 없습니다')
        remaining = sum(current[t] for t in others)
        targets[target] = total * pct / 100
        for t in others:
            targets[t] = total * (1 - pct / 100) * (current[t] / remaining if remaining else 1 / len(others))
    elif action == 'buy_cash_pct':
        pct = float(p.get('pct', 50))
        if 'CASH' not in current or not 0 <= pct <= 100:
            raise ValueError('CASH 구성과 매수 비율을 확인하세요')
        buy = current['CASH'] * pct / 100
        targets['CASH'] -= buy
        targets[target] += buy
    if any(not math.isfinite(v) or v < -1e-7 for v in targets.values()) or abs(sum(targets.values()) - total) > .01:
        raise ValueError('목표 금액 보존 검증 실패')
    return targets


def _evaluate_independent_rules(spec, holdings, day, current, total, result, evaluate_branch):
    # 서로 담당 종목(scope)이 겹치지 않는 독립 규칙들을 각각 평가해 동시에 적용한다.
    # scope로 지정되지 않은 종목은 손대지 않고 현재 값 그대로 둔다.
    rules = spec.get('rules')
    if not rules:
        raise ValueError('독립 규칙이 없습니다')
    targets = current.copy()
    covered = set()
    outcomes = []
    for rule_no, rule in enumerate(rules, start=1):
        name = rule.get('name') or f'규칙 {rule_no}'
        scope = rule.get('scope') or []
        if not scope:
            raise ValueError(f'{name}: 담당 종목(scope)을 지정하세요')
        missing = [t for t in scope if t not in current]
        if missing:
            raise ValueError(f'{name}: 담당 종목 중 전략 구성에 없는 종목이 있습니다 ({", ".join(missing)})')
        overlap = covered & set(scope)
        if overlap:
            raise ValueError(f'{name}: 다른 규칙과 담당 종목이 겹칩니다 ({", ".join(sorted(overlap))})')
        covered |= set(scope)

        passed = evaluate_branch(rule.get('conditions', []), rule_no)
        chosen = (rule.get('then') if passed else rule.get('else')) or {'action': 'hold_buy', 'params': {}}
        action, p = chosen.get('action', 'hold_buy'), chosen.get('params', {})
        restore_wait = _restore_due_check(action, p, day)
        if restore_wait:
            raise ValueError(f'{name}: {restore_wait}')

        scope_current = {t: current[t] for t in scope}
        scope_total = sum(scope_current.values())
        scope_holdings = holdings[holdings['ticker'].astype(str).isin(scope)]
        scope_targets = _apply_action(action, p, scope_current, scope_total, scope_holdings, result)
        targets.update(scope_targets)
        outcomes.append({'그룹': rule_no, '이름': name, '판정': '충족' if passed else '미충족', '동작': ACTIONS.get(action, action)})

    if any(not math.isfinite(v) or v < -1e-7 for v in targets.values()) or abs(sum(targets.values()) - total) > .01:
        raise ValueError('목표 금액 보존 검증 실패')

    result['rules'] = outcomes
    result['passed'] = True
    result['action'] = 'multiple'
    result['status'] = '조건 판정 완료'
    result['message'] = ' · '.join(f"{o['이름']}: {o['동작']}" for o in outcomes)
    result['targets'] = targets
    return result
