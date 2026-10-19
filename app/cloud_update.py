"""Opt-in hosted slices of the existing full-market scan; never a Web task."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import time

from app.cloud_state import fingerprint, pack_state, unpack_state, safe_bytes
from app.data.cache import CacheKey, DataCache
from app.data.validators import DataValidator
from app.market_update import read_live_calendar, write_json
from app.screening.history_cache import HistoryCache
from app.screening.score_cache import ScoreMemo
from app.screening.live import LiveScreeningAdapter
from app.screening.runtime import RunControl, RuntimeLimits
from app.screening.service import ScreeningService
from app.snapshot_publication import target_trade_date, publish_market_context


def source_revision(root):
    try:
        revision=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,
                                check=True,timeout=5,text=True).stdout.strip()
        return revision if re.fullmatch('[a-f0-9]{40}',revision) else 'UNKNOWN'
    except (OSError,subprocess.SubprocessError):
        return 'UNKNOWN'


def publication_gate(result, day):
    """Transport/completeness gate, not a new strategy or coverage threshold.

Legitimate model/data insufficiency remains explicit, not a fabricated zero.
Operational errors, stale or inconsistent inputs can never publish a generation.
The authoritative publisher still performs its full independent validation.
"""
    if (result.get('trade_date')!=day or not result.get('complete')
            or result.get('status') not in ('COMPLETE','PARTIAL')
            or result.get('is_mock') is not False or result.get('mode')!='live'
            or result.get('operational_limit_industries') is not None):
        raise ValueError('CLOUD_INCOMPLETE_RESULT')
    if any(e.get('error')!='SLICE_BOUNDARY_PAUSE' for e in result.get('errors', [])):
        raise ValueError('CLOUD_OPERATIONAL_ERRORS')
    for row in result['sectors']+result['stocks']:
        if row.get('error') or row.get('data_status') in ('DATA_ERROR','DATA_STALE','DATA_INCONSISTENT'):
            raise ValueError('CLOUD_UNSAFE_INPUTS')


def finish_publication(root, directory, adapter, result, day):
    publication_gate(result, day)
    frame=adapter.cache.get(CacheKey('baostock','000001.SH','2000-01-01',day,'NONE'))
    if frame is None:
        raise ValueError('CLOUD_BENCHMARK_MISSING')
    frame=DataValidator.validate(frame, suffixes=('',))
    epoch=frame.attrs.get('last_updated') or frame.attrs.get('fetched_at')
    if str(frame.date.max().date())!=day or epoch is None:
        raise ValueError('CLOUD_BENCHMARK_DATE_OR_PROVENANCE')
    path=directory/'benchmark.csv'
    frame.to_csv(path, index=False)
    write_json(directory/'benchmark_manifest.json', dict(
        provider='baostock', symbol='000001.SH', adjustment_type='NONE', is_mock=False,
        data_status='VALID', trade_date=day, rows=len(frame), retrieved_at_epoch=epoch,
        file=path.relative_to(root).as_posix(), sha256=sha256(path.read_bytes()).hexdigest()))
    return publish_market_context(root, (directory/'screening_details.json').relative_to(root).as_posix(),
        (directory/'benchmark_manifest.json').relative_to(root).as_posix(), expected_trade_date=day)


def run_slice(root, *, slice_index, producer, bundle=None, run_seconds=14400, now=None, adapter_factory=None):
    """One serial slice, <=4h compute + export. No remote writes or Git operations.

