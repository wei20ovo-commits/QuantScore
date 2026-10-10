"""Allowlisted Web worker diagnostics; never serialize exception messages."""
from contextvars import ContextVar
import json
import logging
import math
import re
from time import perf_counter
from app.data.models import DataError

_sink = ContextVar('web_diagnostic_sink', default=None)
_request = ContextVar('web_request_id', default=None)
_log = logging.getLogger(__name__)
STAGES = {'worker', 'service_init', 'security_resolve', 'security_lookup',
          'security_list', 'stock_raw_qfq_fetch', 'provider_request', 'market_fetch',
          'industry_context_load', 'rule_scoring', 'analysis', 'chart_data', 'cache',
          'context', 'fetch_group', 'fetch_attempt', 'fetch_retry'}
REASONS = {'NONE', 'PROVIDER_TIMEOUT', 'PROVIDER_CONNECTION_ERROR', 'PROVIDER_PROXY_ERROR',
           'PROVIDER_LOGIN_ERROR', 'PROVIDER_INCOMPLETE_PAGINATION', 'PROVIDER_SDK_ERROR',
           'PROVIDER_UNAVAILABLE', 'DATA_VALIDATION_ERROR', 'RAW_QFQ_DATE_MISMATCH',
           'FIELD_GROUP_DATE_MISMATCH', 'WORKER_ERROR', 'WORKER_RESPONSE_INVALID',
           'WEB_DEADLINE_EXCEEDED', 'DATA_UNAVAILABLE', 'INVALID_PRICE_VALUES',
           'INVALID_OHLC_RELATION', 'EMPTY_MARKET_DATA',
           'BENCHMARK_SNAPSHOT_UNAVAILABLE','BENCHMARK_SNAPSHOT_DATA_STALE',
           'BENCHMARK_SNAPSHOT_DATA_ERROR','BENCHMARK_SNAPSHOT_DATA_INCONSISTENT',
           'BENCHMARK_SNAPSHOT_PROVIDER_MISMATCH'}
METHODS = {'query_stock_basic', 'query_history_k_data_plus', 'query_trade_dates',
           'stock_zh_a_hist', 'stock_info_sh_name_code', 'stock_info_sz_name_code'}


def allowed(value,values): return isinstance(value,str) and value in values


def error_reason(exc):
    """Classify locally, discard all messages/URLs/paths/credentials."""
    chain = []; seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc)); chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    names = {type(e).__name__ for e in chain}
    text = ' '.join(str(e)[:4000].lower() for e in chain)
    if 'SnapshotUnavailable' in names:
        return next((r for r in sorted(REASONS) if r.startswith('BENCHMARK_SNAPSHOT_') and r.lower() in text),
                    'BENCHMARK_SNAPSHOT_UNAVAILABLE')
    if 'ProxyError' in names or 'proxyerror' in text: return 'PROVIDER_PROXY_ERROR'
    if names & {'TimeoutError', 'Timeout', 'ReadTimeout', 'ConnectTimeout', 'RuntimeDeadline'} or any(t in text for t in ('deadline', 'timeout', '超时')):
        return 'PROVIDER_TIMEOUT'
    if names & {'ConnectionError', 'ConnectionResetError', 'ConnectionRefusedError', 'BrokenPipeError', 'EOFError'} or 'connection' in text:
        return 'PROVIDER_CONNECTION_ERROR'
    if 'login error' in text: return 'PROVIDER_LOGIN_ERROR'
    if 'incomplete pagination' in text: return 'PROVIDER_INCOMPLETE_PAGINATION'
    if 'raw/qfq' in text and '交易日' in text: return 'RAW_QFQ_DATE_MISMATCH'
    if 'field groups have inconsistent dates' in text: return 'FIELD_GROUP_DATE_MISMATCH'
    if '价格包含缺失值、非有限值或非正值' in text: return 'INVALID_PRICE_VALUES'
    if 'ohlc 高低价关系非法' in text: return 'INVALID_OHLC_RELATION'
    if '行情为空' in text: return 'EMPTY_MARKET_DATA'
    if 'DataError' in names: return 'DATA_VALIDATION_ERROR'
    if 'ProviderError' in names: return 'PROVIDER_UNAVAILABLE'
    return 'WORKER_ERROR'


