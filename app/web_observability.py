"""Per-submit evidence outside the unchanged Streamlit cache key and TTL."""
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from app.web_diagnostics import (WebDataError, bind_request, reset_request,
    error_reason, request_summary, publish_terminal)

_execution=ContextVar('web_cache_execution_marker',default=None)


def mark_analysis_execution():
    marker=_execution.get()
    if marker is not None:marker['executed']=True


def run_observed_analysis(code,loader,*,cache_observable=False,deployment=None):
    """Return the original result untouched and a separate sanitized summary."""
    rid=uuid4().hex;marker={'executed':False};start=perf_counter()
    token=bind_request(rid);execution_token=_execution.set(marker)
    def finish(summary):
        # A release fingerprint links each terminal log to the running source.
        import re
        identity=deployment if isinstance(deployment,dict) else {}
        summary['deployment']={}
        for key,size in [('git_commit',40),('code_fingerprint',64)]:
            value=identity.get(key)
            summary['deployment'][key]=value if isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(size)+'}',value) else 'UNKNOWN'
        modified=identity.get('source_modified')
        summary['deployment']['source_modified']=modified if isinstance(modified,bool) else 'UNKNOWN'
        publish_terminal(summary)
        return summary
    try:
        result=loader(code)
        outcome='FAILURE' if result.get('data_status',{}).get('status')=='UNAVAILABLE' else 'SUCCESS'
        summary=request_summary(result.get('web_diagnostics'),rid=rid,outcome=outcome,
                                seconds=perf_counter()-start,web_cache='MISS' if marker['executed'] else ('HIT' if cache_observable else 'UNKNOWN'))
        # Legacy results may omit diagnostics; the original result date is safe.
        from app.web_diagnostics import date_only
        summary['stock_trade_date']=date_only(result.get('evaluation_date')) or summary['stock_trade_date']
        finish(summary)
        return result,summary
    except Exception as exc:
        evidence=getattr(exc,'diagnostics',None)
        source=dict(evidence) if isinstance(evidence,dict) else {}
        source.setdefault('reason_code',error_reason(exc))
        outcome='TIMEOUT' if source['reason_code']=='WEB_DEADLINE_EXCEEDED' else 'FAILURE'
        summary=request_summary(source,rid=rid,outcome=outcome,seconds=perf_counter()-start,
                                web_cache='MISS' if marker['executed'] else 'UNKNOWN')
        finish(summary)
        # Only known safe existing Web errors retain their message. Arbitrary
        # provider exceptions and private paths must never reach the page.
        known_messages={
            '暂时无法取得完整行情，请稍后重试。数据源返回不可用，本次不展示评分。',
            '单股分析达到运行时限，已停止本次请求；未生成新评分，请稍后重试。',
            '单股分析未返回完整结果；本次不展示新评分。',
            '单股数据源或快照暂不可用；本次不展示新评分，请稍后重试。'}
        message=str(exc) if isinstance(exc,WebDataError) and str(exc) in known_messages else '分析暂时未完成，请稍后重试。当前没有可展示的新结果。'
        raise WebDataError(message,summary) from None
    finally:
        _execution.reset(execution_token);reset_request(token)
