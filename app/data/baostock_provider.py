"""BaoStock 0.9.4; flags and fields verified against SDK and live responses."""
from contextlib import redirect_stdout
from io import StringIO
import multiprocessing as mp
import re
import socket
import pandas as pd
from app.data.base import BaseProvider
from app.data.models import DataError, ProviderError, BENCHMARK_SYMBOL
from app.data.validators import DataValidator


def query_session(client, method, kwargs):
    # SDK prints login messages: never contaminate CLI JSON.
    with redirect_stdout(StringIO()):
        try:
            login = client.login()
            if login.error_code != '0':
                raise ProviderError(f'BaoStock login error {login.error_code}')
            result = getattr(client, method)(**kwargs)
            rows = []
            while result.error_code == '0' and result.next():
                rows.append(result.get_row_data())
            if result.error_code != '0':
                raise ProviderError(f'BaoStock {method} error {result.error_code}')
            return pd.DataFrame(rows, columns=result.fields)
        finally:
            client.logout()


def _worker(pipe, method, kwargs, timeout):
    try:
        import baostock
        socket.setdefaulttimeout(timeout)
        data = query_session(baostock, method, kwargs)
        pipe.send((True, data))
    except Exception as exc:
        pipe.send((False, str(exc) if isinstance(exc, ProviderError) else type(exc).__name__))
    finally:
        pipe.close()


class BaoStockProvider(BaseProvider):
    name = 'baostock'

    def __init__(self, client=None, timeout=40):
        self.client, self.timeout = client, timeout

    def _call(self, method, **kwargs):
        if self.client is not None:
            return query_session(self.client, method, kwargs)
        context = mp.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(sender, method, kwargs, min(12, self.timeout)), daemon=True)
        process.start()
        sender.close()
        try:
            if not receiver.poll(self.timeout):
                raise ProviderError(f'BaoStock {method} deadline exceeded')
            ok, value = receiver.recv()
            if not ok:
                raise ProviderError(value)
            return value
        except EOFError as exc:
            raise ProviderError('BaoStock worker unavailable') from exc
        finally:
            receiver.close()
            process.join(.2)
            if process.is_alive():
                process.terminate()
                process.join()

    @staticmethod
    def source_code(symbol):
        if not re.fullmatch(r'\d{6}\.(SH|SZ)', symbol):
            raise DataError('BaoStock requires canonical SH/SZ symbol')
        code, exchange = symbol.split('.')
        return exchange.lower() + '.' + code

    def list_securities(self):
        data = self.query_stock_basic()
        required = {'code', 'code_name', 'ipoDate', 'type'}
        if not required <= set(data):
            raise DataError('BaoStock security fields missing')
        data = data.loc[data.type.eq('1') & data.code.str.match(r'^(sh|sz)\.\d{6}$')].copy()
        data['canonical_symbol'] = data.code.str[3:] + '.' + data.code.str[:2].str.upper()
        return data.rename(columns={'code_name':'name', 'ipoDate':'listing_date'}).assign(asset_type='STOCK')

    def query_stock_basic(self, code=None):
        """查询证券基础资料；code 为空时返回全量证券表。"""
        kwargs = {} if code is None else {'code': self.source_code(code) if re.fullmatch(r'\d{6}\.(SH|SZ)', str(code)) else code}
        data = self._call('query_stock_basic', **kwargs)
        required = {'code', 'code_name', 'ipoDate', 'type'}
        if not required <= set(data):
            raise DataError('BaoStock security fields missing')
        return data

    def query_trade_dates(self, start_date=None, end_date=None, exchange=''):
        """查询交易日历，返回 BaoStock 原始字段并规范日期类型。"""
        kwargs = {}
        if start_date is not None:
            kwargs['start_date'] = pd.Timestamp(start_date).strftime('%Y-%m-%d')
        if end_date is not None:
            kwargs['end_date'] = pd.Timestamp(end_date).strftime('%Y-%m-%d')
        if exchange:
            kwargs['exchange'] = exchange
        data = self._call('query_trade_dates', **kwargs)
        if 'calendar_date' not in data or 'is_trading_day' not in data:
            raise DataError('BaoStock trade calendar fields missing')
        data['calendar_date'] = pd.to_datetime(data['calendar_date'], errors='raise')
        data['is_trading_day'] = pd.to_numeric(data['is_trading_day'], errors='raise').astype('int64')
        return data.sort_values('calendar_date').reset_index(drop=True)

    def _history(self, symbol, start, end, adjustment, index=False):
        fields = 'date,code,open,high,low,close,preclose,pctChg,volume,amount,adjustflag'
        if not index:
            fields += ',turn,tradestatus,isST'
        flag = {'raw':'3', 'qfq':'2'}[adjustment]
        code = self.source_code(symbol)
        data = self._call('query_history_k_data_plus', code=code, fields=fields,
                          start_date=pd.Timestamp(start).strftime('%Y-%m-%d'),
                          end_date=pd.Timestamp(end).strftime('%Y-%m-%d'), frequency='d', adjustflag=flag)
        if not set(fields.split(',')) <= set(data):
            raise DataError('BaoStock history fields missing')
        if not data.code.eq(code).all() or not data.adjustflag.eq(flag).all():
            raise DataError('BaoStock returned unexpected symbol/adjustment')
        data = data.rename(columns={'turn':'turnover_rate'}).replace('', float('nan'))
        for col in ('open','high','low','close','preclose','pctChg','volume','amount','turnover_rate','tradestatus','isST'):
            if col in data:
                data[col] = pd.to_numeric(data[col], errors='raise')
        # Blank optional values remain missing; volume already shares, turn already %.
        data['provider'] = self.name
        data['symbol'] = symbol
        data['exchange'] = symbol[-2:]
        data['data_provenance'] = f'baostock:query_history_k_data_plus:{code}:adjustflag={flag}'
        return DataValidator.validate(data, suffixes=('',))

    def fetch_stock_daily(self, symbol, start_date, end_date, adjustment='raw'):
        if symbol == BENCHMARK_SYMBOL or adjustment not in ('raw','qfq'):
            raise DataError('Invalid BaoStock stock/adjustment')
        return self._history(symbol, start_date, end_date, adjustment)

    def fetch_benchmark(self, start_date, end_date):
        # Live query_stock_basic(sh.000001) verified type=2, 上证综合指数.
        return self._history(BENCHMARK_SYMBOL, start_date, end_date, 'raw', index=True)
