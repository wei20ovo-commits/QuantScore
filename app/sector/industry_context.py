"""Primary-industry context: data acquisition once, existing SectorHeat scoring once."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,date
import math
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.data.cache import DataCache,CacheKey
from app.data.market_rule import CurrentMarketLimitEngine
from .providers import canonical_symbol
from .market_data import align_bars,_returns,sector_snapshot,s7_strong_ratio
from .models import SectorRuleInput
from .scoring import SectorHeatEngine

def json_values(value):
    """Represent missing numerical evidence as JSON null, never a numerical score."""
    if isinstance(value,dict):return {k:json_values(v) for k,v in value.items()}
    if isinstance(value,list):return [json_values(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):return None
    return value

def context_from_frames(symbol,sector_name,day,raws,adjusted,basic,calendar,benchmark,provenance):
    """Pure adapter over validated real frames; reuses Stage3A calculations and Stage3B engine."""
    sector_id=sector_name[:3];symbols=list(raws);n=len(symbols)
    days=[d.date() for d in pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date'])
          if pd.Timestamp(benchmark.date.min())<=d<=pd.Timestamp(day)]
    if len(days)<21 or str(days[-1])!=day:raise ValueError('Incomplete trading calendar')
    basic=basic.set_index('code') if 'code' in basic else basic
    frames=[];limits=[];engine=CurrentMarketLimitEngine()
    for s in symbols:
        raw=raws[s].copy();adj=adjusted[s].copy()
        raw['date']=pd.to_datetime(raw.date);adj['date']=pd.to_datetime(adj.date)
        raw=raw.loc[raw.date.le(pd.Timestamp(day))];adj=adj.loc[adj.date.le(pd.Timestamp(day))]
        if raw.date.tolist()!=adj.date.tolist() or raw.date.duplicated().any():raise ValueError(f'Raw/qfq dates inconsistent: {s}')
        frames.append(adj[['date','symbol','close']].merge(raw[['date','symbol','amount']],on=['date','symbol'],validate='one_to_one'))
        r=raw.loc[raw.date.eq(pd.Timestamp(day))].iloc[0];meta=basic.loc[s[-2:].lower()+'.'+s[:6]]
        ipo=pd.Timestamp(meta.ipoDate);caldates=pd.to_datetime(calendar.calendar_date)
        if caldates.min()>ipo or caldates.max()<pd.Timestamp(day):raise ValueError('IPO calendar incomplete')
        count=int(((caldates>=ipo)&(caldates<=pd.Timestamp(day))&calendar.is_trading_day.eq(1)).sum())
        limit=engine.resolve_current(trade_date=day,symbol=s,exchange=s[-2:],previous_close=r.preclose,
            ipo_date=meta.ipoDate,trading_days_since_ipo=count,is_st=int(r.isST),high=r.high,close=r.close)
        limits.append(dict(symbol=s,date=day,status=limit.status,rule_source=limit.rule_source,
            calculated_limit_up=limit.limit_up_price,actual_close=float(r.close),closed_at_limit_up=limit.closed_at_limit_up))
    frame=pd.concat(frames);aligned=align_bars(frame,symbols=symbols,trading_days=days);ret=_returns(aligned)
    current=ret.loc[ret.date.eq(days[-1])];valid=int(current.return_1d.notna().sum());coverage=valid/n
    b=_returns(align_bars(benchmark,trading_days=days)).set_index('date')
    snap=sector_snapshot(sector_id,frame,symbols=symbols,trading_days=days)
    quality='VALID' if valid==n else 'DATA_INCONSISTENT';inputs={}
    for rid,period,v in [('S1','1d',snap.return_1d),('S2','5d',snap.return_5d)]:
        bv=float(b.iloc[-1]['return_'+period])
        inputs[rid]={f'sector_return_{period}':v,f'benchmark_return_{period}':bv,f'sector_excess_return_{period}':None if v is None else v-bv,'coverage':coverage,'return_intervals':5}
    inputs['S3']=dict(advancing_constituents=int(current.return_1d.gt(0).sum()),valid_constituents=valid,expected_constituents=n,breadth=snap.breadth,coverage=coverage)
    vl=sum(r['status']=='VALID' for r in limits);lc=sum(r['closed_at_limit_up'] is True for r in limits)
    inputs['S4']=dict(limit_up_count=lc,limit_up_ratio=lc/vl if vl else None,expected_count=n,valid_limit_count=vl,limit_details=limits)
    amounts=[]
    for d in days[-21:]:
        a=aligned.loc[aligned.date.eq(d),'amount'];c=float(a.notna().sum()/n)
        amounts.append(dict(date=str(d),sector_amount=float(a.sum()),coverage=c,status='VALID' if c==1 else 'DATA_INCONSISTENT'))
    inputs['S5']=dict(sector_amount_today=snap.amount,sector_amount_prior_20d_mean=snap.amount_20d_mean,amount_ratio=snap.amount_20d_ratio,coverage=coverage,daily_amounts=amounts)
    daily=[]
    for d in days[-5:]:
        v=ret.loc[ret.date.eq(d),'return_1d'];sr=float(v.mean());br=float(b.loc[d,'return_1d']);c=float(v.notna().sum()/n)
        daily.append(dict(date=str(d),sector_return=sr,benchmark_return=br,sector_win=sr>br,coverage=c,status='VALID' if c==1 else 'DATA_INCONSISTENT'))
    inputs['S6']=dict(coverage=coverage,daily_comparisons=daily,expected_trade_dates=[r['date'] for r in daily],win_days=sum(r['sector_win'] for r in daily))
    inputs['S7']=dict(strong_count=int(current.return_1d.ge(.05).sum()),expected_count=n,valid_return_count=valid,strong_ratio=s7_strong_ratio(frame,expected_constituents=symbols,trading_days=days).value)
    # DataStatus for S2 reflects the entire six-session window, independently of Heat's other prerequisites.
    recent=ret.loc[ret.date.isin(days[-6:])]
    complete=recent.groupby('symbol').close.apply(lambda x:len(x)==6 and x.notna().all()).reindex(symbols,fill_value=False).all()
    rule_inputs={k:SectorRuleInput(v,day,quality if k!='S2' else ('VALID' if complete else 'DATA_INCONSISTENT')) for k,v in inputs.items()}
    heat=SectorHeatEngine().evaluate(sector_id,sector_name,day,rule_inputs,provenance)
    return json_values(dict(data_status='VALID',primary_industry=dict(symbol=symbol,sector_id=sector_id,name=sector_name,provider='baostock',as_of=day,provenance=provenance),
        sector_heat=heat.to_dict(),returns=dict(sector_return_5d=snap.return_5d,window_start=str(days[-6]),window_end=day,trade_dates=[str(d) for d in days[-6:]],
            adjustment_type='qfq',data_status='VALID' if complete else 'DATA_INCONSISTENT'),provenance=provenance,expected_count=n))

class PrimaryIndustryService:
    def __init__(self,cache=None,provider=None):
        self.cache=cache if cache is not None else DataCache()
        self.provider=provider if provider is not None else BaoStockProvider(timeout=150)

    def build(self,symbol,day,*,refresh=False):
        p=self.provider;events=[];primary={}
        def fetch(label,code,start,end,fn):
            key=CacheKey('baostock',code,str(start),str(end),'industry_context:'+label)
            value=self.cache.get(key,force_refresh=refresh)
            if value is not None:
                events.append(dict(request=label,symbol=code,cache_hit=True,rows=len(value),last_updated=value.attrs.get('last_updated')));return value
            for attempt in range(1,4):
                try:
                    value=fn()
                    if value.empty:raise ValueError('Empty response')
                    self.cache.put(key,value);events.append(dict(request=label,symbol=code,cache_hit=False,rows=len(value),attempt=attempt));return value
                except Exception as exc:
                    events.append(dict(request=label,symbol=code,status='DATA_ERROR',attempt=attempt,error=str(exc)))
                    if attempt==3:raise
        try:
            if not symbol.endswith(('.SH','.SZ')):raise ValueError('OUT_OF_SCOPE_FOR_V1')
            now=pd.Timestamp.now(tz='Asia/Shanghai');cutoff=now.normalize().tz_localize(None)
            if now.hour<16:cutoff-=pd.Timedelta(days=1)
            recent=fetch('recent_calendar','calendar',str(cutoff.date()),str(cutoff.date()),lambda:p.query_trade_dates(cutoff-pd.Timedelta(days=14),cutoff))
            latest=str(pd.to_datetime(recent.loc[recent.is_trading_day.eq(1),'calendar_date']).max().date())
            if day!=latest:return dict(data_status='DATA_STALE',reason_code='CURRENT_MEMBERSHIP_NOT_HISTORICAL',provenance={'provider':'baostock','requested_day':day,'latest_day':latest})
            membership=fetch('membership','SH_SZ',day,day,lambda:p._call('query_stock_industry'))
            membership['symbol']=membership.code.map(canonical_symbol)
            target=membership.loc[membership.symbol.eq(symbol)&membership.industry.fillna('').ne('')]
            if len(target)!=1:raise ValueError('NO_UNIQUE_PRIMARY_INDUSTRY')
            name=target.industry.iloc[0];members=membership.loc[membership.industry.eq(name)&membership.symbol.str.endswith(('.SH','.SZ'))].drop_duplicates('symbol')
            primary=dict(symbol=symbol,sector_id=name[:3],name=name,provider='baostock',as_of=day)
            symbols=members.symbol.tolist();start=str((pd.Timestamp(day)-pd.Timedelta(days=80)).date())
            benchmark=fetch('benchmark','000001.SH',start,day,lambda:p.fetch_benchmark(start,day))
            basic=fetch('metadata','all',day,day,p.query_stock_basic)
            missing=[s for s in symbols if p.source_code(s) not in set(basic.code)]
            def meta(s):return fetch('metadata',s,day,day,lambda:p.query_stock_basic(s))
            if missing:
                with ThreadPoolExecutor(max_workers=3) as pool:basic=pd.concat([basic,*pool.map(meta,missing)]).drop_duplicates('code',keep='last')
            def calendar(year):
                end=min(date(year+4,12,31),pd.Timestamp(day).date())
                return fetch('calendar','calendar',f'{year}-01-01',str(end),lambda:p.query_trade_dates(f'{year}-01-01',end))
            earliest=int(pd.to_datetime(basic.loc[basic.code.isin([p.source_code(s) for s in symbols]),'ipoDate']).dt.year.min())
            with ThreadPoolExecutor(max_workers=3) as pool:cal=pd.concat(list(pool.map(calendar,range(earliest,pd.Timestamp(day).year+1,5)))).drop_duplicates('calendar_date').sort_values('calendar_date')
            if not set(pd.date_range(pd.to_datetime(cal.calendar_date).min(),day))<=set(pd.to_datetime(cal.calendar_date)):raise ValueError('CALENDAR_INCOMPLETE')
            def bars(s):
                return s,fetch('raw',s,start,day,lambda:p.fetch_stock_daily(s,start,day,'raw')),fetch('qfq',s,start,day,lambda:p.fetch_stock_daily(s,start,day,'qfq'))
            with ThreadPoolExecutor(max_workers=3) as pool:data=list(pool.map(bars,symbols))
            provenance=dict(provider='baostock',as_of=day,retrieved_at=datetime.now(timezone.utc).isoformat(),source='query_stock_industry + raw/qfq + calendar',requests=events)
            return context_from_frames(symbol,name,day,{s:r for s,r,a in data},{s:a for s,r,a in data},basic,cal,benchmark,provenance)
        except Exception as exc:
            return dict(data_status='DATA_ERROR',reason_code=str(exc),primary_industry=primary,provenance={'provider':'baostock','requests':events})
