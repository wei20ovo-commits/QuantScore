"""Opt-in real network probe: <=5 sequential SDK calls, <=120s, no retries.

This is a network/schema probe, NOT a full-market update or a scoring result.
An empty, stale or malformed response is a failure, never synthetic evidence.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import pandas as pd
    from app.screening.batch_provider import BatchBaoStockProvider
    from app.screening.runtime import RunControl, RuntimeLimits
    from app.market_update import write_json
    from app.web_diagnostics import error_reason
    from app.snapshot_publication import target_trade_date
    from app.market_update import read_live_calendar
    from app.data.validators import DataValidator
    provider=BatchBaoStockProvider(timeout=20)
    provider.control=RunControl(RuntimeLimits(request_seconds=20,run_seconds=120,max_attempts=1))
    report=dict(schema_version=1,provider='baostock',hosted=os.getenv('GITHUB_ACTIONS')=='true',
                calls=[],budget=dict(maximum_sdk_calls=5,run_seconds=120,request_seconds=20,retries=0),
                started_at=datetime.now(timezone.utc).isoformat(),status='RUNNING')
    start=time.monotonic()
    count=0
    call=provider._call
    def measured(method,**kwargs):
        nonlocal count
        count+=1
        if count>5:
            raise RuntimeError('PROBE_REQUEST_BUDGET_EXCEEDED')
        t=time.monotonic()
        event=dict(method=method,status='FAILURE')
        try:
            frame=call(method,**kwargs)
            if frame.empty:
                raise ValueError('PROBE_EMPTY_DATA')
            event.update(status='SUCCESS',rows=len(frame))
            return frame
        except Exception as exc:
            event.update(reason_code=error_reason(exc),error_type=type(exc).__name__)
            raise
        finally:
            event['seconds']=round(time.monotonic()-t,4)
            report['calls'].append(event)
    provider._call=measured
    try:
        now=datetime.now(timezone.utc)
        calendar=read_live_calendar(provider,now)
        plan=target_trade_date(calendar,now)
        day=plan['target_trade_date']
        if not day:
            raise ValueError('PROBE_CALENDAR_TARGET_UNKNOWN')
        report.update(trade_date=day,calendar_state=plan['status'])
        members=provider._call('query_stock_industry')
        if not {'code','industry','industryClassification'}<=set(members):
            raise ValueError('PROBE_MEMBERSHIP_SCHEMA')
        lower=(pd.Timestamp(day)-timedelta(days=20)).date().isoformat()
        raw=provider.fetch_stock_daily('600519.SH',lower,day,'raw')
        adj=provider.fetch_stock_daily('600519.SH',lower,day,'qfq')
        index=provider.fetch_benchmark(lower,day)
        if not raw.date.equals(adj.date) or any(str(f.date.max().date())!=day for f in (raw,adj,index)):
            raise ValueError('PROBE_DATE_ALIGNMENT')
        for frame in (raw,adj,index):
            DataValidator.validate(frame,suffixes=('',))
        if not {'volume','turnover_rate'}<=set(raw):
            raise ValueError('PROBE_STOCK_FIELDS')
        report.update(status='PASS',coverage='calendar/membership/600519 raw+qfq/000001.SH only')
    except Exception as exc:
        report.update(status='FAILURE',reason_code=error_reason(exc),error_type=type(exc).__name__)
    finally:
        provider.close()
        report.update(actual_sdk_calls=count,seconds=round(time.monotonic()-start,4),
                      completed_at=datetime.now(timezone.utc).isoformat())
        write_json(ROOT/'outputs/free_cloud/provider_probe.json',report)
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
