"""Bounded real network proof, separate from the recorded-data benchmark."""
from pathlib import Path
import json
import sys
import time
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.screening.batch_provider import BatchBaoStockProvider
from app.screening.history_cache import HistoryCache
from app.screening.runtime import RunControl,RuntimeLimits


def main():
    out=ROOT/'outputs/stage3c1';out.mkdir(parents=True,exist_ok=True)
    control=RunControl(RuntimeLimits(request_seconds=30,run_seconds=600))
    p=BatchBaoStockProvider(timeout=30);p.control=control
    requests=[];original=p._call
    def counted(method,**kwargs):
        before=time.monotonic();record=dict(method=method,parameters=kwargs,status='RUNNING')
        requests.append(record)
        try:
            data=original(method,**kwargs)
            record.update(status='VALID',rows=len(data))
            return data
        except Exception as exc:
            record.update(status='DATA_ERROR',error=str(exc));raise
        finally:record['seconds']=time.monotonic()-before
    p._call=counted
    report=dict(is_mock=False,mode='live-network',provider='baostock',status='RUNNING',requests=requests,phases=[])
    try:
        meta=p.query_stock_basic('600519.SH')
        report['stock_name']=str(meta.code_name.iloc[0])
        run_id=pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%S%f')
        h=HistoryCache(out/f'live_history_{run_id}.sqlite3',control=control)
        report['cache_run_id']=run_id
        operations=[('600519.SH','raw'),('600519.SH','qfq'),('000001.SH','NONE')]
        for phase,day in [('cold','2026-09-29'),('warm','2026-09-29'),('incremental','2026-09-30')]:
            before=len(requests);start=time.monotonic()
            for symbol,mode in operations:
                call=(lambda a,b:p.fetch_benchmark(a,b)) if mode=='NONE' else (lambda a,b,s=symbol,m=mode:p.fetch_stock_daily(s,a,b,m))
                frame=h.fetch(p.name,symbol,mode,'2026-07-12',day,call)
                frame.to_csv(out/f'live_{phase}_{symbol}_{mode}.csv',index=False)
                report['phases'].append(dict(phase=phase,symbol=symbol,adjustment=mode,
                    requested_end=day,actual_last_date=str(frame.date.max().date()),rows=len(frame),
                    cache_metadata=dict(frame.attrs)))
            report.setdefault('timings',{})[phase]=dict(seconds=time.monotonic()-start,requests=len(requests)-before)
        report['cache_metrics']=h.metrics
        report['status']='PASS'
    except Exception as exc:
        report.update(status='PARTIAL',error=str(exc))
    finally:
        p.close()
        report['retrieved_at']=pd.Timestamp.now(tz='UTC').isoformat()
        (out/'live_cache_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)

if __name__=='__main__':main()
