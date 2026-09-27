"""Versioned, portable records. Sheets is the user's durable source of truth."""
import io
import json
import math
from datetime import date
import pandas as pd
from streamlit_app.data import (DataError, normalize_holdings, normalize_strategies, normalize_category_targets,
    HOLDING_COLUMNS, STRATEGY_COLUMNS, SNAPSHOT_COLUMNS, ACTION_COLUMNS, CASHFLOW_COLUMNS, CATEGORY_TARGET_COLUMNS)
from streamlit_app.workflow import records, stable_id

SCHEMA_VERSION = 3
TABLES = ['holdings','strategies','snapshots','actions','cashflows','category_targets','evaluations','strategy_versions']
SCHEMAS = dict(zip(TABLES, [HOLDING_COLUMNS, STRATEGY_COLUMNS,
    SNAPSHOT_COLUMNS + ['schema_version','run_id','record_id','revision','revision_reason','role','fx','account_weight_pct','execution_target_pct','price_date','fx_date','price_source','strategy_json','classification_json'],
    ACTION_COLUMNS + ['schema_version','execution_id','order_id','run_id','execution_date','actual_price','fx','actual_amount','currency','status'],
    CASHFLOW_COLUMNS + ['kind','transfer_id'], CATEGORY_TARGET_COLUMNS,
    ['run_id','date','engine_version','part','parts','payload_json'], STRATEGY_COLUMNS + ['archived_at']]))


def empty_workspace():
    return {k:pd.DataFrame(columns=SCHEMAS[k]) for k in TABLES}


def _pack(value):
    if isinstance(value,pd.DataFrame):
        return {'_frame':True,'columns':list(value.columns),'rows':records(value)}
    if isinstance(value,dict):return {k:_pack(v) for k,v in value.items()}
    if isinstance(value,list):return [_pack(v) for v in value]
    return value


def _unpack(value):
    if isinstance(value,dict):
        if value.get('_frame') is True:return pd.DataFrame(value['rows'],columns=value['columns'])
        return {k:_unpack(v) for k,v in value.items()}
    if isinstance(value,list):return [_unpack(v) for v in value]
    return value


def backup_bytes(workspace, drafts=None):
    payload = {'schema_version':SCHEMA_VERSION, 'tables':{k:records(workspace.get(k,pd.DataFrame())) for k in TABLES},
               'columns':{k:list(workspace.get(k,pd.DataFrame()).columns) for k in TABLES},
               'drafts':_pack(drafts or {})}
    return json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')


def restore_backup(raw, include_drafts=False):
    if len(raw) > 30_000_000:
        raise DataError('백업은 30MB 이하로 업로드하세요')
    try:
        payload = json.loads(raw)
        if payload['schema_version'] != SCHEMA_VERSION:
            raise DataError('지원하지 않는 백업 버전입니다')
        tables = payload['tables']
        if any(k not in tables for k in TABLES):
            raise DataError('백업의 필수 테이블이 없습니다')
        workspace = {k:pd.DataFrame(tables[k],columns=payload.get('columns',{}).get(k)) for k in TABLES}
        workspace['holdings'] = normalize_holdings(workspace['holdings'])
        workspace['strategies'] = normalize_strategies(workspace['strategies'])
        workspace['category_targets'] = normalize_category_targets(workspace['category_targets'])
        latest_snapshots(workspace['snapshots'])
        validate_actions(workspace['actions'])
        from streamlit_app.performance import validate_flows
        validate_flows(workspace['cashflows'])
        drafts = _unpack(payload.get('drafts',{}))
        if not isinstance(drafts,dict):raise DataError('백업 작업 상태가 올바르지 않습니다')
        return (workspace,drafts) if include_drafts else workspace
    except DataError:
        raise
    except Exception as exc:
        raise DataError('올바른 전체 백업 JSON이 아닙니다') from exc


def validate_actions(actions):
    if actions.empty:return actions
    if 'execution_id' in actions:
        ids=actions.execution_id.fillna('').astype(str)
        if ids[ids.ne('')].duplicated().any():raise DataError('중복 체결 ID가 있습니다')
    for col in ['actual_shares','actual_amount']:
        if col in actions:
            populated=actions[col].notna() & actions[col].astype(str).ne('')
            values=pd.to_numeric(actions.loc[populated,col],errors='coerce')
            if values.isna().any() or not values.map(math.isfinite).all() or (values<0).any():
                raise DataError('체결 이력의 수량·금액을 확인하세요')
    return actions


