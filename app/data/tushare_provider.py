import os
import pandas as pd
from app.data.base import BaseProvider
from app.data.models import BENCHMARK_SYMBOL, DataError, ProviderError
from app.data.validators import DataValidator


class TushareProvider(BaseProvider):
    name = 'tushare'

    def __init__(self, token=None, client=None, timeout=20):
        token = token or os.getenv('TUSHARE_TOKEN')
        self.enabled = client is not None or bool(token)
        self.client = client
        if self.enabled and self.client is None:
            try:
                import tushare
                self.client = tushare.pro_api(token, timeout=timeout)
            except (ImportError, RuntimeError, ValueError):
                self.enabled = False

    def _call(self, method, **kwargs):
        if not self.enabled:
            raise ProviderError('未配置 TUSHARE_TOKEN，可继续使用默认 Provider')
        try:
            return getattr(self.client, method)(**kwargs)
        except Exception as exc:
            # 不将 SDK 异常原文（可能包含 token）传播到 API。
            raise ProviderError(f'Tushare {method} 不可用：{type(exc).__name__}') from exc

    @staticmethod
    def _params(symbol, start, end):
        return dict(ts_code=symbol, start_date=pd.Timestamp(start).strftime('%Y%m%d'),
                    end_date=pd.Timestamp(end).strftime('%Y%m%d'))

    @staticmethod
    def _dates(data):
        if data is None or data.empty:
            raise DataError('Tushare 返回空数据')
        data = data.rename(columns={'trade_date': 'date'}).copy()
        data['date'] = pd.to_datetime(data.date, format='%Y%m%d', errors='raise')
        return DataValidator.dates(data.sort_values('date').reset_index(drop=True))

    def list_securities(self):
        d = self._call('stock_basic', exchange='', list_status='L',
                       fields='ts_code,name,market,list_date')
        return d.rename(columns={'ts_code': 'canonical_symbol', 'market': 'board', 'list_date': 'listing_date'}).assign(asset_type='STOCK')

    def fetch_stock_daily(self, symbol, start_date, end_date, adjustment='raw'):
        if symbol == BENCHMARK_SYMBOL or adjustment not in ('raw', 'qfq'):
            raise DataError('无效股票或复权类型')
        params = self._params(symbol, start_date, end_date)
        d = self._dates(self._call('daily', **params)).rename(columns={'vol': 'volume'})
        d['volume'] *= 100
        d['amount'] *= 1000
        if adjustment == 'qfq':
            factors = self._dates(self._call('adj_factor', **params))
            if not d.date.equals(factors.date):
                raise DataError('复权因子日期与日线不一致')
            factors['adj_factor'] = pd.to_numeric(factors.adj_factor, errors='raise')
            if factors.adj_factor.isna().any() or not factors.adj_factor.between(0, float('inf'), inclusive='neither').all():
                raise DataError('复权因子无效')
            joined = d.merge(factors[['date', 'adj_factor']], on='date', validate='one_to_one')
            for col in ('open', 'high', 'low', 'close'):
                joined[col] *= joined.adj_factor / joined.adj_factor.iloc[-1]
            d = joined.drop(columns='adj_factor')
        return DataValidator.validate(d, suffixes=('',))

    def fetch_benchmark(self, start_date, end_date):
        d = self._dates(self._call('index_daily', **self._params(BENCHMARK_SYMBOL, start_date, end_date)))
        d = d.rename(columns={'vol': 'volume'})
        d['amount'] *= 1000
        return DataValidator.validate(d, suffixes=('',))

    def fetch_limits(self, symbol, start_date, end_date):
        d = self._call('stk_limit', **self._params(symbol, start_date, end_date))
        if d is None or d.empty:
            return super().fetch_limits(symbol, start_date, end_date)
        return self._dates(d).rename(columns={'up_limit': 'limit_up_price', 'down_limit': 'limit_down_price'})[
            ['date', 'limit_up_price', 'limit_down_price']]

    def fetch_daily_basic(self, symbol, start_date, end_date):
        d = self._call('daily_basic', **self._params(symbol, start_date, end_date), fields='trade_date,turnover_rate')
        if d is None or d.empty:
            return super().fetch_daily_basic(symbol, start_date, end_date)
        return self._dates(d)[['date', 'turnover_rate']]
