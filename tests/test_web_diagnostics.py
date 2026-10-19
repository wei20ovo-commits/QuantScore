"""Offline failure isolation; fixtures are not live-market acceptance evidence."""
from copy import deepcopy
import json
import logging
from pathlib import Path
import runpy
import time
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.data.models import DataError, ProviderError
from app.data.provider_manager import ProviderManager
from app.web_diagnostics import (WebDataError, bind_sink, reset_sink, error_reason,
                                 emit, safe_event, trace_call)
from app.web_runtime import bounded_web_call
from app.web_snapshots import WebContextSnapshots, SnapshotUnavailable
from app.web_backend import create_web_service
from app.web_snapshots import SnapshotIndustryService
from test_web_snapshots import published
from test_stage2_data import provider
from test_stage2_service import service
from tools.stage4c7_r1_workers import diagnostic_failure_target, diagnostic_hang_target

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('error,reason',[
    (TimeoutError('private endpoint'),'PROVIDER_TIMEOUT'),
    (ConnectionResetError('private endpoint'),'PROVIDER_CONNECTION_ERROR'),
    (ProviderError('BaoStock login error 100'),'PROVIDER_LOGIN_ERROR'),
    (ProviderError('BaoStock query incomplete pagination'),'PROVIDER_INCOMPLETE_PAGINATION'),
    (DataError('raw/qfq 交易日不一致'),'RAW_QFQ_DATE_MISMATCH'),
    (DataError('BaoStock history field groups have inconsistent dates'),'FIELD_GROUP_DATE_MISMATCH'),
    (DataError('invalid OHLC'),'DATA_VALIDATION_ERROR'),
    (ProviderError('unavailable'),'PROVIDER_UNAVAILABLE'),
    (RuntimeError('private message'),'WORKER_ERROR')])
def test_error_categories_do_not_return_exception_text(error,reason):
    assert error_reason(error)==reason


def test_wrapped_proxy_error_retains_safe_root_category():
    from requests.exceptions import ProxyError
    try:raise ProxyError('private URL and credentials')
    except ProxyError as inner:
        outer=ProviderError('wrapped');outer.__cause__=inner
    assert error_reason(outer)=='PROVIDER_PROXY_ERROR'


def test_diagnostics_allowlist_rejects_private_fields_and_values(caplog):
    secret='sk-'+'not-a-real-credential-fixture'
    event={'stage':secret,'status':secret,'reason_code':secret,'provider':secret,
           'method':secret,'adjustment':secret,'api_key':secret,'path':'D:/private','seconds':float('nan')}
    with caplog.at_level(logging.INFO):value=emit(event)
    serialized=json.dumps(value)+caplog.text
    assert secret not in serialized and 'D:/private' not in serialized and 'api_key' not in value
    assert value['reason_code']=='WORKER_ERROR' and value['seconds']==0


def test_trace_preserves_output_input_and_error_without_secret(caplog):
    original={'quant_score':80,'risk':'LOW','B1':6,'B2':1};before=deepcopy(original);events=[]
    assert trace_call(events,'rule_scoring',lambda:original) is original
    assert original==before
    secret='sk-'+'not-a-real-credential-fixture';exc=ProviderError(secret)
    with caplog.at_level(logging.WARNING),pytest.raises(ProviderError) as caught:
        trace_call(events,'provider_request',lambda:(_ for _ in ()).throw(exc),provider='baostock')
    assert caught.value is exc and secret not in json.dumps(events)+caplog.text


def test_diagnostic_sink_failure_cannot_change_success():
    token=bind_sink(lambda event:(_ for _ in ()).throw(OSError('unwritable')))
    try:assert trace_call([],'analysis',lambda:42)==42
    finally:reset_sink(token)


def test_spawn_entrypoint_does_not_register_streamlit_caches():
    # Same name used by multiprocessing spawn on Windows and Linux.
    with patch('streamlit.cache_data',side_effect=AssertionError('No worker UI cache')):
        namespace=runpy.run_path(str(ROOT/'app/web.py'),run_name='__mp_main__')
    assert callable(namespace['load_analysis'])


def test_worker_failure_transports_safe_phase_and_cleans(tmp_path):
    with pytest.raises(WebDataError) as caught:
        bounded_web_call(diagnostic_failure_target,(),root=tmp_path,seconds=20)
    diag=caught.value.diagnostics
    assert diag['events'][-1]['stage']=='provider_request'
    assert diag['events'][-1]['reason_code']=='PROVIDER_TIMEOUT'
    assert 'private endpoint' not in json.dumps(diag)+str(caught.value)
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


