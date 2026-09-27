import pandas as pd
from app.data.base import BaseProvider, bounded_ak_call
from app.data.models import BENCHMARK_SYMBOL, DataError, ProviderError
from app.data.validators import DataValidator


class AKShareProvider(BaseProvider):
    name = 'akshare'

    def __init__(self, client=None, timeout=20):
        self.client, self.timeout = client, timeout

    def _call(self, method, **kwargs):
        if self.client is not None:
            try:
                return getattr(self.client, method)(**kwargs)
            except Exception as exc:
                raise ProviderError(f'AKShare {method} 失败：{type(exc).__name__}') from exc
        return bounded_ak_call(method, kwargs, self.timeout)

    def list_securities(self):
        rows = []
        for exchange, method, kwargs, code, name, board in (
            ('SH', 'stock_info_sh_name_code', {'symbol': '主板A股'}, '证券代码', '证券简称', 'MAIN'),
            ('SH', 'stock_info_sh_name_code', {'symbol': '科创板'}, '证券代码', '证券简称', 'STAR'),
            ('SZ', 'stock_info_sz_name_code', {'symbol': 'A股列表'}, 'A股代码', 'A股简称', None),
        ):
            table = self._call(method, **kwargs)
            if not {code, name} <= set(table):
                raise DataError(f'{method} 证券列表字段变化')
            for record in table.to_dict('records'):
                value = str(record[code]).split('.')[0].zfill(6)
                rows.append({'canonical_symbol': f'{value}.{exchange}', 'name': record[name],
                             'asset_type': 'STOCK', 'board': board or record.get('板块'),
                             'listing_date': record.get('上市日期', record.get('A股上市日期'))})
        return pd.DataFrame(rows)

    def fetch_stock_daily(self, symbol, start_date, end_date, adjustment='raw'):
        if symbol == BENCHMARK_SYMBOL or not symbol.endswith(('.SH', '.SZ')):
            raise DataError('该接口只接受已解析的沪深股票，不接受指数')
        if adjustment not in ('raw', 'qfq'):
            raise DataError('仅支持 raw/qfq')
        data = self._call('stock_zh_a_hist', symbol=symbol.split('.')[0], period='daily',
                          start_date=pd.Timestamp(start_date).strftime('%Y%m%d'),
                          end_date=pd.Timestamp(end_date).strftime('%Y%m%d'),
                          adjust='' if adjustment == 'raw' else 'qfq', timeout=self.timeout)
        rename = {'日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close',
                  '成交量': 'volume', '成交额': 'amount', '换手率': 'turnover_rate'}
        data = data.rename(columns=rename)
        if not {'date','open','high','low','close'} <= set(data):
            raise DataError('AKShare 股票行情为空或返回核心价格字段变化')
        for optional in ('volume','amount','turnover_rate'):
            if optional not in data:
                data[optional] = float('nan')
        data = data[list(rename.values())].copy()
        # 源成交量为手，标准股票成交量为股；换手率保持百分点。
        data['volume'] = pd.to_numeric(data.volume, errors='raise') * 100
        return DataValidator.validate(data, suffixes=('',))

    def fetch_benchmark(self, start_date, end_date):
        # 1.18.97 此接口无 timeout 参数，由 _call 的进程截止控制。
        data = self._call('stock_zh_index_daily_em', symbol='sh000001',
                          start_date=pd.Timestamp(start_date).strftime('%Y%m%d'),
                          end_date=pd.Timestamp(end_date).strftime('%Y%m%d'))
        data = DataValidator.validate(data, suffixes=('',))
        return data.loc[data.date.between(pd.Timestamp(start_date), pd.Timestamp(end_date))].reset_index(drop=True)
