"""Exchange-aware, reproducible daily close observations (no order APIs)."""
from datetime import date, timedelta
from functools import lru_cache
import pandas as pd
import exchange_calendars as xcals


@lru_cache(maxsize=32)
def calendar(market, year):
    return xcals.get_calendar('XKRX' if market == 'KR' else 'XNYS',
                             start=f'{year-5}-01-01', end=f'{year+2}-12-31')


def expected_session(day: date, market: str):
    return calendar(market, day.year).date_to_session(pd.Timestamp(day), direction='previous')


def next_trade_day(day: date, market: str):
    return calendar(market, day.year).date_to_session(pd.Timestamp(day + timedelta(days=1)), direction='next').date()


def closed_session(day: date, market: str, now=None):
    cal = calendar(market, day.year)
    session = expected_session(day, market)
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize('UTC')
    if cal.session_close(session) + pd.Timedelta(minutes=20) > now:
        raise ValueError(f'{market}: {session.date()} 종가 확정 대기 (장 마감 후 20분)')
    return session


def validate_series(series, day, market, now=None, require_close=True):
    if series.empty:
        raise ValueError('유효한 종가가 없습니다')
    result = pd.to_numeric(series, errors='coerce').sort_index()
    result.index = pd.to_datetime(result.index).tz_localize(None).normalize()
    result = result[result.index <= pd.Timestamp(day)]
    if result.empty or result.isna().any() or not ((result > 0) & (result < float('inf'))).all():
        raise ValueError('가격이 누락되었거나 유한한 양수가 아닙니다')
    if result.index.duplicated().any():
        raise ValueError('가격일이 중복되었습니다')
    expected = closed_session(day, market, now) if require_close else expected_session(day, market)
    if result.index[-1].date() != expected.date():
        raise ValueError(f'가격 누락: 필요한 거래일 {expected.date()}, 실제 {result.index[-1].date()}')
    return result
