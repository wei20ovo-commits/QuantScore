import pandas as pd
from app.data.models import BENCHMARK_NAME, BENCHMARK_SYMBOL, DataError
from app.features.technical import FeatureBuilder, build_features
from app.features.resample import build_period_bars
from app.rules.base import Context


def build_context(data, as_of=None, feature_builder=None):
    if data.metadata.get('benchmark_symbol', BENCHMARK_SYMBOL) != BENCHMARK_SYMBOL:
        raise DataError('大盘基准必须为 000001.SH')
    prepared = Context(data.bars, data.benchmark, dict(data.metadata), as_of).prepared()
    builder = feature_builder if feature_builder is not None else FeatureBuilder()
    bars = builder.build(prepared.bars, as_of)
    benchmark = None if prepared.benchmark is None else builder.build(prepared.benchmark, as_of)
    metadata = dict(prepared.metadata)
    metadata.update(benchmark_symbol=BENCHMARK_SYMBOL, benchmark_name=BENCHMARK_NAME,
                    period_bars=build_period_bars(bars, as_of), data_warnings=list(data.warnings))
    return Context(bars, benchmark, metadata, as_of)


def market_context(benchmark, as_of=None):
    result = {'symbol': BENCHMARK_SYMBOL, 'name': BENCHMARK_NAME, 'status': 'UNKNOWN'}
    if benchmark is None or benchmark.empty:
        return result
    d = build_features(benchmark, as_of)
    if d.empty:
        return result
    latest = d.iloc[-1]
    result.update(status='AVAILABLE', date=str(latest.date.date()))
    for key in ('close_adj', 'M20', 'M60', 'return_5d', 'M60_slope_10'):
        value = latest.get(key)
        result[key] = None if value is None or pd.isna(value) else float(value)
    return result
