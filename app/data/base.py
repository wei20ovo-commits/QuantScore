"""Provider 返回升序日线；价格列使用 open/high/low/close。"""
from abc import ABC, abstractmethod
from copy import deepcopy
import multiprocessing as mp
import pandas as pd
from app.data.models import ProviderError


def _ak_worker(connection, method, kwargs):
    try:
        import akshare
        from app.data.proxy import call_with_proxy_fallback
        frame, network = call_with_proxy_fallback(lambda: getattr(akshare, method)(**kwargs))
        frame.attrs.update(network)
        connection.send((True, frame))
    except Exception as exc:
        connection.send((False, {'error': str(exc) if isinstance(exc,ProviderError) else type(exc).__name__,
                                 'retryable':getattr(exc,'retryable',True)}))
    finally:
        connection.close()


def bounded_ak_call(method, kwargs, timeout):
    # AKShare 部分接口没有 timeout；独立子进程提供硬截止，不修改全局 requests。
    context = mp.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_ak_worker, args=(sender, method, kwargs), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            error = ProviderError(f'AKShare {method} 请求超时（包含可能的代理回退，总截止已到）')
            error.retryable = False
            raise error
        ok, value = receiver.recv()
        if not ok:
            error = ProviderError(f'AKShare {method} 失败：{value["error"]}')
            error.retryable = value['retryable']
            raise error
        return value
    except EOFError as exc:
        raise ProviderError(f'AKShare {method} 子进程异常') from exc
    finally:
        receiver.close()
        process.join(timeout=0.2)
        if process.is_alive():
            process.terminate()
            process.join()


class BaseProvider(ABC):
    name = 'base'
    is_mock = False

    @abstractmethod
    def list_securities(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_stock_daily(self, symbol, start_date, end_date, adjustment='raw'):
        raise NotImplementedError

    @abstractmethod
    def fetch_benchmark(self, start_date, end_date):
        raise NotImplementedError

    def fetch_limits(self, symbol, start_date, end_date):
        return pd.DataFrame(columns=['date', 'limit_up_price', 'limit_down_price'])

    def fetch_daily_basic(self, symbol, start_date, end_date):
        return pd.DataFrame(columns=['date', 'turnover_rate'])


class MockProvider(BaseProvider):
    """仅使用调用方提供的数据，不生成或冒充真实行情。"""
    name = 'mock'
    is_mock = True

    def __init__(self, securities, raw, qfq, benchmark=None, limits=None):
        self.securities = deepcopy(securities)
        self.raw, self.qfq = deepcopy(raw), deepcopy(qfq)
        self.benchmark, self.limits = deepcopy(benchmark), deepcopy(limits)
        self.calls = []

    def list_securities(self):
        self.calls.append(('securities',))
        return pd.DataFrame(self.securities).copy()

    def _slice(self, frame, start, end):
        if frame is None:
            raise ProviderError('mock 未提供该数据')
        dates = pd.to_datetime(frame.date)
        return frame.loc[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))].copy()

    def fetch_stock_daily(self, symbol, start_date, end_date, adjustment='raw'):
        self.calls.append(('stock', symbol, adjustment))
        data = self.raw if adjustment == 'raw' else self.qfq
        if isinstance(data, dict):
            data = data.get(symbol)
        return self._slice(data, start_date, end_date)

    def fetch_benchmark(self, start_date, end_date):
        self.calls.append(('benchmark', '000001.SH'))
        return self._slice(self.benchmark, start_date, end_date)

    def fetch_limits(self, symbol, start_date, end_date):
        if self.limits is None:
            return super().fetch_limits(symbol, start_date, end_date)
        return self._slice(self.limits, start_date, end_date)