def snapshots_match(local, remote):
    """Verify immutable identity AND values; identical IDs alone do not prove a save."""
    if local.empty or 'record_id' not in local or 'record_id' not in remote:return False
    fields=['record_id','run_id','date','strategy','ticker','shares','close','fx','value','revision']
    if any(k not in local or k not in remote for k in fields):return False
    if local.record_id.duplicated().any() or remote.record_id.duplicated().any():return False
    if not set(local.record_id).issubset(set(remote.record_id)):return False
    a=local.set_index('record_id');b=remote.set_index('record_id').loc[a.index]
    for key in fields[1:]:
        if key in ['shares','close','fx','value','revision']:
            x,y=pd.to_numeric(a[key],errors='coerce'),pd.to_numeric(b[key],errors='coerce')
            if x.isna().any() or y.isna().any() or ((x-y).abs()>1e-7*(1+x.abs())).any():return False
        elif not a[key].astype(str).eq(b[key].astype(str)).all():return False
    return True


def load_frozen_run(evaluations, run_id):
    try:
        rows=evaluations[evaluations.run_id.eq(run_id)].copy()
        if rows.empty:raise ValueError('missing run')
        if 'part' in rows and rows['part'].notna().all():
            rows['part']=pd.to_numeric(rows['part']).astype(int)
            rows=rows.sort_values('part')
            if list(rows['part'])!=list(range(int(rows.parts.iloc[0]))):raise ValueError('missing part')
        payload=json.loads(''.join(rows.payload_json.astype(str)))
        for key in ['view','plan','holdings','strategies','original_plan']:
            if key in payload:payload[key]=pd.DataFrame(payload[key])
        if payload['id']!=run_id:raise ValueError('run mismatch')
        return payload
    except Exception as exc:
        raise DataError('평가 원본을 복원하지 못했습니다. Evaluations의 모든 조각을 가져오세요') from exc


def latest_snapshots(snapshots):
    """Deduplicate exact replay, select latest revision per account/date, retain originals."""
    if snapshots.empty:
        return snapshots.copy()
    frame = snapshots.drop_duplicates().copy()
    required = {'date','strategy','ticker','value'}
    if not required.issubset(frame.columns):
        raise DataError('Snapshots 필수 열이 없습니다: '+', '.join(sorted(required-set(frame.columns))))
    if pd.to_datetime(frame['date'],errors='coerce').isna().any():
        raise DataError('Snapshots 날짜를 확인하세요')
    values = pd.to_numeric(frame['value'],errors='coerce')
    if values.isna().any() or not values.map(math.isfinite).all() or (values < 0).any():
        raise DataError('Snapshots 평가액을 확인하세요')
    frame['value'] = values
    if 'revision' not in frame:
        frame['revision'] = 1
    frame['revision'] = pd.to_numeric(frame.revision,errors='coerce').fillna(1).astype(int)
    frame = frame[frame.revision.eq(frame.groupby(['date','strategy']).revision.transform('max'))]
    if frame.duplicated(['date','strategy','ticker']).any():
        raise DataError('동일 일자·전략·종목의 기록이 중복됩니다. 개정 번호를 확인하세요')
    return frame


def freeze_run(run, workspace, memo='', revision_reason=''):
    if run['view'].empty:
        raise DataError('확정할 계좌가 없습니다')
    snapshots = workspace.get('snapshots',pd.DataFrame()).copy()
    evaluations = workspace.get('evaluations',pd.DataFrame()).copy()
    if (not evaluations.empty and run['id'] in set(evaluations['run_id'])) or run['id'] in set(snapshots.get('run_id',pd.Series(dtype=str))):
        return workspace, False
    rows = []
    for code, group in run['view'].groupby('strategy'):
        previous = snapshots[(snapshots.date.astype(str).eq(run['date'])) & snapshots.strategy.eq(code)] if not snapshots.empty else pd.DataFrame()
        if not previous.empty and not revision_reason.strip():
            raise DataError(f'{code}: 같은 날짜 기록이 있습니다. 개정 사유를 입력하세요')
        revision = int(pd.to_numeric(previous.get('revision',pd.Series([1])),errors='coerce').fillna(1).max())+1 if not previous.empty else 1
        strategy = run['strategies'].loc[run['strategies'].code.eq(code)].iloc[0]
        targets = run['plan'].loc[run['plan']['전략'].eq(code)].set_index('티커')['실행목표(%)'].to_dict()
        for r in group.to_dict('records'):
            rows.append({'schema_version':SCHEMA_VERSION,'run_id':run['id'],'record_id':stable_id([run['id'],code,r['ticker']]),
                         'revision':revision,'revision_reason':revision_reason,'date':run['date'],'saved_at':run['created_at'],
                         'strategy':code,'account':r['account'],'ticker':r['ticker'],'name':r['name'],'category':r['category'],
                         'role':r['role'],'classification_json':r.get('classification_json',''),'shares':r['shares'],'close':r['close'],'fx':r['fx'],'value':r['평가액'],
                         'weight_pct':r['전체비중'],'account_weight_pct':r['현재비중'],'target_pct':r['target_pct'],
                         'execution_target_pct':targets.get(r['ticker'],r['target_pct']), 'price_date':r['price_date'],
                         'fx_date':r['fx_date'],'price_source':r['price_source'],'strategy_version':strategy['version'],
                         'strategy_json':json.dumps(strategy.to_dict(),ensure_ascii=False,default=str),'memo':memo})
    updated = {k:v.copy() for k,v in workspace.items()}
    updated['snapshots'] = pd.concat([snapshots,pd.DataFrame(rows)],ignore_index=True)
    payload = {k:records(v) if isinstance(v,pd.DataFrame) else v for k,v in run.items()}
    serialized=json.dumps(payload,ensure_ascii=False,default=str)
    chunks=[serialized[i:i+20000] for i in range(0,len(serialized),20000)]
    updated['evaluations'] = pd.concat([evaluations,pd.DataFrame([{'run_id':run['id'],'date':run['date'],
        'engine_version':run['engine_version'],'part':i,'parts':len(chunks),'payload_json':chunk}
        for i,chunk in enumerate(chunks)])],ignore_index=True)
    return updated, True


