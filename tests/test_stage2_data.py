"""仅使用人工夹具和 mock，不将离线结果标为真实行情通过。"""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from app.data.base import MockProvider
from app.data.cache import CacheKey, DataCache
from app.data.models import DataError, ProviderError
from app.data.symbol import SymbolResolver
from app.data.validators import DataValidator
from app.data.market_rule import MarketLimitResolver
from app.data.akshare_provider import AKShareProvider
from app.data.tushare_provider import TushareProvider
from app.data.provider_manager import ProviderManager
from app.features.technical import build_features
from app.features.resample import resample_bars
from app.engine.rule_engine import RuleEngine


def feed(n=150):
    c = np.linspace(10, 12, n)
    return pd.DataFrame({'date': pd.bdate_range('2024-01-01', periods=n), 'open': c,
                         'high': c + .2, 'low': c - .2, 'close': c, 'volume': 100.,
                         'amount': 1000., 'turnover_rate': 5.})


@pytest.fixture
def provider():
    return MockProvider([{'canonical_symbol': '600519.SH', 'name': '测试沪股'},
                         {'canonical_symbol': '000001.SZ', 'name': '测试深股'}], feed(), feed(), feed())


@pytest.mark.parametrize('value,expected', [('600519', '600519.SH'), ('SH600519', '600519.SH'),
    ('600519.SH', '600519.SH'), ('000001', '000001.SZ'), ('SZ000001', '000001.SZ'),
    ('000001.SZ', '000001.SZ'), ('000001.SH', '000001.SH'), ('SSE_COMPOSITE', '000001.SH')])
def test_symbol(provider, value, expected):
    result = SymbolResolver(provider=provider).resolve(value)
    assert result.symbol == expected
    assert result.asset_type == ('INDEX' if expected == '000001.SH' else 'STOCK')


def test_no_prefix_guess():
    with pytest.raises(DataError):
        SymbolResolver([]).resolve('600519')


def test_alignment():
    raw, adj = feed(), feed()
    for col in ('open', 'high', 'low', 'close'):
        adj[col] /= 2
    merged = DataValidator.align_raw_qfq(raw, adj)
    assert (merged.close_raw == merged.close_adj * 2).all()
    assert merged.turnover_rate.iloc[-1] == 5
    with pytest.raises(DataError):
        DataValidator.align_raw_qfq(raw, adj.iloc[1:])


@pytest.mark.parametrize('kind', ['duplicate', 'order', 'ohlc', 'nan', 'negative', 'inf'])
def test_invalid(kind):
    d = feed(5)
    if kind == 'duplicate': d.loc[1, 'date'] = d.loc[0, 'date']
    if kind == 'order': d = d.iloc[::-1]
    if kind == 'ohlc': d.loc[0, 'high'] = 1
    if kind == 'nan': d.loc[0, 'close'] = np.nan
    if kind == 'negative': d.loc[0, 'volume'] = -1
    if kind == 'inf': d.loc[0, 'amount'] = np.inf
    with pytest.raises(DataError):
        DataValidator.validate(d, suffixes=('',))


def test_limits_unknown_and_reported():
    resolver = MarketLimitResolver()
    missing = resolver.resolve(previous_close=10, metadata={'board': 'MAIN', 'is_st': False})
    assert missing.limit_up_price is None and missing.limit_source == 'UNKNOWN'
    assert missing.reason_code == 'LIMIT_PRICE_UNRELIABLE'
    known = resolver.resolve(reported={'limit_up_price': 12, 'limit_down_price': 8})
    assert known.limit_source == 'PROVIDER_REPORTED'
    invalid = resolver.resolve(reported={'limit_up_price': 8, 'limit_down_price': 12})
    assert invalid.limit_up_price is None


def test_verified_rule_rounding():
    m = dict(exchange='SH', board='MAIN', listing_date='2000-01-01', status_date='2024-01-02',
             is_st=False, rule_valid_from='2024-01-01', rule_valid_to='2024-01-31',
             rule_source='测试规则证据', limit_ratio=.1, price_tick=.01, metadata_verified=True,
             rule_verified=True, special_session=False, normal_listing_period=True, reference_price_verified=True)
    result = MarketLimitResolver().resolve(date='2024-01-02', previous_close=10.05, metadata=m)
    assert result.limit_up_price == 11.06
    assert result.limit_down_price == 9.05
    m['is_st'] = None
    assert MarketLimitResolver().resolve(date='2024-01-02', previous_close=10.05, metadata=m).limit_up_price is None


def test_cache(tmp_path):
    clock = [100.]
    cache = DataCache(tmp_path / 'cache.sqlite', ttl=10, clock=lambda: clock[0])
    key = CacheKey('mock', '600519.SH', '20240101', '20240131', 'raw')
    cache.put(key, feed(5))
    assert cache.get(key).attrs['cache_hit']
    assert cache.get(key, force_refresh=True) is None
    clock[0] += 11
    assert cache.get(key) is None


def test_manager_features_cache(provider, tmp_path):
    manager = ProviderManager(provider, cache=DataCache(tmp_path / 'cache.sqlite'))
    data = manager.fetch('000001', end_date='2024-12-31')
    assert data.symbol == '000001.SZ'
    assert data.metadata['benchmark_symbol'] == '000001.SH'
    assert data.bars.limit_up_price.isna().all()
    assert data.metadata['is_mock']
    n = len(provider.calls)
    manager.fetch('000001', end_date='2024-12-31')
    assert len(provider.calls) == n
    manager.fetch('000001', end_date='2024-12-31', refresh=True)
    assert len(provider.calls) > n
    ctx = data.to_context()
    assert ctx.bars.M5.iloc[-1] == pytest.approx(data.bars.close_adj.iloc[-5:].mean())
    assert RuleEngine().evaluate('A1', ctx).status != 'UNKNOWN'
    assert RuleEngine().evaluate('F1-N', ctx).status == 'UNKNOWN'


