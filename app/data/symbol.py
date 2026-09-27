import re
import pandas as pd
from app.data.models import BENCHMARK_NAME, BENCHMARK_SYMBOL, DataError, Security


class SymbolResolver:
    def __init__(self, securities=None, provider=None):
        self.securities = securities
        self.provider = provider

    def resolve(self, value):
        text = str(value).strip().upper()
        if text in ('BENCHMARK', 'SSE_COMPOSITE', BENCHMARK_SYMBOL, 'SH000001'):
            return Security(BENCHMARK_SYMBOL, BENCHMARK_NAME, 'INDEX')
        prefix = re.fullmatch(r'(SH|SZ|BJ)(\d{6})', text)
        if prefix:
            text = f'{prefix[2]}.{prefix[1]}'
        if not re.fullmatch(r'\d{6}(\.(SH|SZ|BJ))?', text):
            raise DataError('证券代码格式无效')
        if self.securities is None:
            if self.provider is None:
                raise DataError('缺少真实证券列表，不能猜测交易所')
            self.securities = self.provider.list_securities()
        table = self.securities
        if not isinstance(table, pd.DataFrame):
            table = pd.DataFrame(table)
        if 'canonical_symbol' not in table:
            raise DataError('证券列表缺少 canonical_symbol')
        symbols = table.canonical_symbol.astype(str)
        matches = table.loc[symbols.eq(text) if '.' in text else symbols.str.split('.').str[0].eq(text)]
        if 'asset_type' in matches:
            matches = matches.loc[matches.asset_type.eq('STOCK')]
        if len(matches) != 1:
            raise DataError('证券未找到或存在歧义，需指定交易所')
        row = matches.iloc[0]
        canonical = str(row.canonical_symbol)
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', canonical):
            raise DataError('证券列表中的 canonical_symbol 无效')
        def optional(key):
            v = row.get(key)
            return None if v is None or pd.isna(v) else str(v)
        return Security(canonical, optional('name') or '', 'STOCK', optional('board'), optional('listing_date'))