def valid_request_id(value):
    return value if isinstance(value,str) and re.fullmatch('[0-9a-f]{32}',value) else None


def bind_request(value): return _request.set(valid_request_id(value))
def reset_request(token): _request.reset(token)
def current_request(): return _request.get()


def safe_event(stage, status, *, seconds=0, reason_code='NONE', provider=None,
               method=None, adjustment=None, request_id=None, stock_trade_date=None,
               industry_snapshot_date=None, benchmark_snapshot_date=None):
    value = {'stage': stage if allowed(stage,STAGES) else 'worker',
             'status': status if allowed(status,{'START', 'OK', 'FAILED', 'UNAVAILABLE', 'TIMEOUT'}) else 'FAILED',
             'reason_code': reason_code if allowed(reason_code,REASONS) else 'WORKER_ERROR',
             'seconds': round(float(seconds), 4) if isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds >= 0 else 0}
    if allowed(provider,{'baostock', 'akshare', 'tushare'}): value['provider'] = provider
    if allowed(method,METHODS): value['method'] = method
    if allowed(adjustment,{'raw', 'qfq', 'NONE', 'limits', 'basic', 'verified_security', 'validated_securities'}):
        value['adjustment'] = adjustment
    rid = valid_request_id(request_id) or current_request()
    if rid: value['request_id'] = rid
    for key,day in [('stock_trade_date',stock_trade_date),('industry_snapshot_date',industry_snapshot_date),
                    ('benchmark_snapshot_date',benchmark_snapshot_date)]:
        if date_only(day): value[key] = day
    return value


def emit(event):
    # Reconstruct instead of trusting callers or an exception's attributes.
    event = safe_event(event.get('stage'), event.get('status'),
                       **{k: event[k] for k in EVENT_FIELDS if k in event})
    sink = _sink.get()
    if sink is not None:
        try: sink(event)
        except Exception: pass  # Diagnostics never decide data/score.
    # Cloud commonly filters INFO. All allowlisted operational events and the
    # terminal summary use WARNING transport level without changing root logging.
    try: _log.warning('QUANTSCORE_WEB_DIAGNOSTIC %s', json.dumps(event, sort_keys=True))
    except Exception: pass
    return event


def bind_sink(sink): return _sink.set(sink)
def reset_sink(token): _sink.reset(token)


def trace_call(events, stage, call, *, provider=None, method=None, adjustment=None):
    emit(safe_event(stage, 'START', provider=provider, method=method, adjustment=adjustment))
    started = perf_counter(); reason = 'NONE'; status = 'OK'
    try:
        return call()
    except Exception as exc:
        reason = error_reason(exc); status = 'FAILED'
        raise
    finally:
        events.append(emit(safe_event(stage, status, seconds=perf_counter()-started,
                                     reason_code=reason, provider=provider, method=method, adjustment=adjustment)))