def execution_draft(run):
    p = run['plan']
    if p.empty:
        return pd.DataFrame()
    p = p[p['티커'].ne('CASH') & p['제안수량'].ne(0)].copy()
    p['실행'] = False
    p['체결ID'] = p['주문ID'].map(lambda v:stable_id([v,'fill-1']))
    p['체결일'] = ''
    p['실제수량'] = 0.
    p['실제단가'] = 0.
    p['실제환율'] = p['환율']
    p['실제체결금액'] = 0.
    p['메모'] = ''
    return p


def order_status(run, actions):
    rows=[]
    for order in run['plan'].to_dict('records'):
        if not order['제안수량']:continue
        history=actions[actions.get('order_id',pd.Series(index=actions.index,dtype=str)).eq(order['주문ID'])]
        quantity=float(pd.to_numeric(history.get('actual_shares',pd.Series(dtype=float)),errors='coerce').sum())
        cancelled=history.get('status',pd.Series(dtype=str)).eq('취소').any()
        state='취소' if cancelled else '완료' if quantity>=abs(order['제안수량'])-1e-8 else '부분 체결' if quantity else '미실행'
        rows.append({'주문ID':order['주문ID'],'전략':order['전략'],'티커':order['티커'],'상태':state,
                     '제안수량':abs(order['제안수량']),'누적체결':quantity,'잔여수량':max(0.,abs(order['제안수량'])-quantity)})
    return pd.DataFrame(rows)


def cancel_orders(workspace, run, order_ids, reason):
    if not order_ids or not reason.strip():raise DataError('취소 대상과 사유가 필요합니다')
    status=order_status(run,workspace['actions']).set_index('주문ID')
    rows=[]
    for ident in order_ids:
        if ident not in status.index or status.loc[ident,'상태'] in ['완료','취소']:raise DataError('취소할 잔여 주문이 없습니다')
        row=status.loc[ident]
        rows.append({'schema_version':SCHEMA_VERSION,'execution_id':stable_id([ident,'cancel']),
            'order_id':ident,'run_id':run['id'],'date':run['date'],'saved_at':pd.Timestamp.now(tz='UTC').isoformat(),
            'strategy':row['전략'],'ticker':row['티커'],'actual_shares':0.,'actual_amount':0.,'done':False,'status':'취소','memo':reason})
    updated={k:v.copy() for k,v in workspace.items()}
    updated['actions']=pd.concat([workspace['actions'],pd.DataFrame(rows)],ignore_index=True)
    return updated


