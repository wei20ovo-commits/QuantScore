"""Deterministic offline boundary faults; no Cloud, market or API calls."""
from copy import deepcopy
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.data.cache import DataCache
from app.data.models import DataError
from app.web_backend import analyze_stock,create_web_service,normalize_stock_code
from app.web_diagnostics import (WebDataError,request_summary,current_request,bind_sink,reset_sink,emit,safe_event)
from app.web_observability import run_observed_analysis,mark_analysis_execution
from app.web_runtime import bounded_web_call
from test_stage2_service import service
from test_web_snapshots import published
from tools.stage4c8_r1_workers import (
    offline_result,offline_initialization_failure,read_json_result)

ROOT=Path(__file__).resolve().parents[1]
PRIVATE='PRIVATE_TEST_SENTINEL Z:/private'


def terminal_records(caplog):
    return [json.loads(r.getMessage().split('QUANTSCORE_WEB_DIAGNOSTIC ',1)[1])
        for r in caplog.records if 'QUANTSCORE_WEB_DIAGNOSTIC ' in r.getMessage()
        and 'REQUEST_COMPLETE' in r.getMessage()]


def loader(code):
    mark_analysis_execution()
    return analyze_stock(code)


def assert_safe_failure(caplog,caught,reason,stage):
    diag=caught.value.diagnostics
    assert diag['reason_code']==reason and diag['outcome']=='FAILURE'
    failed=[e for e in diag['events'] if e['stage']==stage and e['status']=='FAILED']
    assert failed and failed[-1]['seconds']>=0
    assert all(e['request_id']==diag['request_id'] for e in diag['events'])
    assert PRIVATE not in caplog.text+json.dumps(diag)+str(caught.value)
    records=terminal_records(caplog)
    assert records[-1]['layer']=='WEB' and records[-1]['request_id']==diag['request_id']
    assert records[-1]['reason_code']==reason and records[-1]['events']
    for key in ('provider_requests','provider_timeout_count','provider_retry_count','raw_seconds','qfq_seconds',
                'observed_provider_timeout_events','observed_fetch_retry_events'):
        assert diag[key]=='UNKNOWN'
    assert diag['provider_error_observation']=='UNKNOWN'
    assert current_request() is None
    return diag


@pytest.mark.parametrize('code',['bad','000001.SH'])
def test_web_preprocessing_rejection_is_correlated_before_cache(caplog,code):
    with caplog.at_level(logging.WARNING),patch('app.web_backend.analyze_stock') as analyze, \
         pytest.raises(WebDataError) as caught:
        run_observed_analysis(code,loader,cache_observable=True,preprocess=normalize_stock_code)
    diag=assert_safe_failure(caplog,caught,'WEB_INPUT_REJECTED','web_preprocess')
    assert diag['web_cache']=='UNKNOWN' and diag['last_completed_stage']=='UNKNOWN'
    analyze.assert_not_called()


def test_unexpected_preprocessing_fault_is_not_provider_error(caplog):
    def preprocess(_):raise RuntimeError(PRIVATE+' timeout connection login error')
    with caplog.at_level(logging.WARNING),pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',loader,preprocess=preprocess)
    assert_safe_failure(caplog,caught,'WEB_PREPROCESSING_FAILED','web_preprocess')


@pytest.mark.parametrize('error,reason',[
    (DataError(PRIVATE),'DATA_VALIDATION_ERROR'),
    (PermissionError(PRIVATE),'INITIALIZATION_PERMISSION_ERROR'),
    (FileNotFoundError(PRIVATE),'INITIALIZATION_FILE_NOT_FOUND'),
    (ImportError(PRIVATE),'INITIALIZATION_IMPORT_ERROR'),
    (RuntimeError(PRIVATE+' timeout connection'),'SERVICE_INITIALIZATION_FAILED')])
def test_pre_worker_service_failure_retains_phase_and_unknown_measurements(caplog,error,reason):
    with patch('app.web_backend.create_web_service',side_effect=error), \
         patch('app.web_runtime.bounded_web_call') as worker,caplog.at_level(logging.WARNING), \
         pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',loader,cache_observable=True)
    diag=assert_safe_failure(caplog,caught,reason,'pre_worker_service_init')
    assert diag['web_cache']=='MISS' and diag['last_completed_stage']=='backend_preprocess'
    assert diag['stock_trade_date']==diag['industry_snapshot_date']==diag['benchmark_snapshot_date']=='UNKNOWN'
    worker.assert_not_called()


