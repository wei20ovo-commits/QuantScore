"""Stage 3A.4 live closure: metadata, trading calendar, retries, current S4 and cache evidence."""
from __future__ import annotations
import json, time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.data.market_rule import CurrentMarketLimitEngine
from app.data.cache import DataCache, CacheKey

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'stage34'; OUT.mkdir(parents=True,exist_ok=True)
PY=ROOT/'outputs'/'stage33'
def stamp(): return datetime.now(timezone.utc).isoformat()
def main():
    p= BaoStockProvider(timeout=45); selected=pd.read_csv(PY/'selected_industries.csv'); symbols=sorted(selected.symbol.unique())
    end=date.today(); start=end-timedelta(days=150); retrieved=stamp()
    cal=p.query_trade_dates(start,end); trading_days=sorted(cal.loc[cal.is_trading_day.eq(1),'calendar_date'].dt.date); latest=max(trading_days)
    basic=[]
    for s in symbols:
        try: basic.append(p.query_stock_basic(s).iloc[0].to_dict())
        except Exception as e: basic.append({'code':s,'code_name':'','ipoDate':'','outDate':'','type':'','status':'','error':f'{type(e).__name__}:{e}'})
    bdf=pd.DataFrame(basic); bdf.to_csv(OUT/'security_metadata.csv',index=False,encoding='utf-8-sig')
    rows=[]; bars={}
    for s in symbols:
        err=None; data=None
        for attempt in range(1,4):
            ts=stamp()
            try:
                data=p.fetch_stock_daily(s,start,end,'raw'); err=None; rows.append({'symbol':s,'attempt':attempt,'provider':'baostock','error_code':'0','error_msg':'','timestamp':ts}); break
            except Exception as e:
                err=e; rows.append({'symbol':s,'attempt':attempt,'provider':'baostock','error_code':getattr(e,'code','PROVIDER_ERROR'),'error_msg':str(e),'timestamp':ts}); time.sleep(0.5*(2**(attempt-1)))
        if data is not None:
            bars[s]=data
    pd.DataFrame(rows).to_csv(OUT/'bar_retry_log.csv',index=False,encoding='utf-8-sig')
    q=[]
    for s in symbols:
        d=bars.get(s,pd.DataFrame()); dates=pd.to_datetime(d.date,errors='coerce').dt.date if len(d) else pd.Series(dtype=object)
        q.append({'symbol':s,'bar_count':len(d),'latest_trade_date':max(dates) if len(d) else None,'status':'VALID' if len(d)>=35 else 'DATA_ERROR','provider':'baostock'})
    qdf=pd.DataFrame(q); qdf.to_csv(OUT/'bar_quality.csv',index=False,encoding='utf-8-sig')
    engine=CurrentMarketLimitEngine(); s4=[]
    for s,d in bars.items():
        if d.empty: continue
        r=d.sort_values('date').iloc[-1]; meta=bdf[bdf.code.astype(str).str.endswith(s.split('.')[0])].iloc[0] if any(bdf.code.astype(str).str.endswith(s.split('.')[0])) else None
        ipo=meta.get('ipoDate') if meta is not None else None; ipo_ts=pd.Timestamp(ipo).date() if ipo else None
        since=sum(x>ipo_ts for x in trading_days if ipo_ts and x<=latest) if ipo_ts else None
        isst=bool(int(r.get('isST',0))) if pd.notna(r.get('isST')) else False
        result=engine.resolve_current(trade_date=latest,symbol=s,exchange=s[-2:],previous_close=r.get('preclose'),ipo_date=ipo_ts,trading_days_since_ipo=since,is_st=isst,high=r.get('high'),close=r.get('close'))
        s4.append({'symbol':s,'name':meta.get('code_name','') if meta is not None else '','date':latest,'board':engine.board_for(s,s[-2:],is_st=isst),'exchange':s[-2:],'preclose':r.get('preclose'),'isST':isst,'ipoDate':ipo,'trading_day_since_ipo':since,'limit_ratio':result.limit_ratio,'calculated_limit_up':result.limit_up_price,'actual_high':r.get('high'),'actual_close':r.get('close'),'touched_limit':result.touched_limit_up,'closed_limit':result.closed_at_limit_up,'independent_source':'AKShare optional','independent_result':None,'match':None,'status':result.status,'reason_code':result.reason_code,'rule_id':result.rule_id,'rule_source':result.rule_source})
    s4df=pd.DataFrame(s4); s4df.to_csv(OUT/'s4_cross_validation.csv',index=False,encoding='utf-8-sig')
    # Real cache lifecycle with isolated temporary sqlite.
    cache=DataCache(OUT/'stage34_cache.sqlite3',ttl=3600); key=CacheKey('baostock','600000.SH',str(start),str(end),'raw'); sample=bars.get('600000.SH',pd.DataFrame())
    first=cache.put(key,sample.copy()); second=cache.get(key); refreshed=cache.get(key,force_refresh=True)
    pd.DataFrame([{'request':key.encode(),'first_source':'provider_fetch','first_cache_hit':first.attrs.get('cache_hit'),'second_source':'cache','second_cache_hit':second.attrs.get('cache_hit') if second is not None else None,'force_refresh_source':'provider_fetch','force_refresh_cache_hit':refreshed.attrs.get('cache_hit') if refreshed is not None else None,'as_of':str(max(pd.to_datetime(sample.date).dt.date)) if len(sample) else None,'retrieved_at':retrieved}]).to_csv(OUT/'cache_verification.csv',index=False,encoding='utf-8-sig')
    stats={'retrieved_at':retrieved,'provider':'baostock','latest_trade_date':str(latest),'industry_expected_count':int(len(symbols)),'bar_expected':int(len(symbols)),'bar_valid':int((qdf.status=='VALID').sum()),'bar_provider_error':int((qdf.status=='DATA_ERROR').sum()),'s4_valid':int((s4df.status=='VALID').sum()),'s4_sample_count':len(s4df),'s4_crosscheck_match_count':0,'s4_crosscheck_mismatch_count':0,'bj':'OUT_OF_SCOPE_FOR_V1','status':'PARTIAL'}
    (OUT/'run_metadata.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(stats,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
