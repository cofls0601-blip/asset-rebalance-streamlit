"""Cash-flow aware estimates for irregular user-selected valuation dates."""
import math
import numpy as np
import pandas as pd
from streamlit_app.data import DataError
from streamlit_app.ledger import latest_snapshots


def validate_flows(flows):
    if flows.empty:
        return flows.copy()
    df=flows.copy()
    for c in ['date','amount']:
        if c not in df:
            raise DataError('입출금에 date와 amount 열이 필요합니다')
    df['date']=pd.to_datetime(df.date,errors='coerce')
    df['amount']=pd.to_numeric(df.amount,errors='coerce')
    if df.date.isna().any() or df.amount.isna().any() or not df.amount.map(math.isfinite).all():
        raise DataError('입출금 날짜·금액을 확인하세요')
    if 'kind' not in df:
        df['kind']='external'
    df['kind']=df['kind'].fillna('external')
    if not df.kind.isin(['external','transfer']).all():
        raise DataError('입출금 종류는 external 또는 transfer입니다')
    if df.kind.eq('transfer').any():
        transfer=df[df.kind.eq('transfer')]
        if 'transfer_id' not in transfer or transfer.transfer_id.fillna('').eq('').any():
            raise DataError('내부 이체는 연결 ID가 필요합니다')
        for _,g in transfer.groupby('transfer_id'):
            if len(g)!=2 or abs(g.amount.sum())>.01 or g.date.nunique()!=1 or 'strategy' not in g or g.strategy.nunique()!=2:
                raise DataError('내부 이체는 같은 날 두 계좌의 반대 금액으로 기록하세요')
    return df


def summarize(snapshots, cashflows, strategy=None):
    history=latest_snapshots(snapshots)
    if history.empty:
        return pd.DataFrame(), {'cagr':None,'mdd':None,'xirr':None,'total_return':None}
    flows=validate_flows(cashflows)
    if strategy:
        history=history[history.strategy.eq(strategy)]
        if not flows.empty:
            if flows.get('strategy',pd.Series('',index=flows.index)).fillna('').eq('').any():
                raise DataError('계좌 성과를 계산하려면 입출금의 strategy를 지정하세요')
            flows=flows[flows.get('strategy',pd.Series('',index=flows.index)).eq(strategy)]
    else:
        coverage=history.groupby('date').strategy.apply(lambda s:tuple(sorted(set(s))))
        if coverage.nunique()>1:
            raise DataError('날짜별 기록 계좌 구성이 다릅니다. 누락 계좌를 기록한 뒤 전체 성과를 확인하세요')
        if not flows.empty:flows=flows[flows.kind.eq('external')]
    history['date']=pd.to_datetime(history.date)
    equity=history.groupby('date',as_index=False).value.sum().sort_values('date')
    points=[]
    index=100.
    if equity.empty:
        return pd.DataFrame(), {'cagr':None,'mdd':None,'xirr':None,'total_return':None}
    for i,r in enumerate(equity.itertuples()):
        flow=profit=ret=0.
        if i:
            prev=equity.iloc[i-1];d0,d1=prev['date'],r.date
            cf=flows[(flows.date>d0)&(flows.date<=d1)] if not flows.empty else flows
            flow=float(cf.amount.sum()) if not cf.empty else 0.
            profit=r.value-float(prev.value)-flow
            days=(d1-d0).days
            weighted=float((((d1-cf.date).dt.total_seconds()/(days*86400))*cf.amount).sum()) if not cf.empty else 0.
            denominator=float(prev.value)+weighted
            ret=profit/denominator if denominator>0 else np.nan
            index=index*(1+ret) if pd.notna(ret) and index>0 else np.nan
        points.append({'date':r.date,'value':r.value,'net_flow':flow,'profit':profit,'return':ret,'index':index})
    result=pd.DataFrame(points)
    years=(result.date.iloc[-1]-result.date.iloc[0]).days/365.25
    valid=len(result)>1 and result['index'].notna().all() and (result['index']>0).all()
    growth=float(result['index'].iloc[-1]/100-1) if valid else None
    metrics={'total_return':growth,'cagr':float((1+growth)**(1/years)-1) if valid and years>0 else None,
             'mdd':float((result['index']/result['index'].cummax()-1).min()) if valid else None,
             'xirr':money_weighted(equity,flows) if len(equity)>1 else None}
    return result,metrics


