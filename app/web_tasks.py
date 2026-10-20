"""Bounded UI tasks. Public scores remain outputs of the existing loader.

Only the script thread renders Streamlit. Background threads supervise the
existing process deadline; they never attach a session's ScriptRunContext.
The UI deadline includes preprocessing, cache locks and initialization. Python
cannot kill a stuck thread: capacity stays occupied until it actually exits.
"""
from copy import deepcopy
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from threading import Event, Lock, Thread, Timer
import time
from uuid import uuid4

from app.web_diagnostics import WebDataError, request_summary, clean_events, safe_event
from app.web_observability import run_observed_analysis

STATES = {'RUNNING', 'SUCCESS', 'FAILURE', 'TIMEOUT', 'INTERRUPTED', 'BUSY'}
DEADLINE = 240
log = logging.getLogger(__name__)


class Task:
    def __init__(self, code, key, clock):
        self.request_id = uuid4().hex
        self.code, self.key = code, key
        self.started = clock()
        self.status = 'RUNNING'
        self.result = None
        self.diagnostics = {}
        self.message = ''
        self.elapsed = None
        self.events = []
        self.done = Event()
        self.exited = Event()
        self.timer = None
        self.terminal_logged = False


def task_key(code):
    # Input validation still belongs to the existing Web preprocessor. This key
    # only coalesces common aliases; it is not a security/symbol resolver.
    code = str(code).strip().upper()
    if re.fullmatch(r'(SH|SZ|BJ)\d{6}', code):
        return code[2:] + '.' + code[:2]
    if re.fullmatch(r'\d{6}', code):
        return code + ('.SH' if code.startswith('6') else '.SZ')
    return code