def test_explicit_provider_policy_rejection_is_not_market_validation(caplog):
    prototype=SimpleNamespace(provider_manager=SimpleNamespace(provider=SimpleNamespace(is_mock=True)))
    with patch('app.web_backend.create_web_service',return_value=prototype), \
         patch('app.web_runtime.bounded_web_call') as worker,caplog.at_level(logging.WARNING), \
         pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',loader)
    assert_safe_failure(caplog,caught,'PROVIDER_CONFIGURATION_REJECTED','provider_policy')
    worker.assert_not_called()


def test_provider_config_constructor_failure_preserves_only_read_snapshot_dates(published,tmp_path,caplog):
    root,_,_=published
    def initialize():return create_web_service(root,DataCache(tmp_path/'offline.sqlite'))
    with patch('app.web_backend.create_web_service',side_effect=initialize), \
         patch('app.data.provider_manager.ProviderManager',side_effect=ValueError(PRIVATE)), \
         patch('app.web_runtime.bounded_web_call') as worker,caplog.at_level(logging.WARNING), \
         pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',loader)
    diag=assert_safe_failure(caplog,caught,'PROVIDER_CONFIGURATION_ERROR','provider_init')
    assert diag['industry_snapshot_date']==diag['benchmark_snapshot_date']=='2026-09-30'
    assert diag['stock_trade_date']=='UNKNOWN' and diag['industry_data_status']=='UNKNOWN'
    assert diag['last_completed_stage']=='cache_init'
    worker.assert_not_called()


@pytest.mark.parametrize('boundary,reason',[
    ('app.web_snapshots.WebContextSnapshots','INITIALIZATION_PERMISSION_ERROR'),
    ('app.data.cache.DataCache','INITIALIZATION_PERMISSION_ERROR')])
def test_early_constructor_io_failure_is_safe(tmp_path,caplog,boundary,reason):
    def initialize():return create_web_service(tmp_path)
    stage='snapshot_init' if boundary.endswith('WebContextSnapshots') else 'cache_init'
    with patch('app.web_backend.create_web_service',side_effect=initialize), \
         patch(boundary,side_effect=PermissionError(PRIVATE)),caplog.at_level(logging.WARNING), \
         pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',loader)
    assert_safe_failure(caplog,caught,reason,stage)


def test_service_component_failure_after_provider_init_is_located(published,service,caplog):
    root,_,_=published
    def initialize():return create_web_service(root,service.provider_manager.cache)
    with patch('app.web_backend.create_web_service',side_effect=initialize), \
         patch('app.data.provider_manager.ProviderManager',return_value=service.provider_manager), \
         patch('app.web_backend.StockAnalysisService',side_effect=DataError(PRIVATE)), \
         caplog.at_level(logging.WARNING),pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',loader)
    diag=assert_safe_failure(caplog,caught,'DATA_VALIDATION_ERROR','service_components_init')
    assert diag['last_completed_stage']=='provider_init'


@pytest.mark.parametrize('point,reason',[('setup','WORKER_SETUP_FAILED'),('start','WORKER_START_FAILED')])
def test_worker_parent_failure_before_execution_is_correlated_and_clean(tmp_path,caplog,point,reason):
    def run(code):
        mark_analysis_execution()
        return bounded_web_call(offline_result,('never-read.json',),root=tmp_path)
    target='app.web_runtime.mp.get_context' if point=='setup' else 'multiprocessing.context.SpawnProcess.start'
    with patch(target,side_effect=PermissionError(PRIVATE)),caplog.at_level(logging.WARNING), \
         pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',run)
    diag=assert_safe_failure(caplog,caught,reason,'worker_'+point)
    assert diag['stock_trade_date']==diag['industry_snapshot_date']==diag['benchmark_snapshot_date']=='UNKNOWN'
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())
    assert any(r['layer']=='WORKER' and r['request_id']==diag['request_id'] for r in terminal_records(caplog))


