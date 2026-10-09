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

from app.web_diagnostics import WebDataError, bind_sink, reset_sink, safe_event, error_reason


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


def _worker(gate,target,args,directory):
    directory=Path(directory)
    os.environ.update({k:str(directory) for k in ('TMP','TEMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(directory)
    if os.name!='nt': os.setsid()
    gate.recv()  # Parent attaches the owned Windows job before SDK children exist.
    gate.close()
    events=[]
    def progress(event):
        events.append(event)
        temporary=directory/'diagnostic.partial'
        temporary.write_text(json.dumps({'events':events[-100:]}),'utf-8')
        temporary.replace(directory/'diagnostic.json')
    token=bind_sink(progress)
    try:
        output={'ok':True,'value':target(*args)}
    except Exception as exc:
        output={'ok':False,'diagnostics':{'events':events[-100:],
                'reason_code':error_reason(exc)}}
    finally:
        reset_sink(token)
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
    process=context.Process(target=_worker,args=(child,target,args,str(directory)),daemon=False)
    closer=None;started=time.monotonic()
    def failure(message,reason):
        try:
            saved=json.loads((directory/'diagnostic.json').read_text('utf-8'))
            events=[safe_event(e.get('stage'),e.get('status'),**{k:e[k] for k in
                    ('seconds','reason_code','provider','method','adjustment') if k in e}) for e in saved['events'][-100:]]
        except (OSError,ValueError,KeyError,TypeError): events=[]
        return WebDataError(message,{'reason_code':reason,'events':events,
                                    'total_backend_seconds':round(time.monotonic()-started,4)})
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
            if isinstance(output.get('web_diagnostics'),dict):
                output['web_diagnostics'].update(total_backend_seconds=elapsed,web_deadline_seconds=seconds)
        return output
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