class TaskManager:
    def __init__(self, root, *, seconds=DEADLINE, capacity=2, clock=time.monotonic):
        if not 0 < seconds <= DEADLINE or capacity < 1:
            raise ValueError('INVALID_TASK_BUDGET')
        self.directory = Path(root)/'outputs/runtime/web-ui-tasks'
        self.seconds, self.capacity, self.clock = seconds, capacity, clock
        self.lock = Lock()
        self.disk_lock = Lock()
        self.tasks = {}

    def _accepted(self, task):
        with self.lock:
            return task.status == 'RUNNING' and self.clock()-task.started < self.seconds

    def _public(self, task):
        return dict(request_id=task.request_id, status=task.status,
                    elapsed_seconds=task.elapsed if task.elapsed is not None else round(max(0, self.clock()-task.started), 2),
                    message=task.message, diagnostics=deepcopy(task.diagnostics))

    def _persist(self, state):
        # Journal only the safe terminal/ongoing envelope, not scores, raw input,
        # exception strings, credentials, portfolio or user information.
        try:
            # Serialize journal writes off the UI thread. An older RUNNING
            # envelope must never overwrite a terminal state during a race.
            with self.disk_lock:
                with self.lock:
                    task=self.tasks.get(state['request_id'])
                    if task is not None and task.status!=state['status']:return
                self.directory.mkdir(parents=True, exist_ok=True)
                path=self.directory/(state['request_id']+'.json')
                temporary=path.with_suffix('.tmp')
                temporary.write_text(json.dumps(state, allow_nan=False), encoding='utf-8')
                temporary.replace(path)
        except (OSError, ValueError, TypeError):
            pass  # In-memory status still works; no false persistence guarantee.

    def _finish(self, task, status, *, result=None, diagnostics=None, message='', persist=True):
        with self.lock:
            if task.status != 'RUNNING':
                # A poll may commit terminal state without waiting for disk.
                # A later timer/worker callback must still journal that state.
                finished=False
                state=self._public(task) if persist else None
            else:
                finished=True
                if status=='SUCCESS' and self.clock()-task.started>=self.seconds:
                    status,result,message='TIMEOUT',None,'本次分析已达到240秒请求时限，不展示迟到的新评分。'
                    diagnostics=request_summary(dict(events=task.events,partial_events=True,
                        reason_code='WEB_REQUEST_DEADLINE_EXCEEDED'),rid=task.request_id,
                        outcome='TIMEOUT',seconds=self.clock()-task.started)
                task.status, task.result = status, result
                task.elapsed=round(max(0,self.clock()-task.started),2)
                task.diagnostics, task.message = diagnostics or {}, message
                state=self._public(task)
                task.done.set()
            emit_terminal=persist and not task.terminal_logged
            if emit_terminal:
                task.terminal_logged=True
        if finished and persist and task.timer is not None:
            task.timer.cancel()
        if persist:
            self._persist(state)
        if emit_terminal:
            log.warning('QUANTSCORE_WEB_TASK %s', json.dumps(state, allow_nan=False))
        return finished

    def _expire(self, task, *, persist=True):
        with self.lock:
            events=list(task.events)
        diag=request_summary(dict(events=events, partial_events=True,
            reason_code='WEB_REQUEST_DEADLINE_EXCEEDED'), rid=task.request_id,
            outcome='TIMEOUT', seconds=max(0,self.clock()-task.started))
        self._finish(task, 'TIMEOUT', diagnostics=diag,
            message='本次分析已达到240秒请求时限，不展示新评分。后台清理可能仍在进行；请稍后手动重试。',
            persist=persist)

    def submit(self, code, loader, *, deployment=None, preprocess=None, cache_observable=False):
        key=task_key(code)
        with self.lock:
            # Keep active threads even after UI timeout, so a hanging cache lock
            # cannot create an unbounded queue of replacement analyses.
            running=[t for t in self.tasks.values() if not t.exited.is_set()]
            duplicate=next((t for t in running if t.key==key),None)
            if duplicate is not None:
                return duplicate.request_id
            task=Task(code,key,self.clock)
            self.tasks[task.request_id]=task
            busy=len(running)>=self.capacity
            # Retain at most 64 completed result envelopes in process memory.
            finished=[t for t in self.tasks.values() if t.exited.is_set()]
            for old in finished[:-64]:self.tasks.pop(old.request_id,None)
        if busy:
            task.exited.set()
            diag=request_summary({'events':[safe_event('web_admission','FAILED',
                reason_code='WEB_CAPACITY_REJECTED')],'reason_code':'WEB_CAPACITY_REJECTED'},
                rid=task.request_id,outcome='FAILURE',seconds=self.clock()-task.started)
            self._finish(task,'BUSY',diagnostics=diag,
                message='当前分析服务繁忙，未启动新行情请求。请稍后重试。')
            return task.request_id
        def progress(event):
            with self.lock:
                if task.status=='RUNNING':task.events=clean_events([*task.events,event])
        def execute():
            try:
                with self.lock:state=self._public(task)
                self._persist(state)
                if not self._accepted(task):
                    self._expire(task)
                    return
                data,diag=run_observed_analysis(code,loader,cache_observable=cache_observable,
                    deployment=deployment,preprocess=preprocess,request_id=task.request_id,
                    accept_result=lambda:self._accepted(task),on_event=progress,
                    remaining_budget=lambda:max(
                        0.0,self.seconds-(self.clock()-task.started)))
                if not self._accepted(task):
                    self._expire(task)
                elif data.get('data_status',{}).get('is_mock') or data.get('data_status',{}).get('status')=='UNAVAILABLE':
                    source=dict(diag);source['reason_code']='DATA_UNAVAILABLE'
                    diag=request_summary(source,rid=task.request_id,outcome='FAILURE',
                        seconds=self.clock()-task.started,web_cache=diag.get('web_cache','UNKNOWN'))
                    self._finish(task,'FAILURE',diagnostics=diag,message='真实数据暂不可用，本次不展示评分。')
                else:self._finish(task,'SUCCESS',result=data,diagnostics=diag)
            except WebDataError as exc:
                status='TIMEOUT' if exc.diagnostics.get('outcome')=='TIMEOUT' else 'FAILURE'
                self._finish(task,status,diagnostics=exc.diagnostics,message=str(exc))
            except Exception:
                diag=request_summary({},rid=task.request_id,outcome='FAILURE',seconds=self.clock()-task.started)
                self._finish(task,'FAILURE',diagnostics=diag,message='分析未完成，本次不展示新评分。')
            finally:
                task.exited.set()
        task.timer=Timer(self.seconds, self._expire, (task,))
        task.timer.daemon=True
        try:
            task.timer.start()
            Thread(target=execute, name='quantscore-analysis', daemon=True).start()
        except Exception:
            task.exited.set()
            seconds=self.clock()-task.started
            diag=request_summary({'events':[safe_event('web_task_start','FAILED',seconds=seconds,
                reason_code='WEB_TASK_START_FAILED')],'reason_code':'WEB_TASK_START_FAILED'},
                rid=task.request_id,outcome='FAILURE',seconds=seconds)
            self._finish(task,'FAILURE',diagnostics=diag,message='分析任务未能启动，请稍后重试。')
        return task.request_id

    def poll(self, rid):
        if not isinstance(rid,str) or not re.fullmatch('[a-f0-9]{32}',rid):
            return None
        with self.lock:task=self.tasks.get(rid)
        if task is not None:
            if task.status=='RUNNING' and self.clock()-task.started>=self.seconds:
                self._expire(task, persist=False)
            with self.lock:
                state=self._public(task)
                state['result']=task.result if task.status=='SUCCESS' else None
            return state
        # A journal is not a recoverable score cache. On a new process, report
        # interruption/result loss and require explicit re-submission.
        path=self.directory/(rid+'.json')
        exists=False
        try:exists=path.is_file() and not path.is_symlink()
        except OSError:pass
        return dict(request_id=rid,status='INTERRUPTED',elapsed_seconds=None,result=None,diagnostics={},
                    message='服务已重启或会话记录不可恢复。没有恢复本次评分，请手动重新分析。'
                            if exists else '当前服务找不到该请求，可能已重启或记录已释放。请手动重新分析。')

    def wait_briefly(self, rid):
        # Optional fast cache-hit path; never blocks the UI on a data source.
        with self.lock:task=self.tasks.get(rid)
        if task is not None:task.done.wait(.05)


@lru_cache(maxsize=1)
def task_manager(root):
    return TaskManager(root)
