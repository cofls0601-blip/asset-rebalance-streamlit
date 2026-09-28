"""Shared presentation helpers; formatting never changes stored numeric values."""
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
    '목표대비괴리(%p)', '증감률(%)',
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

