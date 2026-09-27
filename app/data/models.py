"""行情数据契约；缺失值不是零，mock 数据必须显式标注。"""
from dataclasses import dataclass, field
import re
import pandas as pd

BENCHMARK_SYMBOL = '000001.SH'
BENCHMARK_NAME = '上证指数'
OHLC = ('open', 'high', 'low', 'close')


@dataclass(frozen=True)
class Security:
    canonical_symbol: str
    name: str = ''
    asset_type: str = 'STOCK'
    board: str | None = None
    listing_date: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', self.canonical_symbol):
            raise DataError('证券必须使用 canonical_symbol')
        if self.asset_type not in ('STOCK', 'INDEX'):
            raise DataError('不支持的证券类型')
        if (self.canonical_symbol == BENCHMARK_SYMBOL) != (self.asset_type == 'INDEX'):
            raise DataError('指数身份必须与固定 benchmark 一致')

    @property
    def symbol(self):
        return self.canonical_symbol

    @property
    def exchange(self):
        return self.canonical_symbol.split('.')[1]


@dataclass
class MarketData:
    security: Security
    bars: pd.DataFrame
    benchmark: pd.DataFrame | None = None
    metadata: dict = field(default_factory=dict)
    # V1.4 固定大盘基准，仅扩展数据契约，不改变评分权重。
    benchmark_symbol: str = BENCHMARK_SYMBOL
    benchmark_name: str = BENCHMARK_NAME
    warnings: list[str] = field(default_factory=list)

    @property
    def symbol(self):
        return self.security.canonical_symbol

    def to_context(self, as_of=None):
        from app.features.market_context import build_context
        return build_context(self, as_of=as_of)


class DataError(ValueError):
    code = 'DATA_INVALID'


class ProviderError(RuntimeError):
    code = 'PROVIDER_UNAVAILABLE'
