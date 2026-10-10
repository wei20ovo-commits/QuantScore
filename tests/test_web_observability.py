"""Controlled offline observability paths, not live Cloud/market evidence."""
from copy import deepcopy
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
import subprocess
import time
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.data.models import ProviderError
from app.web_deployment import deployment_identity
from app.web_diagnostics import (WebDataError, bind_request, reset_request, current_request,
    emit, safe_event, request_summary, trace_call, bind_sink, reset_sink, error_reason, publish_terminal)
from app.web_observability import run_observed_analysis, mark_analysis_execution
from app.web_runtime import bounded_web_call
from test_stage2_service import service
from test_web_snapshots import published
from tools.stage4c7_r1_workers import (success_worker_target, failure_worker_target,
    timeout_worker_target, before_snapshot_worker_target)

ROOT=Path(__file__).resolve().parents[1]


def source_tree(root,newline='\n'):
    for name in ['app/web.py','app/engine/rule_engine.py','app/web_style.css',
                 'config/parameters.yaml','requirements.txt','pyproject.toml','.streamlit/config.toml']:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(('content'+newline).encode())


def test_real_git_identity_is_read_not_embedded():
    actual=deployment_identity(ROOT)
    expected=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()
    assert actual['git_commit']==expected
    assert re.fullmatch('[0-9a-f]{64}',actual['code_fingerprint'])
    assert actual['fingerprint_complete']


def test_no_git_falls_back_to_source_fingerprint_and_ignores_secrets(tmp_path):
    source_tree(tmp_path)
    with patch('app.web_deployment.subprocess.run',side_effect=FileNotFoundError('private executable path')):
        before=deployment_identity(tmp_path)
        (tmp_path/'.streamlit/secrets.toml').write_text('PRIVATE_CREDENTIAL_TEST_SENTINEL')
        (tmp_path/'.env').write_text('PRIVATE_CREDENTIAL_TEST_SENTINEL')
        after=deployment_identity(tmp_path)
    assert before==after and before['git_commit']=='UNKNOWN'
    assert before['code_fingerprint']!='UNKNOWN'
    assert 'PRIVATE_CREDENTIAL_TEST_SENTINEL' not in json.dumps(after)
    (tmp_path/'app/web.py').write_text('changed')
    with patch('app.web_deployment.subprocess.run',side_effect=FileNotFoundError):
        assert deployment_identity(tmp_path)['code_fingerprint']!=before['code_fingerprint']


def test_fingerprint_reproduces_across_windows_linux_line_endings(tmp_path):
    source_tree(tmp_path/'lf');source_tree(tmp_path/'crlf','\r\n')
    with patch('app.web_deployment.subprocess.run',side_effect=FileNotFoundError):
        assert deployment_identity(tmp_path/'lf')['code_fingerprint']==deployment_identity(tmp_path/'crlf')['code_fingerprint']


def test_parent_repository_sha_is_not_claimed_for_nested_app(tmp_path):
    source_tree(tmp_path)
    fake=subprocess.CompletedProcess([],0,stdout=str(tmp_path.parent).encode(),stderr=b'')
    with patch('app.web_deployment.subprocess.run',return_value=fake):
        assert deployment_identity(tmp_path)['git_commit']=='UNKNOWN'


def test_missing_source_cannot_claim_complete_fingerprint(tmp_path):
    with patch('app.web_deployment.subprocess.run',side_effect=FileNotFoundError):
        assert not deployment_identity(tmp_path)['fingerprint_complete']


def test_git_queries_share_budget_and_keep_verified_fingerprint(tmp_path):
    source_tree(tmp_path)
    calls=[]
    def query(command,**kwargs):
        calls.append((command,kwargs['timeout']))
        if len(calls)==1:
            return subprocess.CompletedProcess(command,0,stdout=(str(tmp_path)+'\n'+'a'*40+'\n').encode())
        raise subprocess.TimeoutExpired('git',kwargs['timeout'])
    # Controlled elapsed clock proves status cannot obtain a fresh budget.
    with patch('app.web_deployment.time.monotonic',side_effect=[10,10.1,10.8]), \
         patch('app.web_deployment.subprocess.run',side_effect=query):
        result=deployment_identity(tmp_path)
    assert len(calls)==2 and calls[0][0][-3:]==['rev-parse','--show-toplevel','HEAD']
    assert calls[0][1]==pytest.approx(.9) and calls[1][1]==pytest.approx(.2)
    assert result['git_commit']=='a'*40 and result['source_modified']=='UNKNOWN'
    assert result['fingerprint_complete'] and re.fullmatch('[0-9a-f]{64}',result['code_fingerprint'])


