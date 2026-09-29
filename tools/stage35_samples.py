from pathlib import Path
import sys,json,requests
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.data.baostock_provider import BaoStockProvider
OUT=ROOT/'outputs/stage35';RAW=OUT/'samples';RAW.mkdir(exist_ok=True)
SYMBOLS=['600418.SH','002342.SZ','301190.SZ','688244.SH','600519.SH','000001.SZ','300750.SZ','688981.SH','600165.SH','603018.SH','301369.SZ']
def main():
 url='https://qt.gtimg.cn/q='+','.join(s[-2:].lower()+s[:6] for s in SYMBOLS)
 r=requests.get(url,timeout=30);r.raise_for_status();(RAW/'tencent_quotes.txt').write_bytes(r.content);(RAW/'tencent_url.txt').write_text(url)
 p=BaoStockProvider(timeout=45)
 def one(s):
  for attempt in range(3):
   try:
    d=p.fetch_stock_daily(s,'2026-09-01','2026-09-29','raw');d.to_csv(RAW/(s+'.csv'),index=False);print(s,len(d),flush=True);return
   except Exception as e:print(s,attempt,type(e).__name__,flush=True)
 with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(one,SYMBOLS))
if __name__=='__main__':main()