@pytest.mark.parametrize('unavailable',[False,True])
def test_real_spawn_fixture_success_and_unavailable_preserve_engine_output(tmp_path,service,caplog,unavailable):
    original=service.analyze('000001').to_dict()
    if unavailable:original['data_status']['status']='UNAVAILABLE'
    before=deepcopy(original)
    payload=tmp_path/'OFFLINE_FIXTURE.json';payload.write_text(json.dumps(original),'utf-8')
    def run(code):
        mark_analysis_execution()
        return bounded_web_call(offline_result,(str(payload),),root=tmp_path,seconds=20)
    with caplog.at_level(logging.WARNING):
        result,diag=run_observed_analysis('000001',run,cache_observable=True)
    assert len(result['rules'])==41 and result['rules']==before['rules']
    for key in ('final_quant_score','risk_level','industry_context','score'):
        assert result[key]==before[key]
    assert original==before
    assert diag['outcome']==('FAILURE' if unavailable else 'SUCCESS')
    assert diag['reason_code']==('DATA_UNAVAILABLE' if unavailable else 'NONE')
    assert any(e['stage']=='worker_start' and e['status']=='OK' for e in diag['events'])
    assert any(e['stage']=='analysis' for e in diag['events'])
    assert diag['provider_requests']==diag['raw_seconds']==diag['qfq_seconds']=='UNKNOWN'
    assert any(r['layer']=='WORKER' and r['request_id']==diag['request_id'] for r in terminal_records(caplog))


def test_capture_forwards_outer_sink_without_changing_results():
    outer=[];token=bind_sink(outer.append)
    data={'data_status':{'status':'AVAILABLE'}}
    try:
        def run(_):
            emit(safe_event('analysis','OK'));return data
        value,diag=run_observed_analysis('600519',run)
        emit(safe_event('context','OK'))
    finally:reset_sink(token)
    assert value is data and len(outer)==2
    assert len(diag['events'])==1 and current_request() is None


def test_setup_expiry_is_timeout_and_starts_no_process(tmp_path):
    from app import web_runtime
    clock=[0.]
    real_context=web_runtime.mp.get_context
    def context(*args,**kwargs):
        clock[0]=2.
        return real_context(*args,**kwargs)
    with patch('app.web_runtime.time.monotonic',side_effect=lambda:clock[0]), \
         patch('app.web_runtime.mp.get_context',side_effect=context), \
         patch('multiprocessing.context.SpawnProcess.start') as start, \
         pytest.raises(WebDataError) as caught:
        bounded_web_call(read_json_result,('unused',),root=tmp_path,seconds=1)
    assert caught.value.diagnostics['outcome']=='TIMEOUT'
    assert caught.value.diagnostics['reason_code']=='WEB_DEADLINE_EXCEEDED'
    start.assert_not_called()


def test_start_expiry_is_timeout_before_go_signal(tmp_path):
    class Connection:
        def close(self):pass
        def send(self,_):pytest.fail('GO must not be sent after expiry')
    class Process:
        pid=None
        sentinel=None
        exitcode=None
        def start(self):clock[0]=2.
        def is_alive(self):return False
        def join(self,*_):pass
    class Context:
        def Pipe(self):return Connection(),Connection()
        def Process(self,**_):return Process()
    clock=[0.]
    with patch('app.web_runtime.time.monotonic',side_effect=lambda:clock[0]), \
         patch('app.web_runtime.mp.get_context',return_value=Context()), \
         patch('app.web_runtime._windows_job',return_value=lambda:None), \
         pytest.raises(WebDataError) as caught:
        bounded_web_call(read_json_result,('unused',),root=tmp_path,seconds=1)
    assert caught.value.diagnostics['outcome']=='TIMEOUT'
    assert caught.value.diagnostics['reason_code']=='WEB_DEADLINE_EXCEEDED'


def test_finished_late_response_is_timeout_not_failure(tmp_path):
    class Connection:
        def close(self):pass
        def send(self,_):pass
    class Process:
        pid=None
        sentinel=None
        exitcode=0
        def start(self):
            directory=next((tmp_path/'outputs/runtime/web-jobs').iterdir())
            (directory/'response.json').write_text(
                json.dumps({'ok':True,'value':{
                    'data_status':{'status':'AVAILABLE'}}}),
                encoding='utf-8')
        def is_alive(self):return False
        def join(self,*_):pass
        def terminate(self):pass
        def kill(self):pass
    class Context:
        def Pipe(self):return Connection(),Connection()
        def Process(self,**_):return Process()
    ticks=iter([0.,0.,0.,0.,0.,2.,2.,2.,2.,2.,2.])
    with patch('app.web_runtime.time.monotonic',
               side_effect=lambda:next(ticks,2.)), \
         patch('app.web_runtime.mp.get_context',return_value=Context()), \
         patch('app.web_runtime._windows_job',return_value=lambda:None), \
         pytest.raises(WebDataError) as caught:
        bounded_web_call(read_json_result,('unused',),root=tmp_path,seconds=1)
    assert caught.value.diagnostics['outcome']=='TIMEOUT'
    assert caught.value.diagnostics['reason_code']=='WEB_DEADLINE_EXCEEDED'