def test_git_timeout_does_not_claim_sha_or_disable_fingerprint(tmp_path):
    source_tree(tmp_path)
    with patch('app.web_deployment.subprocess.run',side_effect=subprocess.TimeoutExpired('git',1)):
        result=deployment_identity(tmp_path)
    assert result['git_commit']==result['source_modified']=='UNKNOWN'
    assert result['fingerprint_complete']


@pytest.mark.parametrize('status',['START','OK','FAILED','TIMEOUT'])
def test_events_reach_warning_threshold_with_request_id(caplog,status):
    token=bind_request('a'*32)
    try:
        with caplog.at_level(logging.WARNING):emit(safe_event('provider_request',status,provider='baostock'))
    finally:reset_request(token)
    record=[x for x in caplog.records if 'QUANTSCORE_WEB_DIAGNOSTIC' in x.message][-1]
    assert record.levelno==logging.WARNING
    value=json.loads(record.message.split('QUANTSCORE_WEB_DIAGNOSTIC ',1)[1])
    assert value['request_id']=='a'*32 and value['status']==status


def test_summary_rebuilds_untrusted_values_without_private_fields():
    private='PRIVATE_CREDENTIAL_TEST_SENTINEL'
    source={'request_id':private,'events':[{'stage':private,'status':private,'provider':private,
        'request_id':private,'reason_code':private,'path':'Z:/private','seconds':float('inf')}],
        'reason_code':private,'stock_trade_date':private,'industry_snapshot_date':'2026-02-31',
        'api_key':private,'cache_hits':private,'provider_timeouts':private}
    result=request_summary(source,rid='b'*32,outcome='FAILURE',seconds=1)
    assert private not in json.dumps(result) and 'Z:/private' not in json.dumps(result)
    assert result['industry_snapshot_date']=='UNKNOWN'
    assert result['provider_timeout_count']=='UNKNOWN' and result['data_cache_hits']=='UNKNOWN'


def test_malformed_container_fields_are_safe_not_diagnostic_crashes():
    event=emit({'stage':{},'status':[],'reason_code':{},'provider':[]})
    assert event['stage']=='worker' and event['status']=='FAILED'
    value=request_summary({'reason_code':{},'industry_data_status':[]},rid='b'*32,outcome='FAILURE',seconds=1)
    assert value['industry_data_status']=='UNKNOWN'