def test_deadline_retains_last_provider_stage_and_cleans(tmp_path):
    ready=tmp_path/'provider.ready'
    start=time.monotonic()
    with pytest.raises(WebDataError) as caught:
        bounded_web_call(diagnostic_hang_target,(str(ready),),root=tmp_path,seconds=8)
    assert ready.read_text('utf-8')=='PROVIDER_EVENT_PERSISTED'
    assert caught.value.diagnostics['reason_code']=='WEB_DEADLINE_EXCEEDED'
    assert caught.value.diagnostics['events'][-1]['stage']=='provider_request'
    assert time.monotonic()-start<13
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


def test_spawn_diagnostic_targets_resolve_without_test_ui_or_market_imports():
    # Spawn unpickles the target BEFORE entering _worker and binding its sink.
    # A target defined here re-imports this whole module and its costly test/UI
    # stack inside the eight-second deadline. Reject that dependency regression
    # deterministically instead of relying on warm imports or a larger timeout.
    import subprocess
    import sys
    child=subprocess.run([sys.executable,'-c', '''
import importlib.abc, pickle, sys
class RejectHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pytest', 'streamlit', 'pandas', 'test_web_diagnostics'}:
            raise AssertionError('SPAWN_TARGET_IMPORTED_HEAVY_DEPENDENCY')
sys.meta_path.insert(0, RejectHeavy())
from app import web_runtime
from tools.stage4c7_r1_workers import diagnostic_failure_target, diagnostic_hang_target
for target in (diagnostic_failure_target, diagnostic_hang_target):
    assert target.__module__ == 'tools.stage4c7_r1_workers'
    assert pickle.loads(pickle.dumps(target)) is target
assert not any(name in sys.modules for name in ('pytest', 'streamlit', 'pandas', 'test_web_diagnostics'))
'''],cwd=ROOT,capture_output=True,timeout=20)
    assert child.returncode==0


def test_current_stock_date_rejects_september_snapshots(published):
    root,_,_=published;snapshot=WebContextSnapshots(root)
    assert snapshot.published_benchmark_date=='2026-09-30'
    assert snapshot.industry('600519.SH','2026-10-09')['data_status']=='DATA_STALE'
    with pytest.raises(SnapshotUnavailable,match='DATA_STALE'):
        snapshot.benchmark('2026-10-09','2000-01-01','2026-10-09')


def test_provider_retry_is_finite_and_does_not_cache_failure(tmp_path,provider):
    from app.data.cache import DataCache
    manager=ProviderManager(provider,cache=DataCache(tmp_path/'retry.sqlite3'),retries=2)
    calls=[]
    def failed():calls.append(1);raise ProviderError('deadline exceeded')
    with pytest.raises(ProviderError):manager._fetch(provider,'000001.SZ','2026-09-01','2026-09-30','raw',failed,False)
    assert len(calls)==2
    calls.clear()
    def not_retryable():
        calls.append(1);err=ProviderError('deadline exceeded');err.retryable=False;raise err
    with pytest.raises(ProviderError):manager._fetch(provider,'000001.SZ','2026-09-01','2026-09-30','raw',not_retryable,False)
    assert len(calls)==1


def test_unavailable_ui_displays_diagnosis_and_no_scores(service):
    import streamlit as st
    output=service.analyze('000001').to_dict()
    output['data_status']['status']='UNAVAILABLE';output['data_status']['is_mock']=False
    output['web_diagnostics']={'reason_code':'PROVIDER_TIMEOUT','events':[safe_event('provider_request','FAILED',reason_code='PROVIDER_TIMEOUT')]}
    st.cache_data.clear()
    with patch('app.web_backend.analyze_stock',return_value=output):
        # Isolated cold startup exceeds AppTest's 3s default (profiled main
        # 3.11s, framework run 3.29s). Match the existing finite UI-suite budget;
        # the provider deadline test stays at 8s and production stays at 240s.
        app=AppTest.from_file(str(ROOT/'app/web.py'),default_timeout=8).run()
        app.button(key='analyze_submit').click().run(timeout=20)
    assert not app.exception and app.error and not app.metric
    assert any('请求诊断' in x.label for x in app.expander)
    assert any('PROVIDER_TIMEOUT' in x.value for x in app.json)
    st.cache_data.clear()


def test_web_instrumentation_keeps_all_41_rule_results_identical(published,service):
    root,_,_=published;manager=service.provider_manager
    day=str(manager.fetch('000001').bars.date.iloc[-1].date())
    service.industry_service=SnapshotIndustryService(WebContextSnapshots(root))
    manager.fetch('000001',as_of=day)  # Same acquisition provenance on both calls.
    before=service.analyze('000001',as_of=day).to_dict()
    with patch('app.data.provider_manager.ProviderManager',return_value=manager):
        instrumented=create_web_service(root,manager.cache)
    after=instrumented.analyze('000001',as_of=day).to_dict()
    assert len(after['rules'])==41 and before['rules']==after['rules']
    assert before['score']==after['score']
    assert before['risk_level']==after['risk_level']
    assert before['industry_context']==after['industry_context']
    assert before['final_quant_score']==after['final_quant_score']
