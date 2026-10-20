"""Deterministic offline task/UX contracts; fixtures are never market evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import Event, Thread, Timer
import time
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.web_tasks import TaskManager, Task
from app.web_freshness import date_notice
from app.web_feedback import validate_form_url, feedback_url, SETTING
from app.web_diagnostics import emit, safe_event
from app.web_backend import normalize_stock_code
from test_stage2_service import service
from tools.stage4c8_r1_workers import immediate_index_batch, slow_index_batch

ROOT=Path(__file__).resolve().parents[1]
GOOD={'data_status':{'status':'AVAILABLE','is_mock':False},'evaluation_date':'2026-09-30'}


def settled(manager,rid):
    assert manager.tasks[rid].done.wait(3), 'controlled fixture did not settle'
    return manager.poll(rid)


def test_submit_is_nonblocking_and_reuses_pending_alias(tmp_path):
    entered,release=Event(),Event()
    manager=TaskManager(tmp_path)
    calls=[]
    def loader(code):
        calls.append(code);entered.set()
        assert release.wait(3)
        return deepcopy(GOOD)
    start=time.monotonic()
    rid=manager.submit('600519',loader,preprocess=normalize_stock_code)
    assert time.monotonic()-start < .5
    try:
        assert entered.wait(2)
        assert manager.submit('SH600519',loader)==rid
        state=manager.poll(rid)
        assert state['status']=='RUNNING' and state['result'] is None
    finally:release.set()
    state=settled(manager,rid)
    assert state['status']=='SUCCESS' and state['result']==GOOD and len(calls)==1
    assert state['diagnostics']['web_cache']=='UNKNOWN'  # A plain callback is not an observed cache.
    first=state['elapsed_seconds']
    assert manager.poll(rid)['elapsed_seconds']==first


def test_timeout_in_cache_or_preworker_path_keeps_unknown_and_rejects_late_score(tmp_path):
    now=[0.];entered,release=Event(),Event()
    manager=TaskManager(tmp_path,clock=lambda:now[0],capacity=1)
    def cache_block(_):
        entered.set();assert release.wait(3)
        return deepcopy(GOOD)
    rid=manager.submit('600519',cache_block)
    try:
        assert entered.wait(2)
        now[0]=241
        state=manager.poll(rid)
        assert state['status']=='TIMEOUT' and state['result'] is None
        diag=state['diagnostics']
        assert diag['reason_code']=='WEB_REQUEST_DEADLINE_EXCEEDED'
        assert diag['provider_requests']==diag['raw_seconds']==diag['web_cache']=='UNKNOWN'
        assert manager.submit('600519',cache_block)==rid
        blocked=manager.submit('000001',lambda _:pytest.fail('must not start'))
        assert manager.poll(blocked)['status']=='BUSY'
    finally:release.set()
    assert manager.tasks[rid].exited.wait(2)
    assert manager.poll(rid)['status']=='TIMEOUT' and manager.poll(rid)['result'] is None
    assert manager.poll(rid)['diagnostics']['stock_trade_date']=='UNKNOWN'


def test_poll_expiry_never_waits_for_journal_lock_and_terminal_wins(tmp_path):
    now=[0.]
    manager=TaskManager(tmp_path,seconds=1,clock=lambda:now[0])
    task=Task('600519','600519.SH',manager.clock)
    manager.tasks[task.request_id]=task
    stale=manager._public(task)
    manager.directory.mkdir(parents=True)
    path=manager.directory/(task.request_id+'.json')
    path.write_text(json.dumps(stale),encoding='utf-8')
    locked,release=Event(),Event()
    def hold_disk():
        with manager.disk_lock:
            locked.set()
            assert release.wait(3)
    holder=Thread(target=hold_disk)
    stale_writer=None
    holder.start()
    try:
        assert locked.wait(2)
        stale_writer=Thread(target=manager._persist,args=(stale,))
        stale_writer.start()
        task.timer=Timer(.05,manager._expire,(task,))
        task.timer.start()
        now[0]=2.
        started=time.monotonic()
        state=manager.poll(task.request_id)
        assert time.monotonic()-started < .2
        assert state['status']=='TIMEOUT' and state['result'] is None
        assert json.loads(path.read_text(encoding='utf-8'))['status']=='RUNNING'
    finally:
        release.set()
        holder.join(2)
        if stale_writer is not None:
            stale_writer.join(2)
        if task.timer is not None:
            task.timer.join(2)
    assert not holder.is_alive()
    assert stale_writer is not None and not stale_writer.is_alive()
    assert task.timer is not None and not task.timer.is_alive()
    assert json.loads(path.read_text(encoding='utf-8'))['status']=='TIMEOUT'


def test_poll_expiry_never_waits_for_logging_handler_lock(tmp_path):
    now=[0.]
    manager=TaskManager(tmp_path,seconds=1,clock=lambda:now[0])
    task=Task('600519','600519.SH',manager.clock)
    manager.tasks[task.request_id]=task
    attempted,armed,poll_done=Event(),Event(),Event()
    records=[]
    errors=[]
    result={}
    class ControlledHandler(logging.Handler):
        def acquire(self):
            if armed.is_set():
                attempted.set()
            return super().acquire()
        def emit(self,record):
            records.append(record)
    handler=ControlledHandler()
    logger=logging.Logger('controlled-web-task')
    logger.addHandler(handler)
    handler.acquire()
    armed.set()
    def expire():
        try:
            manager._expire(task)
        except BaseException as exc:
            errors.append(exc)
    def poll():
        try:
            result['state']=manager.poll(task.request_id)
        except BaseException as exc:
            errors.append(exc)
        finally:
            poll_done.set()
    timer=Timer(.01,expire)
    poller=Thread(target=poll)
    poll_returned=False
    log_blocked=False
    try:
        with patch('app.web_tasks.log',logger):
            try:
                now[0]=2.
                poller.start()
                poll_returned=poll_done.wait(.5)
                timer.start()
                log_blocked=attempted.wait(2)
            finally:
                armed.clear()
                handler.release()
                if poller.ident is not None:
                    poller.join(2)
                if timer.ident is not None:
                    timer.join(2)
            # A second existing completion callback must not duplicate logging.
            manager._expire(task)
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert not poller.is_alive()
    assert not timer.is_alive()
    if errors:
        raise errors[0]
    assert poll_returned
    assert result['state']['status']=='TIMEOUT'
    assert result['state']['result'] is None
    assert log_blocked
    assert len(records)==1
    payload=json.loads(records[0].getMessage().split(' ',1)[1])
    assert payload['request_id']==task.request_id
    assert payload['status']=='TIMEOUT'
    assert json.loads((manager.directory/(task.request_id+'.json')).read_text())['status']=='TIMEOUT'


def test_initially_expired_execute_finishes_timeout_without_waiting_for_timer(tmp_path):
    now=[0.]
    manager=TaskManager(tmp_path,seconds=1,clock=lambda:now[0])
    original=manager._accepted
    calls=[]
    def expired(task):
        now[0]=2.
        return original(task)
    with patch.object(manager,'_accepted',side_effect=expired):
        rid=manager.submit('600519',lambda code:calls.append(code))
        assert manager.tasks[rid].done.wait(10)
        assert manager.tasks[rid].exited.wait(10)
        state=manager.poll(rid)
    assert state['status']=='TIMEOUT'
    assert state['result'] is None
    assert calls==[]


def test_expired_preprocess_never_calls_loader_and_resets_budget(tmp_path):
    from app.web_budget import remaining_seconds
    now=[0.]
    manager=TaskManager(tmp_path,clock=lambda:now[0])
    calls=[]
    def preprocess(code):
        now[0]=241
        return code
    rid=manager.submit('600519',lambda code:calls.append(code) or deepcopy(GOOD),
                       preprocess=preprocess)
    state=settled(manager,rid)
    assert state['status']=='TIMEOUT'
    assert state['result'] is None
    assert calls==[]
    assert remaining_seconds(9)==9


def test_observed_analysis_restores_outer_budget_same_thread_on_success_and_error():
    from app.web_budget import bind_remaining, remaining_seconds, reset_remaining
    from app.web_observability import run_observed_analysis
    outer=bind_remaining(lambda:7.)
    try:
        def success(_):
            assert remaining_seconds(240)==3.
            return deepcopy(GOOD)
        result,_=run_observed_analysis('600519',success,remaining_budget=lambda:3.)
        assert result==GOOD
        assert remaining_seconds(240)==7.
        def failure(_):
            assert remaining_seconds(240)==2.
            raise RuntimeError('controlled')
        with pytest.raises(Exception):
            run_observed_analysis('600519',failure,remaining_budget=lambda:2.)
        assert remaining_seconds(240)==7.
    finally:
        reset_remaining(outer)


def test_expired_before_preprocess_calls_neither_preprocess_nor_loader(tmp_path):
    from app.web_observability import run_observed_analysis
    calls=[]
    with pytest.raises(Exception) as caught:
        run_observed_analysis('600519',lambda code:calls.append(('loader',code)),
            preprocess=lambda code:calls.append(('preprocess',code)),
            accept_result=lambda:False,remaining_budget=lambda:0)
    assert '请求时限' in str(caught.value)
    assert calls==[]


@pytest.mark.parametrize('seconds',[0,-1,241])
def test_bounded_call_validates_declared_seconds_before_request_budget(tmp_path,seconds):
    from app.web_budget import bind_remaining, reset_remaining
    from app.web_runtime import bounded_web_call
    token=bind_remaining(lambda:1)
    try:
        with pytest.raises(ValueError,match='Invalid Web deadline'):
            bounded_web_call(immediate_index_batch,(),root=tmp_path,seconds=seconds)
    finally:
        reset_remaining(token)


def test_consumed_request_budget_sets_actual_worker_boundary(tmp_path):
    from app.web_observability import run_observed_analysis
    from app.web_runtime import bounded_web_call
    now=[10.]
    captured={}
    def preprocess(code):
        now[0]=35.
        return code
    def boundary(*args,**kwargs):
        captured.update(kwargs)
        return deepcopy(GOOD)
    def loader(_):
        return bounded_web_call(lambda:None,(),root=tmp_path,seconds=100)
    with patch('app.web_runtime.time.monotonic',side_effect=lambda:now[0]), \
         patch('app.web_runtime._bounded_web_call',side_effect=boundary):
        result,_=run_observed_analysis(
            '600519',loader,preprocess=preprocess,
            remaining_budget=lambda:110.-now[0])
    assert result==GOOD
    assert captured['seconds']==75.
    assert captured['deadline']-captured['started']==75.


def test_remaining_request_budget_reaches_worker_boundary(tmp_path):
    now=[10.]
    manager=TaskManager(tmp_path,seconds=100,clock=lambda:now[0])
    observed=[]
    def loader(_):
        from app.web_budget import remaining_seconds
        observed.append(remaining_seconds(240))
        return deepcopy(GOOD)
    def preprocess(code):
        now[0]=35.
        return code
    rid=manager.submit('600519',loader,preprocess=preprocess)
    assert settled(manager,rid)['status']=='SUCCESS'
    assert observed==[75.]


def test_expired_backend_calls_no_normalizer_or_initializer():
    from app.web_backend import analyze_stock
    from app.web_budget import bind_remaining, reset_remaining
    token=bind_remaining(lambda:0)
    try:
        with patch('app.web_backend.normalize_stock_code') as normalize, \
             patch('app.web_backend.create_web_service') as initialize:
            with pytest.raises(Exception) as caught:
                analyze_stock('600519')
        assert '请求时限' in str(caught.value)
        normalize.assert_not_called()
        initialize.assert_not_called()
    finally:
        reset_remaining(token)


def test_preinitialized_expired_analysis_starts_no_policy_or_worker():
    from app.web_backend import analyze_stock
    from app.web_budget import bind_remaining, reset_remaining
    provider=type('Provider',(),{'is_mock':property(
        lambda self:pytest.fail('provider policy must not run'))})()
    service=type('Service',(),{})()
    service.provider_manager=type('Manager',(),{'provider':provider})()
    remaining=[1.]
    def initialize():
        remaining[0]=0.
        return service
    token=bind_remaining(lambda:remaining[0])
    try:
        with patch('app.web_backend.create_web_service',side_effect=initialize), \
             patch('app.web_runtime.bounded_web_call') as worker:
            with pytest.raises(Exception) as caught:
                analyze_stock('600519')
        assert '请求时限' in str(caught.value)
        worker.assert_not_called()
    finally:
        reset_remaining(token)


def test_index_batch_spawn_starts_with_sufficient_budget(tmp_path):
    from app.web_runtime import bounded_web_call
    marker=tmp_path/'spawn-started'
    assert bounded_web_call(immediate_index_batch,(str(marker),),
                            root=tmp_path,seconds=20)==[]
    assert marker.read_text('utf-8')=='started'


def test_index_batch_timeout_keeps_capacity_until_owned_cleanup(tmp_path):
    from app.web_runtime import bounded_web_call
    import ctypes
    import os
    manager=TaskManager(tmp_path,seconds=8,capacity=1)
    marker=tmp_path/'spawn-started'
    calls=[]
    rid=manager.submit('INDEX_DISPLAY',
        lambda _:bounded_web_call(slow_index_batch,(str(marker),),
                                  root=tmp_path,seconds=3))
    started=time.monotonic()
    deadline=started+8
    while time.monotonic()<deadline and not marker.exists():
        time.sleep(.01)
    assert marker.exists()
    owned=json.loads(marker.read_text('utf-8'))
    assert owned['started'] and owned['pid'] and owned['descendant_pid']
    assert manager.poll(rid)['status']=='RUNNING'
    blocked=manager.submit('600519',lambda code:calls.append(code) or deepcopy(GOOD))
    assert manager.poll(blocked)['status']=='BUSY'
    assert calls==[]
    assert manager.tasks[rid].done.wait(10)
    state=manager.poll(rid)
    assert state['status']=='TIMEOUT'
    assert 3 <= state['elapsed_seconds'] <= 8
    assert manager.tasks[rid].exited.wait(10)
    def alive(pid):
        if os.name=='nt':
            from ctypes import wintypes
            api=ctypes.WinDLL('kernel32',use_last_error=True)
            api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            api.OpenProcess.restype=wintypes.HANDLE
            api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            api.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=api.OpenProcess(0x1000,False,pid)
            if not handle:
                assert ctypes.get_last_error()==87, 'cannot verify owned process state'
                return False
            code=wintypes.DWORD()
            try:
                assert api.GetExitCodeProcess(handle,ctypes.byref(code))
                return code.value==259
            finally:
                api.CloseHandle(handle)
        try:
            os.kill(pid,0)
            return True
        except ProcessLookupError:
            return False
    assert not alive(owned['pid'])
    assert not alive(owned['descendant_pid'])
    jobs=tmp_path/'outputs/runtime/web-jobs'
    assert not jobs.exists() or not list(jobs.iterdir())
    restored=manager.submit('000001',lambda _:deepcopy(GOOD))
    assert manager.tasks[restored].done.wait(10)
    assert manager.poll(restored)['status']=='SUCCESS'
    assert manager.tasks[restored].exited.wait(10)


def test_timer_expires_without_browser_poll(tmp_path):
    entered,release=Event(),Event()
    manager=TaskManager(tmp_path,seconds=.15)
    def loader(_):entered.set();release.wait(3);return deepcopy(GOOD)
    rid=manager.submit('600519',loader)
    try:
        assert entered.wait(2)
        assert manager.tasks[rid].done.wait(2)
        assert manager.tasks[rid].status=='TIMEOUT'
    finally:release.set()
    assert manager.tasks[rid].exited.wait(2)


@pytest.mark.parametrize('failure',['exception','unavailable','mock','input'])
def test_failure_redacted_terminal_and_no_score(tmp_path,failure):
    manager=TaskManager(tmp_path)
    def loader(_):
        if failure=='exception':raise RuntimeError('SYNTHETIC_PRIVATE_ERROR')
        value=deepcopy(GOOD)
        if failure=='unavailable':value['data_status']['status']='UNAVAILABLE'
        if failure=='mock':value['data_status']['is_mock']=True
        return value
    rid=manager.submit('invalid' if failure=='input' else '600519',loader,preprocess=normalize_stock_code)
    state=settled(manager,rid)
    assert state['status']=='FAILURE' and state['result'] is None
    assert state['diagnostics']['outcome']=='FAILURE'
    assert 'SYNTHETIC_PRIVATE_ERROR' not in json.dumps(state)
    assert state['request_id']==rid


def test_restart_and_missing_request_never_restore_score_or_resubmit(tmp_path):
    manager=TaskManager(tmp_path)
    rid=manager.submit('600519',lambda _:deepcopy(GOOD))
    assert settled(manager,rid)['status']=='SUCCESS'
    assert manager.tasks[rid].exited.wait(2)
    journal=json.loads((manager.directory/(rid+'.json')).read_text())
    assert 'result' not in journal and 'code' not in journal
    restarted=TaskManager(tmp_path)
    assert restarted.poll(rid)['status']=='INTERRUPTED'
    assert restarted.poll(rid)['result'] is None
    assert restarted.poll('f'*32)['status']=='INTERRUPTED'
    assert restarted.poll('../private') is None


def test_actual_progress_not_fake_provider_metrics(tmp_path):
    manager=TaskManager(tmp_path)
    def loader(_):
        emit(safe_event('service_init','OK',seconds=.1))
        raise RuntimeError('unobserved provider')
    rid=manager.submit('600519',loader)
    diag=settled(manager,rid)['diagnostics']
    assert diag['last_completed_stage']=='service_init'
    assert diag['provider_requests']=='UNKNOWN'


def test_same_input_41_scores_risk_b1_b2_unchanged(service,tmp_path):
    data=service.analyze('000001').to_dict();data['data_status']['is_mock']=False
    before=deepcopy(data)
    manager=TaskManager(tmp_path)
    rid=manager.submit('000001',lambda _:data)
    after=settled(manager,rid)['result']
    assert len(after['rules'])==41 and after==before and data==before


def test_finish_race_cannot_accept_result_after_deadline(tmp_path):
    now=[0.]
    manager=TaskManager(tmp_path,clock=lambda:now[0])
    task=Task('600519','600519.SH',manager.clock)
    manager.tasks[task.request_id]=task
    now[0]=241
    assert manager._finish(task,'SUCCESS',result=GOOD)
    state=manager.poll(task.request_id)
    assert state['status']=='TIMEOUT' and state['result'] is None


def test_thread_start_failure_is_safe_terminal(tmp_path):
    manager=TaskManager(tmp_path)
    with patch('app.web_tasks.Thread') as thread:
        thread.return_value.start.side_effect=RuntimeError('SYNTHETIC_PRIVATE_START')
        rid=manager.submit('600519',lambda _:pytest.fail('must not start'))
    state=manager.poll(rid)
    assert state['status']=='FAILURE' and state['result'] is None
    assert state['diagnostics']['reason_code']=='WEB_TASK_START_FAILED'
    assert state['diagnostics']['provider_requests']=='UNKNOWN'
    assert 'SYNTHETIC_PRIVATE_START' not in json.dumps(state)


def test_index_refresh_is_background_and_does_not_block_navigation(tmp_path):
    manager=TaskManager(tmp_path)
    entered,release=Event(),Event()
    def loader():
        entered.set();assert release.wait(10)
        return [{'name':'OFFLINE INDEX FIXTURE','date':'2026-09-30','close':1,'change':0,
                 'percent':0,'trend':[1],'symbol':'000001.SH'}]
    st.cache_data.clear()
    with patch('app.web_tasks.task_manager',return_value=manager), \
         patch('app.web_runtime.bounded_web_call',
               side_effect=lambda target,args,**kwargs:loader()):
        app=AppTest.from_file(str(ROOT/'app/web.py'),default_timeout=8).run()
        try:
            app.button(key='load_indices').click().run(timeout=8)
            assert entered.wait(2)
            rid=app.session_state['index_task']
            assert manager.poll(rid)['status']=='RUNNING'
            app.button(key='nav_rules').click().run(timeout=8)
            assert app.session_state['view']=='rules' and not app.exception
        finally:release.set()
        assert settled(manager,rid)['status']=='SUCCESS'
        app.button(key='nav_home').click().run(timeout=8)
        assert not app.exception
        assert app.session_state['market_snapshot'][0]['name']=='OFFLINE INDEX FIXTURE'
    st.cache_data.clear()


@pytest.mark.parametrize('source,reference,status,expected',[
    ('2026-09-20','2026-09-29',None,'DATA_STALE'),
    ('2026-09-30',None,None,'历史数据'),
    (None,None,None,'UNKNOWN'),
    ('invalid',None,None,'UNKNOWN'),
    ('2026-09-30',None,'DATA_ERROR','DATA_ERROR'),
    ('2026-09-30',None,'DATA_STALE','DATA_STALE'),
    ('2026-09-30','2026-09-30','BENCHMARK_SNAPSHOT_DATA_STALE','DATA_STALE'),
    ('2026-09-30','2026-09-30','UNKNOWN','UNKNOWN'),
    ('2026-09-30','2026-09-30',None,'与评价日期一致'),
])
def test_date_status_does_not_guess_trading_calendar(source,reference,status,expected):
    _,text=date_notice(source,reference=reference,status=status,now=datetime(2026,10,1,tzinfo=timezone.utc))
    assert expected in text
    if reference is None and status is None and source=='2026-09-30':assert 'DATA_STALE' not in text


def test_future_date_rejected_before_reference_equality():
    level,text=date_notice('2026-10-02',reference='2026-10-02',
                           now=datetime(2026,10,1,tzinfo=timezone.utc))
    assert level=='error'
    assert '晚于当前日期' in text
    assert '与评价日期一致' not in text


@pytest.mark.parametrize('url,valid',[
    ('https://forms.gle/offlineFixture',True),
    ('https://docs.google.com/forms/d/e/offlineFixture/viewform',True),
    ('https://tally.so/r/offlineFixture',True),
    ('https://docs.google.com/forms/d/e/offlineFixture/edit',False),
    ('https://example.invalid/feedback',False),('http://forms.gle/offlineFixture',False),
    ('https://forms.gle.example.invalid/offlineFixture',False),
    ('https://tally.so/r/offlineFixture?token=placeholder',False),
    ('https://user:placeholder@tally.so/r/offlineFixture',False),
    ('https://tally.so:4433/r/offlineFixture',False),
])
def test_form_link_safety(url,valid):
    assert bool(validate_form_url(url))==valid


def test_feedback_configuration_precedence_no_fake_save(monkeypatch):
    monkeypatch.delenv(SETTING,raising=False)
    assert feedback_url({}) is None
    assert feedback_url({SETTING:'https://tally.so/r/offlineFixture'})
    monkeypatch.setenv(SETTING,'https://example.invalid/unsafe')
    assert feedback_url({SETTING:'https://tally.so/r/offlineFixture'}) is None


def test_ui_pending_navigation_and_terminal_failure_without_blocking(tmp_path):
    manager=TaskManager(tmp_path)
    entered,release=Event(),Event()
    def loader(_):
        entered.set();assert release.wait(10)
        raise RuntimeError('SYNTHETIC_PRIVATE_UI_ERROR')
    st.cache_data.clear()
    with patch('app.web_tasks.task_manager',return_value=manager), \
         patch('app.web_backend.analyze_stock',side_effect=loader):
        app=AppTest.from_file(str(ROOT/'app/web.py'),default_timeout=8).run()
        try:
            app.button(key='analyze_submit').click().run(timeout=8)
            assert entered.wait(2)
            rid=app.session_state['analysis_task']
            assert any(rid in c.value for c in app.caption)
            assert manager.poll(rid)['status']=='RUNNING' and not app.metric
            app.button(key='theme_toggle').click().run(timeout=8)
            assert app.session_state['theme']=='dark' and not app.exception
        finally:release.set()
        assert settled(manager,rid)['status']=='FAILURE'
        app.run(timeout=8)
        assert app.error and not app.metric and not app.exception
        assert 'SYNTHETIC_PRIVATE_UI_ERROR' not in str(app)
    st.cache_data.clear()


def test_ui_same_running_request_keeps_accepted_result_on_resubmit(tmp_path,service):
    manager=TaskManager(tmp_path)
    success_persisting,release_persist=Event(),Event()
    original_persist=manager._persist
    result=service.analyze('000001').to_dict()
    result['data_status']['is_mock']=False
    assert len(result['rules'])==41
    def persist(state):
        if state['status']=='SUCCESS':
            success_persisting.set()
            assert release_persist.wait(10)
        return original_persist(state)
    st.cache_data.clear()
    with patch('app.web_tasks.task_manager',return_value=manager), \
         patch('app.web_backend.analyze_stock',return_value=result), \
         patch.object(manager,'_persist',side_effect=persist):
        app=AppTest.from_file(str(ROOT/'app/web.py'),default_timeout=8).run()
        rid=None
        try:
            app.text_input[0].set_value('000001')
            app.button(key='analyze_submit').click().run(timeout=8)
            rid=app.session_state['analysis_task']
            assert success_persisting.wait(3)
            app.run(timeout=8)
            assert app.session_state['analysis']==result
            app.button(key='analyze_submit').click().run(timeout=8)
            assert app.session_state['analysis_task']==rid
            assert app.session_state['analysis']==result
            assert app.session_state['handled_task']==rid
        finally:
            release_persist.set()
        assert manager.tasks[rid].exited.wait(3)
    st.cache_data.clear()


def test_feedback_ui_explicitly_unconfigured_no_success(monkeypatch):
    monkeypatch.delenv(SETTING,raising=False)
    with patch('app.web_feedback.feedback_url',return_value=None):
        app=AppTest.from_string('from app.web_feedback import render_feedback; render_feedback()').run()
    assert any('不能提交或保存' in x.value for x in app.info)
    assert not app.success and not app.get('link_button')


def test_feedback_ui_external_form_is_not_a_submission():
    with patch('app.web_feedback.feedback_url',return_value='https://tally.so/r/offlineFixture'):
        app=AppTest.from_string('from app.web_feedback import render_feedback; render_feedback()').run()
    assert app.get('link_button') and not app.success
    assert any('打开链接不代表已提交' in x.value for x in app.caption)
