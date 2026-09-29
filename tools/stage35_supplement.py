"""Live supplemental requests; keep original attempts and source responses."""
from pathlib import Path
import sys, json
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
import requests
from bs4 import BeautifulSoup
from app.data.baostock_provider import BaoStockProvider
from app.data.cache import CacheKey, DataCache

def main():
    out = ROOT / 'outputs/stage35'
    p = BaoStockProvider(timeout=45)
    logs = pd.read_csv(out / 'fetch_log.csv').to_dict('records')
    for attempt in range(4, 7):
        try:
            f = p.fetch_stock_daily('601007.SH', '2026-04-22', '2026-09-29', 'qfq')
            f.to_csv(out / 'raw/601007.SH_qfq.csv', index=False)
            logs.append(dict(request='601007.SH:qfq', attempt=attempt, status='SUCCESS', retrieved_at=datetime.now(timezone.utc).isoformat(), rows=len(f)))
            break
        except Exception as e:
            logs.append(dict(request='601007.SH:qfq', attempt=attempt, status='DATA_ERROR', retrieved_at=datetime.now(timezone.utc).isoformat(), error=str(e)))
        finally:
            pd.DataFrame(logs).to_csv(out / 'fetch_log.csv', index=False)
    for code, aid in [('603018','12601356'), ('301369','12608826')]:
        url = f'https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id={aid}&stockid={code}'
        r = requests.get(url, timeout=30); r.raise_for_status(); r.encoding='gb18030'
        (out / f'sources/issuer_{code}.html').write_text(r.text, encoding='utf-8')
        soup = BeautifulSoup(r.text, 'html.parser')
        (out / f'sources/issuer_{code}.txt').write_text(soup.get_text('\n', strip=True), encoding='utf-8')
        links = [a['href'] for a in soup.select('a[href]') if '.pdf' in a['href'].lower()]
        for u in links[:1]:
            rr=requests.get(u,timeout=30); rr.raise_for_status()
            (out / f'sources/issuer_{code}.pdf').write_bytes(rr.content)
        symbol = ('sh' if code=='603018' else 'sz') + code
        u = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,2026-09-01,2026-09-29,60,'
        rr=requests.get(u,timeout=30); rr.raise_for_status()
        (out / f'sources/tencent_history_{code}.json').write_text(rr.text,encoding='utf-8')
        (out / f'sources/exdiv_{code}_urls.json').write_text(json.dumps(dict(announcement=url,pdf=links[:1],history=u),indent=2),encoding='utf-8')
        print(code, rr.text[:150], flush=True)
    u='https://qt.gtimg.cn/q=sh600107,sz002193'
    r=requests.get(u,timeout=30);r.raise_for_status()
    (out/'samples/tencent_st_quotes.txt').write_bytes(r.content)
    (out/'samples/tencent_st_url.txt').write_text(u)
    # A genuine force refresh needs a second provider invocation, not just a cache miss.
    key=CacheKey('baostock','600519.SH','2026-09-01','2026-09-28','raw')
    cache=DataCache(out / ('cache_'+datetime.now().strftime('%H%M%S')+'.sqlite3'))
    rows=[]
    for phase in ('first_fetch','cache_hit','force_refresh_fetch'):
        frame=cache.get(key,force_refresh=phase=='force_refresh_fetch')
        fetched=frame is None
        if fetched:
            frame=p.fetch_stock_daily(key.symbol,key.start_date,key.end_date,'raw')
            if frame.empty:raise RuntimeError('Empty cache evidence is not acceptable')
            cache.put(key,frame)
        rows.append(dict(phase=phase,provider='baostock',symbol=key.symbol,provider_fetch=fetched,cache_hit=not fetched,rows=len(frame),as_of=str(frame.date.max()),retrieved_at=datetime.now(timezone.utc).isoformat()))
    pd.DataFrame(rows).to_csv(out/'cache_verification.csv',index=False)
    print(rows,flush=True)

if __name__=='__main__':main()