def test_stale_benchmark_is_not_misreported_as_provider_network_failure():
    from app.web_snapshots import SnapshotUnavailable
    reason=error_reason(SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_STALE'))
    assert reason=='BENCHMARK_SNAPSHOT_DATA_STALE'
    summary=request_summary({'events':[safe_event('fetch_group','FAILED',reason_code=reason,adjustment='NONE')]},
                            rid='b'*32,outcome='SUCCESS',seconds=1)
    assert summary['provider_error_categories']==[]
    assert summary['data_error_categories']==['BENCHMARK_SNAPSHOT_DATA_STALE']


def test_terminal_logger_filters_extra_private_values(caplog):
    with caplog.at_level(logging.WARNING):
        publish_terminal({'request_id':'f'*32,'outcome':'SUCCESS','total_latency_seconds':1,
                          'api_key':'PRIVATE_CREDENTIAL_TEST_SENTINEL','traceback':'Z:/private',
                          'provider_error_observation':'OBSERVED_WRAPPERS','provider_timeout_count':'PRIVATE_CREDENTIAL_TEST_SENTINEL'})
    assert 'PRIVATE_CREDENTIAL_TEST_SENTINEL' not in caplog.text and 'Z:/private' not in caplog.text


def test_request_summary_preserves_partial_stage_and_lower_bound_semantics():
    source={'events':[safe_event('rule_scoring','OK',seconds=.1),
        safe_event('fetch_group','START',adjustment='raw'),
        safe_event('provider_request','FAILED',reason_code='PROVIDER_TIMEOUT'),
        safe_event('fetch_group','TIMEOUT',adjustment='raw',seconds=7)],
        'partial_events':True,'reason_code':'WEB_DEADLINE_EXCEEDED'}
    summary=request_summary(source,rid='c'*32,outcome='TIMEOUT',seconds=8)
    assert summary['last_completed_stage']=='rule_scoring'
    assert summary['raw_seconds']==7 and summary['raw_measurement']=='PARTIAL'
    assert summary['provider_timeout_count']=='UNKNOWN'
    assert summary['observed_provider_timeout_events']==1


def test_terminal_logging_and_input_immutability_with_unknown_measurements(caplog):
    original={'final_quant_score':80,'risk_level':'LOW','industry_context':{'data_status':'DATA_STALE'},
        'data_status':{'status':'AVAILABLE'},'rules':[{'rule_id':'B1','status':'UNKNOWN','score':None}]}
    before=deepcopy(original)
    with caplog.at_level(logging.WARNING):value,diagnostic=run_observed_analysis('600519',lambda _:original)
    assert value is original and original==before
    assert diagnostic['web_cache']=='UNKNOWN' and diagnostic['provider_retry_count']=='UNKNOWN'
    assert any('REQUEST_COMPLETE' in x.message and 'SUCCESS' in x.message for x in caplog.records)
    assert current_request() is None


def test_streamlit_cache_hit_gets_new_request_and_no_old_provider_metrics(caplog):
    calls=[]
    @st.cache_data(ttl=300,show_spinner=False)
    def loader(code):
        mark_analysis_execution();calls.append(code)
        return {'data_status':{'status':'AVAILABLE'},'evaluation_date':'2026-10-09',
            'web_diagnostics':{'request_id':current_request(),'cache_hits':2,'cache_misses':3,
                'provider_requests':7,'provider_timeouts':1,'fetch_attempts_observed':True,
                'events':[safe_event('fetch_retry','OK',adjustment='raw'),safe_event('chart_data','OK')],
                'industry_snapshot_date':'2026-09-30','industry_data_status':'DATA_STALE'}}
    loader.clear()
    try:
        with caplog.at_level(logging.WARNING):
            first,a=run_observed_analysis('600519',loader,cache_observable=True)
            second,b=run_observed_analysis('600519',loader,cache_observable=True)
    finally:loader.clear()
    assert calls==['600519'] and first==second
    assert a['web_cache']=='MISS' and b['web_cache']=='HIT' and a['request_id']!=b['request_id']
    assert b['cached_origin_request_id']==a['request_id']
    assert b['provider_requests']==b['provider_timeout_count']==b['provider_retry_count']==0
    assert b['events']==[] and b['raw_measurement']=='NOT_EXECUTED'
    assert b['industry_data_status']=='DATA_STALE' and b['industry_snapshot_date']=='2026-09-30'
    logged=[json.loads(x.message.split('QUANTSCORE_WEB_DIAGNOSTIC ',1)[1]) for x in caplog.records if 'REQUEST_COMPLETE' in x.message]
    assert logged[-1]['cached_origin_request_id']==a['request_id']


@pytest.mark.parametrize('reason,outcome',[('PROVIDER_TIMEOUT','FAILURE'),('WEB_DEADLINE_EXCEEDED','TIMEOUT'),('WORKER_ERROR','FAILURE')])
def test_failure_timeout_logs_and_page_evidence_are_safe(caplog,reason,outcome):
    def failed(_):
        mark_analysis_execution()
        raise WebDataError('PRIVATE_CREDENTIAL_TEST_SENTINEL',{'reason_code':reason,'api_key':'PRIVATE_CREDENTIAL_TEST_SENTINEL'})
    with caplog.at_level(logging.WARNING),pytest.raises(WebDataError) as caught:
        run_observed_analysis('600519',failed)
    assert caught.value.diagnostics['outcome']==outcome
    assert caught.value.diagnostics['web_cache']=='MISS'
    assert 'PRIVATE_CREDENTIAL_TEST_SENTINEL' not in str(caught.value)+caplog.text+json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize('target,outcome',[(success_worker_target,'SUCCESS'),(failure_worker_target,'FAILURE'),(timeout_worker_target,'TIMEOUT')])
def test_actual_spawn_paths_emit_parent_terminal_at_warning(tmp_path,caplog,target,outcome):
    # The child reads the actual offline context file, not an assumed date from
    # the parent. Keep UI/pytest imports outside the spawned target's module.
    snapshot=tmp_path/'offline-context.json'
    snapshot.write_text(json.dumps({'industry_snapshot_date':'2026-09-30',
        'benchmark_snapshot_date':'2026-09-30'}),'utf-8')
    token=bind_request('d'*32)
    try:
        with caplog.at_level(logging.WARNING):
            if outcome=='SUCCESS':
                value=bounded_web_call(target,(str(snapshot),),root=tmp_path,seconds=20)
                assert value['final_quant_score']==80 and value['risk_level']=='LOW'
                assert value['web_diagnostics']['request_id']=='d'*32
                assert any(e['stage']=='fetch_group' for e in value['web_diagnostics']['events'])
            else:
                with pytest.raises(WebDataError) as caught:
                    bounded_web_call(target,(str(snapshot),),root=tmp_path,seconds=8 if outcome=='TIMEOUT' else 20)
                evidence=caught.value.diagnostics
                assert evidence['request_id']=='d'*32 and evidence['outcome']==outcome
                assert evidence['industry_snapshot_date']==evidence['benchmark_snapshot_date']=='2026-09-30'
                if outcome=='TIMEOUT':
                    assert evidence['last_completed_stage']=='rule_scoring'
                    assert evidence['qfq_seconds']>0 and evidence['qfq_measurement']=='PARTIAL'
    finally:reset_request(token)
    records=[json.loads(x.message.split('QUANTSCORE_WEB_DIAGNOSTIC ',1)[1]) for x in caplog.records
             if 'QUANTSCORE_WEB_DIAGNOSTIC ' in x.message]
    assert any(r.get('event_type')=='REQUEST_COMPLETE' and r['outcome']==outcome and r['request_id']=='d'*32 for r in records)
    assert 'PRIVATE_CREDENTIAL_TEST_SENTINEL' not in caplog.text
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


def test_logging_handler_failure_does_not_change_analysis():
    with patch('app.web_diagnostics._log.warning',side_effect=RuntimeError('logging unavailable')):
        assert trace_call([],'analysis',lambda:42)==42
        value,_=run_observed_analysis('600519',lambda _:{'data_status':{'status':'AVAILABLE'}})
    assert value['data_status']['status']=='AVAILABLE'


def test_timeout_before_snapshot_read_keeps_unknown_and_logs_terminal(tmp_path,caplog):
    snapshot=tmp_path/'offline-context.json'
    snapshot.write_text(json.dumps({'industry_snapshot_date':'2026-09-30',
        'benchmark_snapshot_date':'2026-09-30'}),'utf-8')
    token=bind_request('f'*32)
    try:
        with caplog.at_level(logging.WARNING), pytest.raises(WebDataError) as caught:
            bounded_web_call(before_snapshot_worker_target,(str(snapshot),),root=tmp_path,seconds=8)
    finally:reset_request(token)
    assert snapshot.with_suffix('.ready').read_text('utf-8')=='TARGET_ENTERED'
    result=caught.value.diagnostics
    assert result['outcome']=='TIMEOUT' and result['reason_code']=='WEB_DEADLINE_EXCEEDED'
    assert result['industry_snapshot_date']==result['benchmark_snapshot_date']=='UNKNOWN'
    assert result['events']==[] and result['last_completed_stage']=='UNKNOWN'
    assert result['qfq_seconds']=='UNKNOWN' and result['request_id']=='f'*32
    assert any('REQUEST_COMPLETE' in r.message and 'f'*32 in r.message for r in caplog.records)
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


def test_wrapped_retry_counts_without_changing_retry_or_scoring(published,service):
    from app.web_backend import create_web_service
    root,_,_=published;manager=service.provider_manager;provider=manager.provider
    with patch('app.data.provider_manager.ProviderManager',return_value=manager):
        observed=create_web_service(root,manager.cache)
    calls=[]
    import pandas as pd
    def attempt():
        calls.append(1)
        if len(calls)==1:raise ProviderError('deadline exceeded')
        return pd.DataFrame({'date':pd.to_datetime(['2026-09-30']),'open':[10.]})
    manager._fetch(provider,'TEST','2026-09-30','2026-09-30','raw',attempt,False)
    summary=request_summary({'events':observed.web_diagnostic_events,'fetch_attempts_observed':True},rid='e'*32,outcome='SUCCESS',seconds=1)
    assert len(calls)==2 and summary['provider_retry_count']==1 and summary['raw_seconds']>=0
    assert manager.retries==2


def test_web_success_deployment_and_per_submit_cache_panel(service):
    data=service.analyze('000001').to_dict();data['data_status']['is_mock']=False;before=deepcopy(data)
    st.cache_data.clear()
    try:
        with patch('app.web_backend.analyze_stock',return_value=data) as analyze:
            app=AppTest.from_file(str(ROOT/'app/web.py')).run()
            assert any('部署版本' in e.label for e in app.expander)
            app.button(key='analyze_submit').click().run(timeout=20)
            first=deepcopy(app.session_state['request_diagnostics'])
            app.button(key='analyze_submit').click().run(timeout=20)
            second=app.session_state['request_diagnostics']
        assert not app.exception and analyze.call_count==1
        assert first['web_cache']=='MISS' and second['web_cache']=='HIT'
        assert first['request_id']!=second['request_id']
        assert len(app.json)==len(data['rules']) and len(data['rules'])==41
        assert data==before and app.session_state['analysis']['rules']==before['rules']
        assert any('请求诊断' in e.label for e in app.expander)
    finally:st.cache_data.clear()