class WebDataError(DataError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def date_only(value):
    from datetime import date
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        try: date.fromisoformat(value); return value
        except ValueError: pass
    return None


EVENT_FIELDS = ('seconds','reason_code','provider','method','adjustment','request_id',
                'stock_trade_date','industry_snapshot_date','benchmark_snapshot_date')


def clean_events(events):
    if not isinstance(events,list): return []
    return [safe_event(e.get('stage'),e.get('status'),**{k:e[k] for k in EVENT_FIELDS if k in e})
            for e in events[-100:] if isinstance(e,dict)]


def request_summary(diagnostics, *, rid, outcome, seconds, web_cache='UNKNOWN', layer='WEB'):
    """Rebuild public evidence, never copy arbitrary dicts or exception text.

    Cache HIT describes this submit, not the cached request's provider work.
    Missing measurements are UNKNOWN; observed counters have explicit scopes.
    """
    source=diagnostics if isinstance(diagnostics,dict) else {}
    hit=web_cache=='HIT';events=[] if hit else clean_events(source.get('events'))
    reason=source.get('reason_code')
    reason=reason if allowed(reason,REASONS) else ('NONE' if outcome=='SUCCESS' else 'WORKER_ERROR')
    result={'diagnostic_version':2,'event_type':'REQUEST_COMPLETE',
            'request_id':valid_request_id(rid) or 'UNKNOWN','layer':layer if layer in {'WEB','WORKER'} else 'WEB',
            'outcome':outcome if outcome in {'SUCCESS','FAILURE','TIMEOUT'} else 'FAILURE',
            'reason_code':'NONE' if hit and outcome=='SUCCESS' else reason,
            'total_latency_seconds':round(seconds,4) if isinstance(seconds,(int,float)) and math.isfinite(seconds) and seconds>=0 else 'UNKNOWN',
            'latency_scope':'loader_including_cache_and_worker' if layer=='WEB' else 'worker_including_startup',
            'web_cache':web_cache if web_cache in {'HIT','MISS'} else 'UNKNOWN',
            'events':events,'last_completed_stage':'cache' if hit else next(
                (e['stage'] for e in reversed(events) if e['status']=='OK' and e['stage'] not in {'context','fetch_retry'}),'UNKNOWN'),
            'last_observed_stage':events[-1]['stage'] if events else ('cache' if hit else 'UNKNOWN'),
            'provider_error_categories':sorted({e['reason_code'] for e in events if e['status'] in {'FAILED','TIMEOUT'}
                                               and e['stage'] in {'provider_request','stock_raw_qfq_fetch','fetch_attempt','fetch_group'}
                                               and not e['reason_code'].startswith('BENCHMARK_SNAPSHOT_')
                                               and e['reason_code']!='WEB_DEADLINE_EXCEEDED'}),
            'data_error_categories':sorted({e['reason_code'] for e in events if e['status'] in {'FAILED','TIMEOUT'}
                                            and e['reason_code'].startswith('BENCHMARK_SNAPSHOT_')}),
            'retry_scope':'ProviderManager._fetch callback retries; security/SDK internal retries UNKNOWN',
            'security_retry_count':'UNKNOWN','provider_internal_retry_count':'UNKNOWN',
            'provider_retry_count':0 if hit else (sum(e['stage']=='fetch_retry' for e in events) if source.get('fetch_attempts_observed') is True else 'UNKNOWN'),
            'provider_timeout_count':0 if hit else 'UNKNOWN',
            'raw_seconds':0 if hit else 'UNKNOWN','qfq_seconds':0 if hit else 'UNKNOWN',
            'data_cache_hits':0 if hit else 'UNKNOWN','data_cache_misses':0 if hit else 'UNKNOWN',
            'provider_requests':0 if hit else 'UNKNOWN',
            'counter_scope':'this request only; cached-origin measurements not reused',
            'partial_events':bool(source.get('partial_events',False)) or len(events)>=100}
    for key in ('stock_trade_date','industry_snapshot_date','benchmark_snapshot_date'):
        day=date_only(source.get(key)) or next((e[key] for e in reversed(events) if key in e),None)
        result[key]=day or 'UNKNOWN'
    for key in ('industry_data_status','benchmark_data_status'):
        value=source.get(key)
        result[key]=value if allowed(value,{'VALID','UNKNOWN','DATA_ERROR','DATA_STALE','DATA_INCONSISTENT','DATA_INCOMPLETE',
                                      'BENCHMARK_SNAPSHOT_DATA_STALE','BENCHMARK_SNAPSHOT_DATA_ERROR','BENCHMARK_SNAPSHOT_DATA_INCONSISTENT'}) else 'UNKNOWN'
    if hit:
        result['cached_origin_request_id']=valid_request_id(source.get('cached_origin_request_id')) or valid_request_id(source.get('request_id')) or 'UNKNOWN'
        result.update(raw_measurement='NOT_EXECUTED',qfq_measurement='NOT_EXECUTED')
        return result
    for adjustment in ('raw','qfq'):
        attempts=[e for e in events if e['stage']=='fetch_group' and e.get('adjustment')==adjustment and e['status']!='START']
        if attempts:result[adjustment+'_seconds']=round(sum(e['seconds'] for e in attempts),4)
        result[adjustment+'_measurement']='PARTIAL' if source.get('partial_events') and attempts else ('OBSERVED' if attempts else 'UNKNOWN')
    for key,destination in [('provider_timeouts','provider_timeout_count'),('cache_hits','data_cache_hits'),
                            ('cache_misses','data_cache_misses'),('provider_requests','provider_requests')]:
        value=source.get(key,source.get(destination))
        if isinstance(value,int) and not isinstance(value,bool) and value>=0:result[destination]=value
    if isinstance(source.get('provider_retry_count'),int) and not isinstance(source['provider_retry_count'],bool) and source['provider_retry_count']>=0:
        result['provider_retry_count']=source['provider_retry_count']
    # On a killed/failed worker, partial events only prove a lower bound.
    result['observed_provider_timeout_events']=sum(e['stage']=='provider_request' and e['status'] in {'FAILED','TIMEOUT'}
                                                  and e['reason_code']=='PROVIDER_TIMEOUT' for e in events)
    result['observed_fetch_retry_events']=sum(e['stage']=='fetch_retry' for e in events)
    result['provider_error_observation']='UNKNOWN' if not events else ('PARTIAL' if result['partial_events'] else 'OBSERVED_WRAPPERS')
    result['timeout_count_scope']='classified wrapped provider calls; socket/SDK internals UNKNOWN'
    native=source.get('provider_timeouts',source.get('sdk_poll_timeout_count'))
    result['sdk_poll_timeout_count']=native if isinstance(native,int) and not isinstance(native,bool) and native>=0 else 'UNKNOWN'
    if source.get('provider_requests_observed') is True and not result['partial_events']:
        result['provider_timeout_count']=result['observed_provider_timeout_events']
    elif source.get('provider_error_observation')=='OBSERVED_WRAPPERS' and not result['partial_events']:
        value=source.get('provider_timeout_count')
        result['provider_timeout_count']=value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else 'UNKNOWN'
    else:result['provider_timeout_count']='UNKNOWN'
    if len(events)>=100:
        result['provider_retry_count']='UNKNOWN'
        for adjustment in ('raw','qfq'):
            if result[adjustment+'_seconds']!='UNKNOWN':result[adjustment+'_measurement']='PARTIAL'
    return result


def publish_terminal(summary):
    # Reconstruct again at the logger boundary; never trust extra caller fields.
    try:
        source=summary if isinstance(summary,dict) else {}
        clean=request_summary(source,rid=source.get('request_id'),outcome=source.get('outcome','FAILURE'),
                              seconds=source.get('total_latency_seconds'),web_cache=source.get('web_cache','UNKNOWN'),
                              layer=source.get('layer','WEB'))
        identity=source.get('deployment')
        if isinstance(identity,dict):
            clean['deployment']={}
            for key,length in [('git_commit',40),('code_fingerprint',64)]:
                value=identity.get(key)
                clean['deployment'][key]=value if isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) else 'UNKNOWN'
            value=identity.get('source_modified')
            clean['deployment']['source_modified']=value if isinstance(value,bool) else 'UNKNOWN'
        _log.warning('QUANTSCORE_WEB_DIAGNOSTIC %s',json.dumps(clean,sort_keys=True,allow_nan=False))
    except Exception: pass
