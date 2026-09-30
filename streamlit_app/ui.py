"""Shared presentation helpers; formatting never changes stored numeric values."""
import pandas as pd
import streamlit as st


MONEY_COLUMNS = {
    '평가액', '현재평가액', '목표평가액', '목표조정액', '예상매매액', '예상잔여현금',
    '실제체결금액', '지난달평가액', '증감액', 'value', 'amount', 'net_flow', 'profit',
    'planned_amount', 'actual_amount', 'cash_reserve', '현재값', '기준값',
}
PRICE_COLUMNS = {'close', '기준종가', '실제단가', 'actual_price', 'fx', '환율', '실제환율', 'price'}
QUANTITY_COLUMNS = {
    'shares', '보유수량', '제안수량', '실제수량', 'planned_shares', 'actual_shares',
    '누적체결', '잔여수량',
}
PERCENT_COLUMNS = {
    'target_pct', 'weight_pct', 'account_weight_pct', 'execution_target_pct',
    '비중(%)', '현재비중', '현재비중(%)', '기본목표(%)', '실행목표(%)', '실행후비중(%)',
    '목표대비괴리(%p)', '괴리(%p)', '허용괴리(%p)', '증감률(%)',
}

TARGET_STATUS_STYLES = {
    '미달': ('#143047', '#9bd6ff'),
    '충족': ('#17382c', '#a0e3b8'),
    '초과': ('#422824', '#ffb8ad'),
}


def numeric_column_config(columns, overrides=None):
    """Return Streamlit column formats with thousands separators."""
    config = {}
    for column in columns:
        if column in MONEY_COLUMNS:
            config[column] = st.column_config.NumberColumn(format='%,.0f')
        elif column in PRICE_COLUMNS:
            config[column] = st.column_config.NumberColumn(format='%,.0f')
        elif column in QUANTITY_COLUMNS:
            config[column] = st.column_config.NumberColumn(format='%,.4f')
        elif column in PERCENT_COLUMNS:
            config[column] = st.column_config.NumberColumn(format='%.2f')
    config.update(overrides or {})
    return config


def prefer_asset_names(frame, holdings, ticker_column='티커', name_column='종목'):
    """Add/fill the asset name and place it immediately before the ticker."""
    result = frame.copy()
    if ticker_column not in result.columns:
        return result
    lookup = (holdings[['ticker', 'name']].dropna().drop_duplicates('ticker')
              .set_index('ticker')['name'].astype(str).to_dict())
    names = result[ticker_column].astype(str).map(lookup).fillna(result[ticker_column].astype(str))
    if name_column in result.columns:
        existing = result[name_column].fillna('').astype(str)
        result[name_column] = existing.where(existing.str.strip().ne(''), names)
    else:
        result.insert(result.columns.get_loc(ticker_column), name_column, names)
    columns = [column for column in result.columns if column not in {name_column, ticker_column}]
    insert_at = min(result.columns.get_loc(name_column), result.columns.get_loc(ticker_column))
    columns[insert_at:insert_at] = [name_column, ticker_column]
    return result[columns]


def allocation_status_frame(plan, strategies):
    """Classify current weight versus the execution target using each strategy's tolerance."""
    result = plan.copy()
    if result.empty:
        for column in ['괴리(%p)', '허용괴리(%p)', '목표상태']:
            result[column] = pd.Series(dtype=float if column != '목표상태' else str)
        return result
    tolerance = (strategies[['code', 'tolerance_pct']].copy()
                 .assign(tolerance_pct=lambda frame: pd.to_numeric(frame['tolerance_pct'], errors='coerce').fillna(0.0))
                 .drop_duplicates('code').set_index('code')['tolerance_pct'].to_dict())
    result['현재비중(%)'] = pd.to_numeric(result['현재비중(%)'], errors='coerce').fillna(0.0)
    result['실행목표(%)'] = pd.to_numeric(result['실행목표(%)'], errors='coerce').fillna(0.0)
    result['괴리(%p)'] = result['현재비중(%)'] - result['실행목표(%)']
    result['허용괴리(%p)'] = result['전략'].astype(str).map(tolerance).fillna(0.0)

    def classify(row):
        if row['괴리(%p)'] < -row['허용괴리(%p)'] - 1e-9:
            return '미달'
        if row['괴리(%p)'] > row['허용괴리(%p)'] + 1e-9:
            return '초과'
        return '충족'

    result['목표상태'] = result.apply(classify, axis=1)
    priority = {'미달': 0, '초과': 1, '충족': 2}
    result['_status_order'] = result['목표상태'].map(priority).fillna(3)
    result['_gap_order'] = result['괴리(%p)'].abs()
    return result.sort_values(['_status_order', '_gap_order'], ascending=[True, False]).drop(
        columns=['_status_order', '_gap_order']).reset_index(drop=True)


def style_allocation_rows(frame):
    """Apply calm, accessible status colors to allocation rows."""
    def row_style(row):
        background, _ = TARGET_STATUS_STYLES.get(row.get('목표상태'), ('#111621', '#e6eaf1'))
        return [f'background-color: {background}' for _ in row.index]

    def status_style(value):
        background, foreground = TARGET_STATUS_STYLES.get(value, ('#111621', '#e6eaf1'))
        return f'background-color: {background}; color: {foreground}; font-weight: 750'

    styled = frame.style.apply(row_style, axis=1)
    if '목표상태' in frame.columns:
        styled = styled.map(status_style, subset=['목표상태'])
    return styled