def test_success_is_not_published_before_last_deadline_check(tmp_path,caplog):
    class Connection:
        def close(self):pass
        def send(self,_):pass
    class Process:
        pid=None
        sentinel=None
        exitcode=0
        def start(self):
            directory=next((tmp_path/'outputs/runtime/web-jobs').iterdir())
            (directory/'response.json').write_text(
                json.dumps({'ok':True,'value':original}),encoding='utf-8')
        def is_alive(self):return False
        def join(self,*_):pass
        def terminate(self):pass
        def kill(self):pass
    class Context:
        def Pipe(self):return Connection(),Connection()
        def Process(self,**_):return Process()
    original={'data_status':{'status':'AVAILABLE','is_mock':False}}
    ticks=iter([0.,0.,0.,0.,0.,0.,0.,2.,2.,2.,2.])
    with patch('app.web_runtime.time.monotonic',
               side_effect=lambda:next(ticks,2.)), \
         patch('app.web_runtime.mp.get_context',return_value=Context()), \
         patch('app.web_runtime._windows_job',return_value=lambda:None), \
         caplog.at_level(logging.WARNING),pytest.raises(WebDataError) as caught:
        bounded_web_call(read_json_result,('unused',),
                         root=tmp_path,seconds=1)
    assert caught.value.diagnostics['outcome']=='TIMEOUT'
    records=terminal_records(caplog)
    assert not any(record['layer']=='WORKER' and record['outcome']=='SUCCESS'
                   for record in records)


def test_consumed_parent_budget_rejects_before_runtime_setup(tmp_path):
    from app.web_budget import bind_remaining,reset_remaining
    token=bind_remaining(lambda:0)
    try:
        with patch('app.web_runtime.mp.get_context') as context, \
             pytest.raises(WebDataError) as caught:
            bounded_web_call(read_json_result,('unused',),root=tmp_path)
        assert caught.value.diagnostics['outcome']=='TIMEOUT'
        assert caught.value.diagnostics['reason_code']=='WEB_REQUEST_DEADLINE_EXCEEDED'
        context.assert_not_called()
    finally:
        reset_remaining(token)


def test_worker_init_fault_keeps_typed_boundary_not_message_network_guess(tmp_path,caplog):
    def run(_):return bounded_web_call(offline_initialization_failure,(),root=tmp_path,seconds=20)
    with caplog.at_level(logging.WARNING),pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',run)
    diag=assert_safe_failure(caplog,caught,'PROVIDER_CONFIGURATION_ERROR','provider_init')
    assert diag['provider_error_categories']==[]


def test_initialization_events_do_not_prove_provider_zero_calls():
    diag=request_summary({'events':[safe_event('service_init','FAILED',reason_code='DATA_VALIDATION_ERROR')]},
                         rid='a'*32,outcome='FAILURE',seconds=1)
    for key in ('provider_requests','provider_retry_count','provider_timeout_count','raw_seconds','qfq_seconds',
                'observed_provider_timeout_events','observed_fetch_retry_events'):
        assert diag[key]=='UNKNOWN'
    assert diag['provider_error_observation']=='UNKNOWN'


def test_ui_input_failure_shows_safe_request_diagnostic_without_analysis():
    st.cache_data.clear()
    try:
        with patch('app.web_runtime.bounded_web_call',
                   side_effect=lambda target,args,**kwargs:target(*args)), \
             patch('app.web_backend.analyze_stock') as analyze:
            # This new test starts a completely cold UI. Three-second failures
            # were measured at web.py's initial CSS st.html, before diagnostics;
            # local total startup reached 7.77s. Only this first run gets 10s;
            # the request and all existing tests retain their previous budgets.
            app=AppTest.from_file(str(ROOT/'app/web.py')).run(timeout=10)
            app.text_input[0].set_value('bad')
            app.button(key='analyze_submit').click().run()
        assert not app.exception and app.error and not app.metric
        assert any('6位股票代码' in error.value for error in app.error)
        assert app.session_state['request_diagnostics']['reason_code']=='WEB_INPUT_REJECTED'
        assert any('请求诊断' in e.label for e in app.expander)
        analyze.assert_not_called()
    finally:st.cache_data.clear()
