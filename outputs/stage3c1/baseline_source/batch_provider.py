"""Run-scoped SDK worker reuse; each query retains fresh login/finally logout.

The inherited Provider keeps field grouping, validation, mutex, throttling and
bounded retries. Only Python worker startup is amortized across sequential calls.
"""
import multiprocessing as mp
import socket
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


class BatchBaoStockProvider(BaoStockProvider):
    def __init__(self, timeout=150):
        super().__init__(timeout=timeout)
        self._process = self._pipe = None
        self.worker_starts = 0

    def _start(self):
        context = mp.get_context('spawn')
        self._pipe, child = context.Pipe()
        self._process = context.Process(target=batch_worker, args=(child, min(45,self.timeout)), daemon=True)
        self._process.start()
        child.close()
        self.worker_starts += 1

    def _call_once(self, method, **kwargs):
        if self._process is None or not self._process.is_alive():
            self.close()
            self._start()
        try:
            self._pipe.send((method, kwargs))
            if not self._pipe.poll(self.timeout):
                raise ProviderError(f'BaoStock {method} deadline exceeded')
            ok, value = self._pipe.recv()
            if not ok:
                raise ProviderError(value)
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
                self._process.join()
        if self._pipe is not None:
            self._pipe.close()
        self._pipe = self._process = None