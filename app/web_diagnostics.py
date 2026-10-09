"""Allowlisted Web worker diagnostics; never serialize exception messages."""
from contextvars import ContextVar
import json
import logging
import math
import re
from time import perf_counter
from app.data.models import DataError

_sink = ContextVar('web_diagnostic_sink', default=None)
_log = logging.getLogger(__name__)
STAGES = {'worker', 'service_init', 'security_resolve', 'security_lookup',
          'security_list', 'stock_raw_qfq_fetch', 'provider_request', 'market_fetch',
          'industry_context_load', 'rule_scoring', 'analysis', 'chart_data', 'cache'}
REASONS = {'NONE', 'PROVIDER_TIMEOUT', 'PROVIDER_CONNECTION_ERROR', 'PROVIDER_PROXY_ERROR',
           'PROVIDER_LOGIN_ERROR', 'PROVIDER_INCOMPLETE_PAGINATION', 'PROVIDER_SDK_ERROR',
           'PROVIDER_UNAVAILABLE', 'DATA_VALIDATION_ERROR', 'RAW_QFQ_DATE_MISMATCH',
           'FIELD_GROUP_DATE_MISMATCH', 'WORKER_ERROR', 'WORKER_RESPONSE_INVALID',
           'WEB_DEADLINE_EXCEEDED', 'DATA_UNAVAILABLE', 'INVALID_PRICE_VALUES',
           'INVALID_OHLC_RELATION', 'EMPTY_MARKET_DATA'}
METHODS = {'query_stock_basic', 'query_history_k_data_plus', 'query_trade_dates',
           'stock_zh_a_hist', 'stock_info_sh_name_code', 'stock_info_sz_name_code'}


def error_reason(exc):
    """Classify locally, discard all messages/URLs/paths/credentials."""
    chain = []; seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc)); chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    names = {type(e).__name__ for e in chain}
    text = ' '.join(str(e)[:4000].lower() for e in chain)
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


def safe_event(stage, status, *, seconds=0, reason_code='NONE', provider=None,
               method=None, adjustment=None):
    value = {'stage': stage if stage in STAGES else 'worker',
             'status': status if status in {'START', 'OK', 'FAILED', 'UNAVAILABLE', 'TIMEOUT'} else 'FAILED',
             'reason_code': reason_code if reason_code in REASONS else 'WORKER_ERROR',
             'seconds': round(float(seconds), 4) if isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds >= 0 else 0}
    if provider in {'baostock', 'akshare', 'tushare'}: value['provider'] = provider
    if method in METHODS: value['method'] = method
    if adjustment in {'raw', 'qfq', 'NONE', 'limits', 'basic', 'verified_security', 'validated_securities'}:
        value['adjustment'] = adjustment
    return value


def emit(event):
    # Reconstruct instead of trusting callers or an exception's attributes.
    event = safe_event(event.get('stage'), event.get('status'),
                       **{k: event[k] for k in ('seconds','reason_code','provider','method','adjustment') if k in event})
    sink = _sink.get()
    if sink is not None:
        try: sink(event)
        except (OSError, ValueError): pass  # Diagnostics never decide data/score.
    log = _log.warning if event['status'] in {'FAILED','UNAVAILABLE','TIMEOUT'} else _log.info
    log('QUANTSCORE_WEB_DIAGNOSTIC %s', json.dumps(event, sort_keys=True))
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
    return value if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None
