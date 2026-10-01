"""B1/B2 are offline consumers of a shared primary-industry context."""
from decimal import Decimal
import math
from app.rules.base import result

def base(ctx):
    data=ctx.metadata.get('industry_context') or {};primary=data.get('primary_industry') or {}
    day=str(ctx.bars.date.iloc[-1].date()) if len(ctx.bars) else None
    raw=dict(primary_industry_id=primary.get('sector_id'),primary_industry_name=primary.get('name'),
        trade_date=day,provenance=data.get('provenance',{}),primary_industry_provenance=primary.get('provenance',{}),
        primary_industry_as_of=primary.get('as_of'),data_status=data.get('data_status','DATA_ERROR'),
        upstream_data_status=data.get('data_status','DATA_ERROR'))
    error=None
    if data and data.get('data_status')!='VALID':error=data.get('reason_code') or raw['data_status']
    elif not primary.get('sector_id'):raw['data_status']='DATA_ERROR';error='NO_PRIMARY_INDUSTRY'
    elif primary.get('as_of')!=day:raw['data_status']='DATA_STALE';error='PRIMARY_INDUSTRY_DATE_MISMATCH'
    elif primary.get('symbol')!=ctx.metadata.get('symbol',primary.get('symbol')):raw['data_status']='DATA_INCONSISTENT';error='PRIMARY_INDUSTRY_SYMBOL_MISMATCH'
    elif data.get('data_status')!='VALID':error=data.get('reason_code') or raw['data_status']
    return data,raw,error

def unknown(rule,raw,reason):
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
        if isinstance(v,list):return [clean(x) for x in v]
        if isinstance(v,float) and not math.isfinite(v):return None
        return v
    return result(rule,'UNKNOWN',raw=clean(raw),reason_code=reason,explanation=f'行业数据不可评分：{reason}；数据问题不表示业务0分。')

def tier(value,bands):
    points=0;label=f'<{bands[0][0]}'
    for i,(lower,score) in enumerate(bands):
        if value>=Decimal(str(lower)):
            points=score;upper=bands[i+1][0] if i+1<len(bands) else '+inf';label=f'[{lower},{upper})'
    return points,label

def b1(ctx,rule,p):
    data,raw,error=base(ctx);heat=data.get('sector_heat') or {}
    raw['upstream_data_status']=heat.get('overall_status') or raw['upstream_data_status']
    raw.update(sector_heat_score=heat.get('total_score'),sector_heat_max=heat.get('max_score'),sector_heat_trade_date=heat.get('trade_date'),
        sector_heat_status=heat.get('overall_status'),sector_heat_coverage=heat.get('score_coverage'))
    if error:return unknown(rule,raw,error)
    if heat.get('overall_status')!='VALID' or heat.get('total_score') is None:
        raw['data_status']=heat.get('overall_status','DATA_ERROR');return unknown(rule,raw,'SECTOR_HEAT_UNAVAILABLE')
    if heat.get('trade_date')!=raw['trade_date']:
        raw['data_status']='DATA_STALE';return unknown(rule,raw,'SECTOR_HEAT_DATE_MISMATCH')
    if heat.get('sector_id')!=raw['primary_industry_id']:
        raw['data_status']='DATA_INCONSISTENT';return unknown(rule,raw,'SECTOR_HEAT_INDUSTRY_MISMATCH')
    try:
        score=float(heat['total_score']);maximum=float(heat['max_score']);coverage=float(heat['score_coverage'])
        if not all(math.isfinite(x) for x in (score,maximum,coverage)) or not 0<=score<=maximum or not p['B_INTEGRATION']['B1_min_coverage']<=coverage<=1:raise ValueError()
    except (KeyError,TypeError,ValueError):
        raw['data_status']='DATA_INCONSISTENT';return unknown(rule,raw,'INVALID_SECTOR_HEAT')
    points,band=tier(Decimal(str(score)),p['B_INTEGRATION']['B1_bands']);raw.update(threshold_band=band,data_status='VALID')
    return result(rule,score=points,raw=raw,conditions={'complete_sector_heat':True},explanation=f'{raw["primary_industry_name"]}完整Heat={score:g}/{maximum:g}，落入{band}，B1={points}/{rule["max_score"]}；不重复累加S1–S7。')

def b2(ctx,rule,p):
    data,raw,error=base(ctx);ret=data.get('returns') or {}
    raw.update(sector_return_5d=ret.get('sector_return_5d'),window_start=ret.get('window_start'),window_end=ret.get('window_end'),
        stock_return_5d=None,relative_return_5d=None,adjustment_type=ctx.metadata.get('adjustment_type'))
    if error:return unknown(rule,raw,error)
    if ret.get('data_status')!='VALID':
        raw['data_status']=ret.get('data_status','DATA_ERROR');return unknown(rule,raw,'INDUSTRY_RETURN_UNAVAILABLE')
    try:
        days=ret['trade_dates'];length=p['B_INTEGRATION']['return_intervals']+1
        if len(days)!=length or len(set(days))!=length or days!=sorted(days):raise ValueError('INVALID_TRADE_WINDOW')
        if days[0]!=ret['window_start'] or days[-1]!=ret['window_end'] or days[-1]!=raw['trade_date']:raise ValueError('TRADE_WINDOW_MISMATCH')
        if ret.get('adjustment_type')!='qfq' or ctx.metadata.get('adjustment_type')!='qfq':raise ValueError('ADJUSTMENT_MISMATCH')
        stock=ctx.bars.tail(length);dates=stock.date.dt.strftime('%Y-%m-%d').tolist()
        raw.update(stock_window_start=dates[0] if dates else None,stock_window_end=dates[-1] if dates else None,stock_trade_dates=dates,sector_trade_dates=days)
        if dates!=days:raise ValueError('TRADE_WINDOW_MISMATCH')
        prices=[float(v) for v in stock.close_adj]
        if not all(math.isfinite(v) and v>0 for v in prices):raise ValueError('STOCK_RETURN_UNAVAILABLE')
        sr=prices[-1]/prices[0]-1;ir=float(ret['sector_return_5d'])
        if not math.isfinite(ir):raise ValueError('INDUSTRY_RETURN_UNAVAILABLE')
        relative=Decimal(str(sr))-Decimal(str(ir))
        # Floating-division noise only; this is not a trading tolerance.
        for lower,_ in p['B_INTEGRATION']['B2_bands']:
            if math.isclose(float(relative),lower,rel_tol=0,abs_tol=1e-12):relative=Decimal(str(lower));break
        points,band=tier(relative,p['B_INTEGRATION']['B2_bands'])
        raw.update(stock_return_5d=sr,relative_return_5d=float(relative),threshold_band=band,data_status='VALID')
        return result(rule,score=points,raw=raw,conditions={'same_window':True,'same_qfq_basis':True},explanation=f'同窗口{days[0]}至{days[-1]}，qfq个股收益{sr:.4%}－行业收益{ir:.4%}={float(relative):.4%}；区间{band}，B2={points}/{rule["max_score"]}。')
    except (KeyError,AttributeError,TypeError,ValueError,IndexError) as exc:
        raw['data_status']='DATA_INCONSISTENT';return unknown(rule,raw,str(exc))
