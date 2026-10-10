"""Hard Web request deadline, with cleanup of only the owned process tree."""
import ctypes
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import signal
import time
from uuid import uuid4

from app.web_diagnostics import (WebDataError, bind_sink, reset_sink, safe_event, error_reason,
    bind_request, reset_request, current_request, clean_events, request_summary, publish_terminal)


def _windows_job(process):
    """A private kill-on-close job also contains the SDK grandchildren."""
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_=[('per_process',ctypes.c_int64),('per_job',ctypes.c_int64),
                  ('flags',wintypes.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),
                  ('active',wintypes.DWORD),('affinity',ctypes.c_size_t),
                  ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(n,ctypes.c_uint64) for n in ('reads','writes','others','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('process_mem',ctypes.c_size_t),
                  ('job_mem',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
    api.CreateJobObjectW.restype=wintypes.HANDLE
    api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.CreateJobObjectW(None,None)
    if not handle: raise OSError('WEB_JOB_CREATION_FAILED')
    info=Extended();info.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not api.AssignProcessToJobObject(handle,process.sentinel):
        api.CloseHandle(handle)
        raise OSError('WEB_JOB_ATTACHMENT_FAILED')
    return lambda:api.CloseHandle(handle)


def _worker(gate,target,args,directory,rid):
    directory=Path(directory)
    os.environ.update({k:str(directory) for k in ('TMP','TEMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(directory)
    if os.name!='nt': os.setsid()
    gate.recv()  # Parent attaches the owned Windows job before SDK children exist.
    gate.close()
    events=[];metadata={};request_token=bind_request(rid)
    def progress(event):
        events.append(event)
        for key in ('stock_trade_date','industry_snapshot_date','benchmark_snapshot_date'):
            if key in event:metadata[key]=event[key]
        if event['stage']=='fetch_group':metadata['fetch_attempts_observed']=True
        if event['stage']=='fetch_group' and event.get('adjustment') in {'raw','qfq'}:
            if event['status']=='START':
                metadata['active_fetch']={'adjustment':event['adjustment'],'started_monotonic':time.monotonic()}
            else:metadata.pop('active_fetch',None)
        temporary=directory/'diagnostic.partial'
        temporary.write_text(json.dumps({'events':events[-100:],**metadata}),'utf-8')
        temporary.replace(directory/'diagnostic.json')
    token=bind_sink(progress)
    try:
        output={'ok':True,'value':target(*args)}
    except Exception as exc:
        output={'ok':False,'diagnostics':{'events':events[-100:],
                'reason_code':error_reason(exc)}}
    finally:
        reset_sink(token)
        reset_request(request_token)
    temporary=directory/'response.partial'
    temporary.write_text(json.dumps(output,ensure_ascii=False,allow_nan=False),'utf-8')
    temporary.replace(directory/'response.json')


def bounded_web_call(target,args,*,root,seconds=240):
    if not 0<seconds<=240: raise ValueError('Invalid Web deadline')
    root=Path(root).resolve()
    directory=root/'outputs/runtime/web-jobs'/uuid4().hex
    directory.mkdir(parents=True)
    context=mp.get_context('spawn')
    parent,child=context.Pipe()
    rid=current_request() or uuid4().hex
    process=context.Process(target=_worker,args=(child,target,args,str(directory),rid),daemon=False)
    closer=None;started=time.monotonic()
    def failure(message,reason):
        try:
            saved=json.loads((directory/'diagnostic.json').read_text('utf-8'))
            saved['events']=clean_events(saved.get('events'))
        except (OSError,ValueError,KeyError,TypeError): saved={}
        pending=saved.pop('active_fetch',None)
        if isinstance(pending,dict) and pending.get('adjustment') in {'raw','qfq'}:
            began=pending.get('started_monotonic')
            if isinstance(began,(int,float)) and started<=began<=time.monotonic():
                saved.setdefault('events',[]).append(safe_event('fetch_group',
                    'TIMEOUT' if reason=='WEB_DEADLINE_EXCEEDED' else 'FAILED',
                    request_id=rid,adjustment=pending['adjustment'],reason_code=reason,
                    seconds=time.monotonic()-began))
        saved.update(reason_code=reason,partial_events=True)
        summary=request_summary(saved,rid=rid,outcome='TIMEOUT' if reason=='WEB_DEADLINE_EXCEEDED' else 'FAILURE',
                                seconds=time.monotonic()-started,layer='WORKER')
        summary.update(total_backend_seconds=summary['total_latency_seconds'],web_deadline_seconds=seconds)
        publish_terminal(summary)
        return WebDataError(message,summary)
    try:
        process.start();child.close()
        if os.name=='nt': closer=_windows_job(process)
        parent.send('GO');parent.close()
        while process.is_alive() and time.monotonic()-started<seconds:
            process.join(min(.1,max(.001,seconds-(time.monotonic()-started))))
        if process.is_alive():
            raise failure('单股分析达到运行时限，已停止本次请求；未生成新评分，请稍后重试。','WEB_DEADLINE_EXCEEDED')
        path=directory/'response.json'
        if process.exitcode!=0 or not path.exists() or path.stat().st_size>16*1024*1024:
            raise failure('单股分析未返回完整结果；本次不展示新评分。','WORKER_RESPONSE_INVALID')
        result=json.loads(path.read_text('utf-8'))
        if not result['ok']:
            reason=result.get('diagnostics',{}).get('reason_code','WORKER_ERROR')
            from app.web_diagnostics import REASONS
            raise failure('单股数据源或快照暂不可用；本次不展示新评分，请稍后重试。',
                          reason if reason in REASONS else 'WORKER_ERROR')
        output=result['value']
        if isinstance(output,dict):
            elapsed=round(time.monotonic()-started,4)
            output.setdefault('web_latency',{})['total_backend_seconds']=elapsed
            original=output.get('web_diagnostics',{})
            source=dict(original) if isinstance(original,dict) else {}
            try:
                progress=json.loads((directory/'diagnostic.json').read_text('utf-8'))
                source['events']=clean_events(progress.get('events'))
                for key in ('stock_trade_date','industry_snapshot_date','benchmark_snapshot_date','fetch_attempts_observed'):
                    if key in progress and not source.get(key):source[key]=progress[key]
            except (OSError,ValueError,AttributeError):pass
            summary=request_summary(source,rid=rid,
                outcome='FAILURE' if output.get('data_status',{}).get('status')=='UNAVAILABLE' else 'SUCCESS',
                seconds=elapsed,layer='WORKER')
            # Preserve raw instrumentation for the Web summary and cached-origin
            # attribution. All fields already cross the existing worker boundary.
            if isinstance(source,dict):
                source.update(request_id=rid,total_backend_seconds=elapsed,web_deadline_seconds=seconds)
                output['web_diagnostics']=source
            publish_terminal(summary)
        return output
    except WebDataError:
        raise
    except Exception:
        raise failure('单股分析未返回完整结果；本次不展示新评分。','WORKER_ERROR') from None
    finally:
        parent.close();child.close()
        if closer:
            closer()  # Stops all owned descendants, including on success.
        elif os.name!='nt' and process.pid:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        if process.pid and process.is_alive():
            process.terminate();process.join(2)
            if process.is_alive(): process.kill();process.join(2)
        else:
            process.join(.2) if process.pid else None
        resolved=directory.resolve()
        if resolved.parent==(root/'outputs/runtime/web-jobs').resolve():
            shutil.rmtree(resolved,ignore_errors=True)
