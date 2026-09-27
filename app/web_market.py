"""Homepage-only index display; the scoring benchmark contract is unchanged."""
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from app.data.baostock_provider import BaoStockProvider

INDEX_CANDIDATES = [('上证指数','sh.000001'),('深证成指','sz.399001'),
                    ('创业板指','sz.399006'),('沪深300','sh.000300'),('科创50','sh.000688')]

def load_index_snapshots():
    def fetch(candidate):
        name,code=candidate
        try:
            provider=BaoStockProvider()
            basic=provider._call('query_stock_basic',code=code)
            verified=basic.loc[basic.code.eq(code) & basic.type.eq('2')]
            if len(verified)!=1:
                return None
            now=pd.Timestamp.now(tz='Asia/Shanghai')
            end=now.normalize().tz_localize(None)-pd.Timedelta(days=int(now.hour<16))
            canonical=code[3:]+'.'+code[:2].upper()
            # Existing bounded SDK adapter; no new adjustment or provider logic.
            bars=provider._history(canonical,end-pd.Timedelta(days=70),end,'raw',index=True)
            if len(bars)<2:return None
            last=bars.iloc[-1]; previous=bars.close.iloc[-2]
            change=float(last.close-previous)
            return dict(name=name,source_name=str(verified.code_name.iloc[0]),symbol=canonical,
                        close=float(last.close),change=change,percent=change/float(previous)*100,
                        date=str(last.date.date()),provider=provider.name,
                        trend=[float(x) for x in bars.close.tail(24)])
        except Exception:
            return None  # No placeholder prices or unverified index identities.
    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for row in pool.map(fetch,INDEX_CANDIDATES) if row is not None]
