"""Small live acceptance only; no ranking, no stock score integration."""
from pathlib import Path
from types import SimpleNamespace
import sys,json,socket,threading
from datetime import date,datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.data.market_rule import CurrentMarketLimitEngine
from app.sector.providers import BaoStockIndustryProvider
from app.sector.market_data import align_bars,_returns,sector_snapshot,s6_daily_comparisons,s7_strong_ratio
from app.sector.models import SectorRuleInput
from app.sector.scoring import SectorHeatEngine
from app.sector.replay import records,write_results
from tools.stage35_evidence import ipo_trading_day_count

def main():
    out=ROOT/'outputs/stage3b/live';out.mkdir(parents=True,exist_ok=True)
    socket.setdefaulttimeout(20)
    resume='--resume' in sys.argv
    p=BaoStockProvider(timeout=150 if resume else 40);industry=BaoStockIndustryProvider()
    logs=json.loads((out/'request_log.json').read_text(encoding='utf-8')) if resume else []
    log_lock=threading.Lock()
    def call(label,fn):
        for attempt in range(1,4):
            try:
                result=fn();logs.append(dict(request=label,attempt=attempt,status='SUCCESS',retrieved_at=datetime.now(timezone.utc).isoformat()));return result
            except Exception as exc:
                logs.append(dict(request=label,attempt=attempt,status='DATA_ERROR',error=str(exc)))
            finally:
                with log_lock:(out/'request_log.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf-8')
        raise RuntimeError(label+' exhausted retries')
    if resume:
        # Resume this same live run's successful industry request, never Stage35 data.
        stored=json.loads((out/'membership.json').read_text(encoding='utf-8'))
        selected=SimpleNamespace(name=stored[0]['sector'],sector_id=stored[0]['sector'])
        symbols=[m['symbol'] for m in stored]
    else:
        sectors=call('industry list',industry.list_sectors)
        selected=next(s for s in sectors if s.name.startswith('C25'))
        members=call('constituents '+selected.name,lambda:industry.list_constituents(selected.sector_id))
        members=[m for m in members if m.symbol.endswith(('.SH','.SZ'))];symbols=[m.symbol for m in members]
        (out/'membership.json').write_text(json.dumps([dict(symbol=m.symbol,name=m.name,sector=m.sector_id,provenance=m.provenance.as_dict()) for m in members],ensure_ascii=False,indent=2),encoding='utf-8')
    end=date.today();start=end-timedelta(days=80)
    def saved_or_fetch(file,fn,dates=None):
        if resume and (out/file).exists():return pd.read_csv(out/file,parse_dates=dates)
        value=fn();value.to_csv(out/file,index=False);return value
    basic=saved_or_fetch('metadata.csv',lambda:call('metadata',p.query_stock_basic)).set_index('code')
    missing=[s for s in symbols if p.source_code(s) not in basic.index]
    if missing:
        (out/'metadata_completeness.json').write_text(json.dumps(dict(original_rows=len(basic),missing_target_symbols=missing,
            action='Fetch each missing target explicitly; preserve original response'),indent=2),encoding='utf-8')
        def supplement(s):
            return saved_or_fetch(s+'_metadata.csv',lambda:call(s+' metadata',lambda:p.query_stock_basic(s))).set_index('code')
        with ThreadPoolExecutor(max_workers=3) as pool:extra=list(pool.map(supplement,missing))
        basic=pd.concat([basic,*extra]);basic=basic[~basic.index.duplicated(keep='last')]
        if any(p.source_code(s) not in basic.index for s in symbols):raise ValueError('Target metadata remains incomplete')
        basic.to_csv(out/'metadata_completed.csv')
    cal=saved_or_fetch('calendar.csv',lambda:call('calendar',lambda:p.query_trade_dates('1990-01-01',end)),['calendar_date'])
    bench=saved_or_fetch('benchmark.csv',lambda:call('benchmark',lambda:p.fetch_benchmark(start,end)),['date'])
    # Keep a resumed run on its original successful benchmark window, even past midnight.
    start=bench.date.min().date();end=bench.date.max().date()
    if cal.calendar_date.max()<pd.Timestamp(end):
        # The live large response ended after 4000 rows. Bounded requests make
        # completeness verifiable without changing the existing provider.
        ranges=[(date(year,1,1),min(date(year+4,12,31),end)) for year in range(1990,end.year+1,5)]
        def calendar_chunk(bounds):
            first,last=bounds
            return saved_or_fetch(f'calendar_{first.year}.csv',lambda:call(f'calendar {first}..{last}',lambda:p.query_trade_dates(first,last)),['calendar_date'])
        with ThreadPoolExecutor(max_workers=3) as pool:chunks=list(pool.map(calendar_chunk,ranges))
        cal=pd.concat(chunks).drop_duplicates('calendar_date').sort_values('calendar_date')
        if cal.calendar_date.max()<pd.Timestamp(end):raise ValueError('Chunked calendar still incomplete')
        expected=pd.date_range(cal.calendar_date.min(),end)
        if not set(expected)<=set(cal.calendar_date):raise ValueError('Calendar has missing dates')
        cal.to_csv(out/'calendar_completed.csv',index=False)
    day=str(bench.date.max().date());days=[d.date() for d in cal.loc[cal.is_trading_day.eq(1),'calendar_date'] if pd.Timestamp(start)<=d<=pd.Timestamp(day)]
    def fetch(s):
        raw=saved_or_fetch(s+'_raw.csv',lambda:call(s+' raw',lambda:p.fetch_stock_daily(s,start,end,'raw')),['date'])
        adj=saved_or_fetch(s+'_qfq.csv',lambda:call(s+' qfq',lambda:p.fetch_stock_daily(s,start,end,'qfq')),['date'])
        if not raw.date.equals(adj.date):raise ValueError('raw/qfq date mismatch')
        return s,raw,adj
    with ThreadPoolExecutor(max_workers=3) as pool:fetched=list(pool.map(fetch,symbols))
    frames=[];limits=[];le=CurrentMarketLimitEngine()
    for symbol,raw,adj in fetched:
        frames.append(adj[['date','symbol','close']].merge(raw[['date','symbol','amount']],on=['date','symbol'],validate='one_to_one'))
        r=raw.loc[raw.date.eq(pd.Timestamp(day))].iloc[0];meta=basic.loc[symbol[-2:].lower()+'.'+symbol[:6]]
        result=le.resolve_current(trade_date=day,symbol=symbol,exchange=symbol[-2:],previous_close=r.preclose,ipo_date=meta.ipoDate,
            trading_days_since_ipo=ipo_trading_day_count(cal,meta.ipoDate,day),is_st=int(r.isST),high=r.high,close=r.close)
        limits.append(dict(symbol=symbol,date=day,status=result.status,rule_source=result.rule_source,calculated_limit_up=result.limit_up_price,actual_close=float(r.close),closed_at_limit_up=result.closed_at_limit_up))
    frame=pd.concat(frames);aligned=align_bars(frame,symbols=symbols,trading_days=days);ret=_returns(aligned);latest=ret.loc[ret.date.eq(days[-1])]
    b=_returns(align_bars(bench,trading_days=days)).set_index('date');snap=sector_snapshot(selected.name,frame,symbols=symbols,trading_days=days)
    n=len(symbols);valid=int(latest.return_1d.notna().sum());cov=valid/n;quality='VALID' if valid==n else 'DATA_INCONSISTENT'
    raw_inputs={}
    for rid,period,value in [('S1','1d',snap.return_1d),('S2','5d',snap.return_5d)]:
        raw_inputs[rid]={f'sector_return_{period}':value,f'benchmark_return_{period}':float(b.iloc[-1]['return_'+period]),f'sector_excess_return_{period}':value-float(b.iloc[-1]['return_'+period]),'coverage':cov,'return_intervals':5}
    raw_inputs['S3']=dict(advancing_constituents=int(latest.return_1d.gt(0).sum()),valid_constituents=valid,expected_constituents=n,breadth=snap.breadth,coverage=cov)
    vl=sum(r['status']=='VALID' for r in limits);lc=sum(r['closed_at_limit_up'] is True for r in limits)
    raw_inputs['S4']=dict(limit_up_count=lc,limit_up_ratio=lc/vl if vl else None,expected_count=n,valid_limit_count=vl,limit_details=limits)
    amounts=[]
    for d in days[-21:]:
        v=aligned.loc[aligned.date.eq(d),'amount'];cv=float(v.notna().sum()/n)
        amounts.append(dict(date=str(d),sector_amount=float(v.sum()),coverage=cv,status='VALID' if cv==1 else 'DATA_INCONSISTENT'))
    raw_inputs['S5']=dict(sector_amount_today=snap.amount,sector_amount_prior_20d_mean=snap.amount_20d_mean,amount_ratio=snap.amount_20d_ratio,coverage=cov,daily_amounts=amounts)
    daily=[]
    for d in days[-5:]:
        v=ret.loc[ret.date.eq(d),'return_1d'];sr=float(v.mean());br=float(b.loc[d,'return_1d']);cv=float(v.notna().sum()/n)
        daily.append(dict(date=str(d),sector_return=sr,benchmark_return=br,sector_win=sr>br,coverage=cv,status='VALID' if cv==1 else 'DATA_INCONSISTENT'))
    raw_inputs['S6']=dict(coverage=cov,daily_comparisons=daily,expected_trade_dates=[r['date'] for r in daily],win_days=sum(r['sector_win'] for r in daily))
    raw_inputs['S7']=dict(strong_count=int(latest.return_1d.ge(.05).sum()),expected_count=n,valid_return_count=valid,strong_ratio=s7_strong_ratio(frame,expected_constituents=symbols,trading_days=days).value)
    provenance=dict(provider='baostock',industry_provider='BaoStockIndustryProvider',trade_date=day,retrieved_at=datetime.now(timezone.utc).isoformat(),expected_count=n,valid_count=valid,network_used=True)
    (out/'scoring_inputs.json').write_text(json.dumps(raw_inputs,ensure_ascii=False,indent=2),encoding='utf-8')
    result=SectorHeatEngine().evaluate(selected.sector_id,selected.name,day,{k:SectorRuleInput(v,day,quality) for k,v in raw_inputs.items()},provenance)
    write_results([result],out)
    print(selected.name,day,result.total_score,result.overall_status,flush=True)
    if result.overall_status!='VALID':raise RuntimeError('Live score incomplete; see details')

if __name__=='__main__':main()
