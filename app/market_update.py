"""Explicit backend-only daily job. No Web import or implicit full-market run."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
import os

from app.data.cache import DataCache,CacheKey
from app.data.validators import DataValidator
from app.screening.batch_provider import BatchBaoStockProvider
from app.screening.history_cache import HistoryCache
from app.screening.score_cache import ScoreMemo
from app.screening.runtime import RunControl,RuntimeLimits
from app.screening.live import LiveScreeningAdapter
from app.screening.service import ScreeningService
from app.snapshot_publication import target_trade_date,validate_calendar,publish_market_context

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.partial')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)

def read_live_calendar(provider,now):
    from zoneinfo import ZoneInfo
    today=now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    frame=provider.query_trade_dates(today-timedelta(days=45),today)
    rows=[]
    for row in frame.to_dict('records'):
        value=row['is_trading_day']
        if value not in (0,1):raise ValueError('INVALID_CALENDAR_FLAG')
        rows.append(dict(date=str(row['calendar_date'].date()),is_trading_day=bool(value)))
    return validate_calendar(dict(schema_version=1,source='baostock.query_trade_dates',
        provider='baostock',is_mock=False,data_status='VALID',
        retrieved_at=datetime.now(timezone.utc).isoformat(),days=rows))

def daily_update(root,*,execute=False,resume=False,now=None,limits=None,adapter=None):
    """Plan then optionally run full unchanged Stage3C, validate and publish.

    adapter injection is for offline tests only. Production uses actual BaoStock,
    persistent overlap-validated history, score memo and same-day checkpoints.
    Failed/unfinished runs never touch the authoritative current pointer.
    """
    root=Path(root).resolve();now=now or datetime.now(timezone.utc)
    limits=limits or RuntimeLimits()
    control=RunControl(limits);started=perf_counter()
    cache=DataCache(root/'data/cache/market.sqlite3')
    adapter=adapter or LiveScreeningAdapter(cache=cache,control=control,
        history_cache=HistoryCache(root/'data/cache/screening_history.sqlite3',control=control),
        score_memo=ScoreMemo(root/'data/cache/screening_scores.sqlite3',control=control))
    record=dict(schema_version=1,started_at=datetime.now(timezone.utc).isoformat(),
        published=False,status='RUNNING',target_trade_date=None,
        mode='FULL_UNIVERSE_UPDATE' if execute else 'CALENDAR_PLAN_ONLY',
        limits=control.to_dict(),provider=getattr(adapter.provider,'name','UNKNOWN'))
    try:
        calendar=read_live_calendar(adapter.provider,now)
        plan=target_trade_date(calendar,now);record.update(plan)
        record['last_completed_stage']='calendar_plan'
        if plan['status']!='READY' or not execute:
            return record
        day=plan['target_trade_date'];directory=root/'outputs/runtime/market-update'/day
        write_json(directory/'calendar.json',calendar)
        result=ScreeningService(adapter).run(output_dir=directory,resume=resume,runtime_limits=limits)
        record['scan_status']=result['status']
        performance=result.get('performance',{})
        record['performance']={key:performance.get(key,'UNKNOWN') for key in
            ('provider_requests','retry_count','timeout_count','cache_hits','cache_misses','worker_starts')}
        from app.web_diagnostics import error_reason
        record['provider_errors']=[dict(method=e.get('method','UNKNOWN'),
            reason_code=error_reason(RuntimeError(str(e.get('error','')))))
            for e in performance.get('provider_request_errors',[]) if isinstance(e,dict)]
        if result['status']=='DATA_ERROR':
            record.update(status='DATA_ERROR',reason_code='UPDATE_PREPARATION_FAILED');return record
        if result.get('trade_date')!=day:
            record.update(status='DATA_SOURCE_NOT_UPDATED',reason_code='SCAN_TRADE_DATE_MISMATCH');return record
        if not result.get('complete') or result['status'] not in ('COMPLETE','PARTIAL'):
            record.update(status='INCOMPLETE',reason_code='SCAN_NOT_COMPLETE');return record
        # The adapter's same-run validated benchmark is already cached. No
        # independent, potentially different-date benchmark is fabricated.
        key=CacheKey('baostock','000001.SH','2000-01-01',day,'NONE')
        frame=adapter.cache.get(key)
        if frame is None:
            record.update(status='DATA_SOURCE_NOT_UPDATED',reason_code='BENCHMARK_UNAVAILABLE');return record
        frame=DataValidator.validate(frame,suffixes=('',))
        if str(frame.date.max().date())!=day:
            record.update(status='DATA_SOURCE_NOT_UPDATED',reason_code='BENCHMARK_TRADE_DATE_MISMATCH');return record
        path=directory/'benchmark.csv';frame.to_csv(path,index=False)
        epoch=frame.attrs.get('last_updated') or frame.attrs.get('fetched_at')
        if epoch is None:
            record.update(status='DATA_ERROR',reason_code='BENCHMARK_RETRIEVAL_TIME_UNKNOWN');return record
        manifest=dict(provider='baostock',symbol='000001.SH',adjustment_type='NONE',
            is_mock=False,data_status='VALID',trade_date=day,rows=len(frame),
            retrieved_at_epoch=epoch,file=path.relative_to(root).as_posix(),sha256=sha256(path.read_bytes()).hexdigest())
        write_json(directory/'benchmark_manifest.json',manifest)
        generation=publish_market_context(root,(directory/'screening_details.json').relative_to(root).as_posix(),
            (directory/'benchmark_manifest.json').relative_to(root).as_posix(),expected_trade_date=day)
        record.update(status='PUBLISHED',published=True,generation=generation.generation,
            industry_count=len(result['sectors']),stock_count=len(result['stocks']),last_completed_stage='atomic_publication')
        return record
    except Exception as exc:
        # Safe category only. Core result/checkpoint retains upstream evidence
        # locally; it is never echoed or uploaded as an ordinary job log.
        from app.web_diagnostics import error_reason
        record.update(status='DATA_ERROR',reason_code=error_reason(exc),error_type=type(exc).__name__)
        return record
    finally:
        try:adapter.close()
        finally:
            record.update(total_seconds=round(perf_counter()-started,4),
                          completed_at=datetime.now(timezone.utc).isoformat())
            write_json(root/'outputs/runtime/market-update/latest_attempt.json',record)
