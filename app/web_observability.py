"""Per-submit evidence outside the unchanged Streamlit cache key and TTL."""
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from app.web_diagnostics import (WebDataError, bind_request, reset_request,
    error_reason, request_summary, publish_terminal, bind_event_capture, reset_sink,
    trace_call, boundary_reason)

_execution=ContextVar('web_cache_execution_marker',default=None)


def mark_analysis_execution():
    marker=_execution.get()
    if marker is not None:marker['executed']=True


def run_observed_analysis(code,loader,*,cache_observable=False,deployment=None,preprocess=None):
    """Return the original result untouched and a separate sanitized summary."""
    rid=uuid4().hex;marker={'executed':False};start=perf_counter()
    token=bind_request(rid);execution_token=_execution.set(marker)
    observed=[];sink_token=bind_event_capture(observed)
    def evidence(source):
        source=dict(source) if isinstance(source,dict) else {}
        # emit() returns the same object sent to the capture sink. Preserve
        # distinct worker IPC events, but do not double count in-process events.
        identities={id(e) for e in observed}
        original=source.get('events')
        source['events']=[*observed,*([e for e in original if id(e) not in identities]
                                    if isinstance(original,list) else [])]
        if len(source['events'])>100:source['partial_events']=True
        return source
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
        if preprocess is not None:
            code=trace_call([],'web_preprocess',lambda:preprocess(code),error_classifier=boundary_reason)
        result=loader(code)
        outcome='FAILURE' if result.get('data_status',{}).get('status')=='UNAVAILABLE' else 'SUCCESS'
        summary=request_summary(evidence(result.get('web_diagnostics')),rid=rid,outcome=outcome,
                                seconds=perf_counter()-start,web_cache='MISS' if marker['executed'] else ('HIT' if cache_observable else 'UNKNOWN'))
        # Legacy results may omit diagnostics; the original result date is safe.
        from app.web_diagnostics import date_only
        summary['stock_trade_date']=date_only(result.get('evaluation_date')) or summary['stock_trade_date']
        finish(summary)
        return result,summary
    except Exception as exc:
        source=evidence(getattr(exc,'diagnostics',None))
        # The first failed nested boundary identifies the original failure;
        # outer service wrappers must not overwrite it with a generic DataError.
        if 'reason_code' not in source:
            failed_reason=next((e['reason_code'] for e in observed if e['status']=='FAILED'),None)
            source['reason_code']=failed_reason or error_reason(exc)
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
        input_messages={'请输入6位股票代码，例如600519或000001，也可使用600519.SH。',
                        '当前页面只分析股票；平安银行请输入000001或000001.SZ。'}
        safe_input=source['reason_code']=='WEB_INPUT_REJECTED' and str(exc) in input_messages
        message=str(exc) if safe_input or (isinstance(exc,WebDataError) and str(exc) in known_messages) else '分析暂时未完成，请稍后重试。当前没有可展示的新结果。'
        raise WebDataError(message,summary) from None
    finally:
        reset_sink(sink_token)
        _execution.reset(execution_token);reset_request(token)