def test_benchmark_degrades(provider, tmp_path):
    provider.benchmark = None
    manager = ProviderManager(provider, cache=DataCache(tmp_path / 'cache.sqlite'))
    data = manager.fetch('600519', end_date='2024-12-31')
    assert data.benchmark is None
    engine = RuleEngine()
    for rid in ('A1', 'A2', 'A3'):
        assert engine.evaluate(rid, data.to_context()).status == 'UNKNOWN'
    assert engine.evaluate('C1', data.to_context()).status != 'UNKNOWN'


def test_retry(provider, tmp_path):
    original = provider.fetch_stock_daily
    count = [0]
    def flaky(*args):
        count[0] += 1
        if count[0] == 1: raise ProviderError('测试网络错误')
        return original(*args)
    provider.fetch_stock_daily = flaky
    ProviderManager(provider, cache=DataCache(tmp_path / 'c.sqlite')).fetch('600519', end_date='2024-12-31')
    assert count[0] == 3


def test_features_no_future():
    d = DataValidator.align_raw_qfq(feed(), feed())
    asof = d.date.iloc[80]
    expected = build_features(d.iloc[:81], asof)
    d.loc[81:, 'close_adj'] = 10000
    actual = build_features(d, asof)
    pd.testing.assert_frame_equal(actual, expected)
    assert actual.volume_ratio_20.iloc[-1] == 1
    assert pd.isna(actual.position_120.iloc[-1])


@pytest.mark.parametrize('period', ['W', 'M'])
def test_periods(period):
    d = DataValidator.align_raw_qfq(feed(), feed())
    out = resample_bars(d, period, as_of='2024-02-14')
    assert out.is_complete_period.all()
    assert (out.date < pd.Timestamp('2024-02-14')).all()
    first = out.iloc[0]
    freq = 'W-FRI' if period == 'W' else 'M'
    group = d.loc[d.date.dt.to_period(freq) == first.date.to_period(freq)]
    assert first.open_adj == group.open_adj.iloc[0]
    assert first.close_adj == group.close_adj.iloc[-1]
    assert first.volume == group.volume.sum()
    assert first.amount == group.amount.sum()


def test_akshare_signature_and_units():
    calls = []
    rename = {'date': '日期', 'open': '开盘', 'high': '最高', 'low': '最低', 'close': '收盘',
              'volume': '成交量', 'amount': '成交额', 'turnover_rate': '换手率'}
    def hist(symbol, period, start_date, end_date, adjust, timeout):
        calls.append((symbol, adjust, timeout))
        return feed(5).rename(columns=rename)
    def index(symbol, start_date, end_date):
        assert symbol == 'sh000001'
        return feed(5)
    p = AKShareProvider(SimpleNamespace(stock_zh_a_hist=hist, stock_zh_index_daily_em=index))
    data = p.fetch_stock_daily('000001.SZ', '20240101', '20240131', 'qfq')
    assert calls == [('000001', 'qfq', 20)]
    assert data.volume.iloc[0] == 10000 and data.turnover_rate.iloc[0] == 5
    assert len(p.fetch_benchmark('20240101', '20240131')) == 5


def test_period_missing_day_not_complete():
    d = DataValidator.align_raw_qfq(feed(), feed())
    d = d.loc[d.date != pd.Timestamp('2024-01-03')]
    out = resample_bars(d, 'W', '2024-01-05')
    assert out.empty


def test_manager_asof_and_missing_date(provider, tmp_path):
    manager = ProviderManager(provider, cache=DataCache(tmp_path / 'c.sqlite'))
    data = manager.fetch('600519', as_of='2024-04-30')
    assert data.bars.date.max() == pd.Timestamp('2024-04-30')
    assert data.to_context().bars.date.max() == pd.Timestamp('2024-04-30')
    with pytest.raises(DataError):
        manager.fetch('600519', as_of='2024-04-28')


def test_tushare_optional(monkeypatch):
    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    p = TushareProvider()
    assert not p.enabled
    with pytest.raises(ProviderError):
        p.fetch_limits('600519.SH', '20240101', '20240131')


def test_tushare_factor_date_alignment():
    raw = feed(5).rename(columns={'date': 'trade_date', 'volume': 'vol'})
    raw.trade_date = raw.trade_date.dt.strftime('%Y%m%d')
    factors = pd.DataFrame({'trade_date': raw.trade_date, 'adj_factor': [1, 1, 2, 2, 2]})
    client = SimpleNamespace(daily=lambda **kw: raw.iloc[::-1].copy(), adj_factor=lambda **kw: factors.iloc[::-1].copy())
    p = TushareProvider(client=client)
    qfq = p.fetch_stock_daily('600519.SH', '20240101', '20240131', 'qfq')
    assert qfq.close.iloc[0] == raw.close.iloc[0] / 2
    assert qfq.close.iloc[-1] == raw.close.iloc[-1]
    factors.drop(index=0, inplace=True)
    with pytest.raises(DataError):
        p.fetch_stock_daily('600519.SH', '20240101', '20240131', 'qfq')