def apply_executions(workspace, fills, run):
    """Commit explicit fills atomically. Never finance buys using same-batch sales."""
    holdings = normalize_holdings(workspace['holdings']).copy()
    history = workspace.get('actions',pd.DataFrame()).copy()
    validate_actions(history)
    existing = set(history.get('execution_id',pd.Series(dtype=str)).dropna())
    checked = fills[fills['실행'].eq(True)]
    if checked.empty:
        raise DataError('반영할 체결을 선택하세요')
    if checked['체결ID'].duplicated().any():
        raise DataError('체결 ID가 중복되었습니다')
    buys, sales, out = {}, {}, []
    plan = run['plan'].set_index('주문ID')
    today = date.today()
    for r in checked.to_dict('records'):
        ident = str(r['체결ID']).strip()
        if not ident:
            raise DataError('체결 ID가 필요합니다')
        if ident in existing:
            raise DataError('이미 반영된 체결입니다: '+ident)
        order_id = r['주문ID']
        previous=history[history.get('order_id',pd.Series(index=history.index,dtype=str)).eq(order_id)]
        if previous.get('status',pd.Series(dtype=str)).eq('취소').any():raise DataError('취소된 주문에는 체결을 추가할 수 없습니다')
        if order_id not in plan.index:
            raise DataError('평가 결과에 없는 주문입니다')
        order = plan.loc[order_id]
        qty, price, fx, amount = [float(r[k]) for k in ['실제수량','실제단가','실제환율','실제체결금액']]
        if any(not math.isfinite(v) or v <= 0 for v in (qty,price,fx,amount)):
            raise DataError('실제 수량·단가·환율·체결금액은 양수여야 합니다')
        try:
            trade_date = date.fromisoformat(str(r['체결일'])[:10])
        except ValueError as exc:
            raise DataError('체결일을 YYYY-MM-DD로 입력하세요') from exc
        if trade_date < date.fromisoformat(order['주문예정일']) or trade_date > today:
            raise DataError('체결일은 주문 예정일 이후이며 미래일 수 없습니다')
        from streamlit_app.market import calendar
        from streamlit_app.engine import resolved_market
        market = resolved_market(order['티커'],'KR')
        if not calendar(market,trade_date.year).is_session(pd.Timestamp(trade_date)):
            raise DataError('체결일이 거래일이 아닙니다')
        if market == 'KR' and abs(fx-1)>1e-9:
            raise DataError('원화 종목의 체결 환율은 1이어야 합니다')
        if abs(qty/order['거래단위']-round(qty/order['거래단위'])) > 1e-6:
            raise DataError('실제 수량이 계좌 거래 단위와 맞지 않습니다')
        if abs(amount - qty*price*fx) > max(1., amount*.00001):
            raise DataError('실제체결금액(원)이 수량 × 단가 × 환율과 다릅니다')
        code,ticker,side = order['전략'],order['티커'],order['구분']
        previous_qty = pd.to_numeric(history.loc[history.get('order_id',pd.Series(index=history.index,dtype=str)).eq(order_id),'actual_shares'],errors='coerce').sum() if not history.empty and 'actual_shares' in history else 0
        prior_batch = sum(x['actual_shares'] for x in out if x['order_id']==order_id)
        if previous_qty+prior_batch+qty > abs(order['제안수량'])+1e-8:
            raise DataError('누적 체결수량이 확정 주문 수량을 초과합니다')
        mask = holdings.strategy.eq(code)&holdings.ticker.eq(ticker)
        if mask.sum()!=1:
            raise DataError('체결 대상 보유내역이 변경되었습니다')
        sign = 1 if side=='매수' else -1
        new = float(holdings.loc[mask,'shares'].iloc[0])+sign*qty
        if new < -1e-8:
            raise DataError('보유수량 초과 매도입니다')
        holdings.loc[mask,'shares'] = new
        target = buys if sign==1 else sales
        target[code] = target.get(code,0.)+amount
        out.append({'schema_version':SCHEMA_VERSION,'execution_id':ident,'order_id':order_id,'run_id':run['id'],
            'date':run['date'],'execution_date':str(trade_date),'saved_at':pd.Timestamp.now(tz='UTC').isoformat(),
            'strategy':code,'ticker':ticker,'name':order['종목'],'side':side,'planned_shares':abs(order['제안수량']),
            'actual_shares':qty,'actual_price':price,'fx':fx,'actual_amount':amount,'planned_amount':abs(order['예상매매액']),
            'currency':'USD' if market=='US' else 'KRW','done':True,
            'status':'완료' if abs(previous_qty+prior_batch+qty-abs(order['제안수량']))<1e-8 else '부분 체결',
            'reason':order['근거'],'memo':r.get('메모','')})
    for code in set(buys)|set(sales):
        mask=holdings.strategy.eq(code)&holdings.ticker.eq('CASH')
        if mask.sum()!=1:
            raise DataError('CASH 행이 필요합니다')
        start=float(holdings.loc[mask,'shares'].iloc[0])
        reserve=float(workspace['strategies'].loc[workspace['strategies'].code.eq(code),'cash_reserve'].iloc[0])
        if buys.get(code,0)>max(0.,start-reserve)+1e-7:
            raise DataError('기존 CASH 잔액이 부족합니다. 같은 반영 묶음의 매도대금은 재사용하지 않습니다')
        holdings.loc[mask,'shares']=start-buys.get(code,0)+sales.get(code,0)
    updated={k:v.copy() for k,v in workspace.items()}
    updated['holdings']=holdings
    updated['actions']=pd.concat([history,pd.DataFrame(out)],ignore_index=True)
    return updated


def parse_table(raw):
    text=raw.decode('utf-8-sig') if isinstance(raw,bytes) else raw
    sep='\t' if '\t' in text.partition('\n')[0] else ','
    try:
        return pd.read_csv(io.StringIO(text),sep=sep,dtype={'ticker':str,'strategy':str,'code':str})
    except Exception as exc:
        raise DataError('표를 읽지 못했습니다. CSV/TSV 헤더를 확인하세요') from exc
