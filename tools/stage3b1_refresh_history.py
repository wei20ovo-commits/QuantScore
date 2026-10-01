"""Reacquire truncated remote history in bounded chunks; never fill missing bars."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.data.cache import DataCache,CacheKey
from app.data.validators import DataValidator

def main():
    p=BaoStockProvider(timeout=150);cache=DataCache();records=[];frames={}
    symbol='600258.SH';end=pd.Timestamp.now(tz='Asia/Shanghai').normalize().tz_localize(None);start=pd.Timestamp('2000-01-01')
    for adjustment in ['raw','qfq']:
        chunks=[]
        for year in range(2000,2027,4):
            a=pd.Timestamp(f'{year}-01-01');b=min(pd.Timestamp(f'{year+3}-12-31'),end)
            for attempt in range(3):
                try:
                    df=p.fetch_stock_daily(symbol,a,b,adjustment);break
                except Exception:
                    if attempt==2:raise
            chunks.append(df);records.append(dict(symbol=symbol,adjustment=adjustment,start=str(a),end=str(b),rows=len(df),provider='baostock'))
            print(records[-1],flush=True)
        frames[adjustment]=pd.concat(chunks,ignore_index=True)
    DataValidator.align_raw_qfq(frames['raw'],frames['qfq'])
    assert frames['raw'].date.max()==end
    for adjustment,frame in frames.items():cache.put(CacheKey('baostock',symbol,str(start),str(end),adjustment),frame)
    (ROOT/'outputs/stage3b1/history_reacquisition.json').write_text(json.dumps(records,indent=2),encoding='utf-8')

if __name__=='__main__':main()