Different-day seed: caches only. Same-day seed: exact universe/policy checkpoint
resume. A dated cache never becomes VALID merely because it was transported.
"""
    if slice_index not in (1,2,3,4) or not 2400 <= run_seconds <= 14400:
        raise ValueError('CLOUD_SLICE_BUDGET_INVALID')
    root=Path(root).resolve()
    base=root/'outputs/runtime/cloud-update'
    work=base/('work-'+str(slice_index))
    code=fingerprint(root)
    started=time.monotonic()
    report=dict(schema_version=1, status='RUNNING', published=False, slice=slice_index,
                source_fingerprint=code, producer=str(producer), provider='baostock',
                source_revision=source_revision(root),last_completed_stage='NONE',
                started_at=datetime.now(timezone.utc).isoformat(), cloud_verified=False,
                cache_seed='MISS', target_trade_date=None)
    adapter=None
    try:
        seed=None
        if bundle and Path(bundle).exists():
            seed=unpack_state(bundle, work, source_fingerprint=code)
            report['cache_seed']='RESTORED_NOT_YET_VALIDATED'
            report['last_completed_stage']='state_transport_validation'
        else:
            if slice_index!=1:
                raise ValueError('CLOUD_PREVIOUS_SLICE_MISSING')
            work.mkdir(parents=True, exist_ok=False)
        limits=RuntimeLimits(run_seconds=run_seconds)
        control=RunControl(limits)
        cache=DataCache(work/'cache/market.sqlite3')
        adapter=(adapter_factory(cache,control) if adapter_factory else LiveScreeningAdapter(
            cache=cache, control=control,
            history_cache=HistoryCache(work/'cache/screening_history.sqlite3',control=control),
            score_memo=ScoreMemo(work/'cache/screening_scores.sqlite3',control=control)))
        calendar=read_live_calendar(adapter.provider, now or datetime.now(timezone.utc))
        plan=target_trade_date(calendar, now or datetime.now(timezone.utc))
        report.update(plan)
        report['last_completed_stage']='calendar_plan'
        day=plan['target_trade_date']
        directory=work/'run'
        continuing=False
        if seed and seed['trade_date']==day and (directory/'checkpoint.json').exists():
            saved=json.loads((directory/'checkpoint.json').read_text('utf-8'))
            continuing=saved['result'].get('status')=='STOPPED' and not saved['result'].get('complete')
        if plan['status']!='READY' and not (continuing and plan['status'] in ('NON_TRADING_DAY','MARKET_NOT_CLOSED')):
            return report
        report['calendar_state']=plan['status']
        if slice_index>1 and (not seed or seed['trade_date']!=day):
            raise ValueError('CLOUD_SLICE_CROSSED_TRADE_DATE')
        if seed and seed['trade_date']!=day and directory.exists():
            # Keep the immutable old checkpoint for audit, never resume it under
            # a new trade date. Only its caches can participate in validation.
            directory.rename(work/'previous-run-not-used')
        write_json(directory/'calendar.json', calendar)
        result=ScreeningService(adapter).run(output_dir=directory,
            resume=(directory/'checkpoint.json').exists(), runtime_limits=limits,
            boundary_reserve_seconds=120)
        report.update(scan_status=result['status'], complete=result.get('complete',False), stats=result.get('stats',{}))
        report['last_completed_stage']='scan_slice'
        metrics=adapter.metrics()
        report['performance']={k:metrics.get(k,'UNKNOWN') for k in (
            'provider_requests','retry_count','timeout_count','cache_hits','cache_misses','history_cache')}
        if result.get('trade_date')!=day:
            raise ValueError('CLOUD_SCAN_TRADE_DATE_MISMATCH')
        if result.get('complete'):
            publication_gate(result,day)
        elif result.get('status')=='STOPPED':
            report['status']='PAUSED' if slice_index<4 else 'BUDGET_EXHAUSTED'
        else:
            raise ValueError('CLOUD_SCAN_FAILED')
        # status.json is also a public artifact. Validate untrusted metrics
        # before exporting state or switching a formal snapshot pointer.
        safe_bytes(json.dumps(report, ensure_ascii=False, allow_nan=False).encode())
        report['state']=pack_state(work, base/'transfer/state.jsonl.gz',
            source_fingerprint=code, trade_date=day, producer=producer,
            frame_cutoff_epoch=time.time()-cache.ttl)
        report['last_completed_stage']='state_export'
        if result.get('complete'):
            published=finish_publication(root,directory,adapter,result,day)
            report.update(status='PUBLISHED_LOCALLY',published=True,generation=published.generation)
            report['last_completed_stage']='atomic_publication'
        return report
    except Exception as exc:
        from app.web_diagnostics import error_reason
        # Never serialize upstream exception text, query parameters or paths.
        report.update(status='BLOCKED', reason_code=error_reason(exc), error_type=type(exc).__name__)
        if isinstance(exc, ValueError) and str(exc).startswith(('CLOUD_', 'STATE_')):
            report['reason_code']=str(exc) if str(exc).replace('_','').isalnum() else 'CLOUD_VALIDATION_REJECTED'
        return report
    finally:
        if adapter:
            try:
                adapter.close()
            except Exception as exc:
                report.update(status='BLOCKED',cleanup_error_type=type(exc).__name__,reason_code='CLOUD_CLEANUP_FAILED')
        report.update(total_seconds=round(time.monotonic()-started,4),
                      completed_at=datetime.now(timezone.utc).isoformat())
        try:
            safe_bytes(json.dumps(report, ensure_ascii=False, allow_nan=False).encode())
        except (ValueError, TypeError, RecursionError):
            # Explicit failure, not a sanitized "successful" result. Never
            # persist the unsafe metrics/identities even on an early return.
            report.clear()
            report.update(schema_version=1, status='BLOCKED', published=False,
                          reason_code='STATE_PRIVATE_OR_INVALID_REPORT_REJECTED',
                          cloud_verified=False)
        write_json(base/'status.json',report)
        # Compatibility only with the existing CI publication tool. No push is
        # performed here. Its separate main-only workflow step is opt-in.
        write_json(root/'outputs/runtime/market-update/latest_attempt.json',report)