def money_weighted(equity,flows):
    first,last=equity.iloc[0],equity.iloc[-1]
    start,end=first['date'],last['date']
    entries=[(start,-float(first.value)),(end,float(last.value))]
    if not flows.empty:
        entries += [(r.date,-float(r.amount)) for r in flows[(flows.date>start)&(flows.date<=end)].itertuples()]
    if not any(v<0 for _,v in entries) or not any(v>0 for _,v in entries):
        return None
    def npv(rate):
        return sum(v/(1+rate)**((d-start).days/365.25) for d,v in entries)
    grid=[-.9999,-.99,-.9,-.5,0.,.1,.5,1.,2.,10.,100.]
    brackets=[]
    for lo,hi in zip(grid,grid[1:]):
        if abs(npv(lo))<1e-8:
            return lo
        if npv(lo)*npv(hi)<0:
            brackets.append((lo,hi))
    if len(brackets)!=1:
        return None
    lo,hi=brackets[0]
    for _ in range(120):
        mid=(lo+hi)/2
        if npv(lo)*npv(mid)<=0:
            hi=mid
        else:
            lo=mid
    return (lo+hi)/2


def monthly_risk(equity, risk_free=0.):
    """Only annualize a regular monthly valuation grid with >=12 returns."""
    empty={'volatility':None,'sharpe':None,'sortino':None}
    if len(equity)<13:return empty
    dates=pd.DatetimeIndex(equity.date)
    regular=(dates.to_period('M').asi8[1:]-dates.to_period('M').asi8[:-1]==1).all()
    regular=regular and (len(set(dates.day))==1 or dates.is_month_end.all())
    values=pd.to_numeric(equity['return'].iloc[1:],errors='coerce')
    if not regular or values.isna().any():return empty
    excess=values-((1+risk_free)**(1/12)-1)
    deviation=float(values.std(ddof=1));downside=float(np.sqrt(np.mean(np.minimum(excess,0)**2)))
    return {'volatility':deviation*np.sqrt(12),
            'sharpe':float(excess.mean()/deviation*np.sqrt(12)) if deviation>1e-12 else None,
            'sortino':float(excess.mean()/downside*np.sqrt(12)) if downside>1e-12 else None}


def benchmark_index(ticker, dates, fetch):
    """Raw-price KRW comparator at the exact portfolio valuation dates."""
    from streamlit_app.engine import resolved_market
    from streamlit_app.market import expected_session, validate_series
    dates=pd.DatetimeIndex(dates).normalize()
    if dates.empty:raise DataError('비교할 평가일이 없습니다')
    market=resolved_market(ticker,'KR');last=dates.max().date()
    prices=validate_series(fetch(ticker,market,last,False),last,market)
    fx=fetch('KRW=X','US',last,False) if market=='US' else None
    if fx is not None:
        fx=fx.copy();fx.index=pd.to_datetime(fx.index).tz_localize(None).normalize()
        fx=pd.to_numeric(fx,errors='coerce').sort_index()
        if fx.index.duplicated().any():raise DataError('벤치마크 환율 관측일이 중복됩니다')
    values=[]
    for day in dates:
        session=expected_session(day.date(),market)
        if session not in prices.index:raise DataError('벤치마크 기간의 가격이 부족합니다. 분석 시작일을 조정하세요')
        rate=1.
        if fx is not None:
            available=fx[fx.index<=session].dropna()
            if available.empty or (session-available.index[-1]).days>3:raise DataError('벤치마크 환율이 부족합니다')
            rate=float(available.iloc[-1])
        value=float(prices.loc[session])*rate
        if not math.isfinite(value) or value<=0:raise DataError('벤치마크 가격·환율이 올바르지 않습니다')
        values.append(value)
    return pd.DataFrame({'date':dates,'benchmark':np.array(values)/values[0]*100})
