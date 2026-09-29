"""Fresh Stage 3A.5 evidence, never copied from earlier runs."""
from pathlib import Path
import sys,json,time
from datetime import date,datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.sector.providers import canonical_symbol
OUT=ROOT/'outputs/stage35';RAW=OUT/'raw';RAW.mkdir(parents=True,exist_ok=True)
def stamp():return datetime.now(timezone.utc).isoformat()
def main():
 p=BaoStockProvider(timeout=45);end=date.today();start=end-timedelta(days=160)
 logs=[]
 def call(label,fn):
  for attempt in range(1,4):
   try:
    d=fn();logs.append(dict(request=label,attempt=attempt,status='SUCCESS',retrieved_at=stamp(),rows=len(d)));return d
   except Exception as e:
    logs.append(dict(request=label,attempt=attempt,status='DATA_ERROR',retrieved_at=stamp(),error=str(e)))
  return None
 industry=call('query_stock_industry',lambda:p._call('query_stock_industry'))
 if industry is None:raise RuntimeError('industry unavailable')
 industry.to_csv(RAW/'industry.csv',index=False)
 industry['symbol']=industry.code.map(canonical_symbol)
 valid=industry[industry.industry.fillna('').str.strip().ne('') & industry.symbol.str.endswith(('.SH','.SZ'))].copy()
 selected=valid[valid.industry.str.match(r'^(H61|C25|C18)')].drop_duplicates('symbol').copy()
 selected.to_csv(OUT/'membership.csv',index=False)
 if selected.empty:raise RuntimeError('selected industries missing')
 basic=call('query_stock_basic',lambda:p.query_stock_basic());basic.to_csv(RAW/'security_metadata.csv',index=False)
 cal=call('query_trade_dates',lambda:p.query_trade_dates('1990-01-01',end));cal.to_csv(RAW/'calendar.csv',index=False)
 benchmark=call('benchmark',lambda:p.fetch_benchmark(start,end));benchmark.to_csv(RAW/'benchmark.csv',index=False)
 print('Fresh membership:',len(industry),len(valid),valid.industry.nunique(),selected.groupby('industry').size().to_dict(),flush=True)
 def fetch(symbol):
  result={}
  for adj in ['raw','qfq']:
   d=call(symbol+':'+adj,lambda:p.fetch_stock_daily(symbol,start,end,adj))
   if d is not None:d.to_csv(RAW/(symbol+'_'+adj+'.csv'),index=False)
   result[adj]=None if d is None else len(d)
  print(symbol,result,flush=True);return result
 with ThreadPoolExecutor(max_workers=4) as pool:
  futures=[pool.submit(fetch,s) for s in sorted(selected.symbol.unique())]
  for f in as_completed(futures):f.result()
 pd.DataFrame(logs).to_csv(OUT/'fetch_log.csv',index=False)
 (OUT/'fetch_metadata.json').write_text(json.dumps(dict(retrieved_at=stamp(),requested_end=str(end),requested_start=str(start),industry_count=int(valid.industry.nunique()),industry_raw_count=len(industry),valid_memberships=len(valid),selected_memberships=len(selected),cache_used=False),indent=2),encoding='utf-8')
if __name__=='__main__':main()
