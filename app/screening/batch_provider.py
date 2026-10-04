"""Run-scoped SDK worker reuse; each query retains fresh login/finally logout.

The inherited Provider keeps field grouping, validation, mutex, throttling and
bounded retries. Only Python worker startup is amortized across sequential calls.
"""
import multiprocessing as mp
import socket
from io import StringIO
from pathlib import Path
import tempfile
import shutil
import pandas as pd
import time
from app.data.baostock_provider import BaoStockProvider, query_session
from app.data.models import ProviderError


def batch_worker(pipe, timeout):
    import baostock
    socket.setdefaulttimeout(timeout)
    try:
        while True:
            command = pipe.recv()
            if command is None:
                return
            method, kwargs = command
            try:
                pipe.send((True, query_session(baostock, method, kwargs)))
            except Exception as exc:
                pipe.send((False, str(exc)))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        pipe.close()


def batch_file_worker(pipe, timeout, directory):
    """Keep large payloads off the pipe: poll now bounds the complete response.

The worker writes a validated SDK response atomically before sending a tiny
notification. Each request still has its own login/finally logout.
"""
    import baostock
    socket.setdefaulttimeout(timeout)
    try:
        while True:
            command = pipe.recv()
            if command is None:
                return
            method, kwargs = command
            try:
                frame = query_session(baostock,method,kwargs)
                temporary=Path(directory)/'response.tmp'
                temporary.write_text(frame.to_json(orient='table',index=False,double_precision=15),encoding='utf-8')
                temporary.replace(Path(directory)/'response.json')
                pipe.send((True,''))
            except Exception as exc:
                # Limit IPC messages; full error belongs to ordinary evidence.
                pipe.send((False,str(exc)[:1500]))
    except (EOFError,BrokenPipeError):
        pass
    finally:
        pipe.close()


class BatchBaoStockProvider(BaoStockProvider):
    def __init__(self, timeout=150):
        super().__init__(timeout=timeout)
        self._process = self._pipe = None
        self.worker_starts = 0
        self.control = None
        self._result_dir = None
        self.timeout_count = 0
        self.wait_seconds = 0

    def _start(self):
        context = mp.get_context('spawn')
        self._pipe, child = context.Pipe()
        self._result_dir = tempfile.mkdtemp(prefix='quantscore-sdk-')
        self._process = context.Process(target=batch_file_worker, args=(child, min(45,self.timeout), self._result_dir), daemon=True)
        self._process.start()
        child.close()
        self.worker_starts += 1

    def _call(self, method, **kwargs):
        if self.control is None:
            return super()._call(method,**kwargs)
        from app.data import baostock_provider as module
        self.control.check()
        start=time.monotonic()
        if not module._REQUEST_LOCK.acquire(timeout=max(0,self.control.remaining())):
            self.control.check()
            raise ProviderError('BaoStock request lock deadline exceeded')
        delay=.3
        try:
            self.control.wait(max(0,module._NEXT_REQUEST_AT-time.monotonic()))
            self.wait_seconds+=time.monotonic()-start
            return self._call_once(method,**kwargs)
        except ProviderError:
            delay=1.0
            raise
        finally:
            module._NEXT_REQUEST_AT=time.monotonic()+delay
            module._REQUEST_LOCK.release()

    def _call_once(self, method, **kwargs):
        if self._process is None or not self._process.is_alive():
            self.close()
            self._start()
        try:
            self._pipe.send((method, kwargs))
            timeout=min(self.timeout,self.control.limits.request_seconds,self.control.remaining()) if self.control else self.timeout
            if not self._pipe.poll(max(0,timeout)):
                self.timeout_count+=1
                raise ProviderError(f'BaoStock {method} deadline exceeded')
            ok, value = self._pipe.recv()
            if not ok:
                raise ProviderError(value)
            if self._result_dir:
                value=pd.read_json(StringIO((Path(self._result_dir)/'response.json').read_text('utf-8')),orient='table')
            if self.control:
                self.control.check()
            return value
        except (EOFError, BrokenPipeError, OSError) as exc:
            self.close()
            raise ProviderError(f'BaoStock batch worker unavailable: {exc}') from exc
        except ProviderError:
            # The next existing bounded retry starts a new interpreter, with no
            # failed SDK state reused. Failure never becomes a cached frame.
            self.close()
            raise

    def close(self):
        if self._pipe is not None:
            try:
                self._pipe.send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
        if self._process is not None:
            self._process.join(1)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(2)
        if self._pipe is not None:
            self._pipe.close()
        self._pipe = self._process = None
        if self._result_dir:
            target=Path(self._result_dir).resolve()
            # Only clean the single owned worker directory, never temp root.
            if target.parent==Path(tempfile.gettempdir()).resolve() and target.name.startswith('quantscore-sdk-'):
                shutil.rmtree(target,ignore_errors=True)
            self._result_dir=None
