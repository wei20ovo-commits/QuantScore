from datetime import datetime, timezone
import pandas as pd
from pathlib import Path
import yaml
from app.data.baostock_provider import BaoStockProvider
from app.data.akshare_provider import AKShareProvider
from app.data.cache import CacheKey, DataCache
from app.data.market_rule import MarketLimitResolver
from app.data.models import BENCHMARK_SYMBOL, MarketData, DataError, ProviderError, Security
from app.data.symbol import SymbolResolver
from app.data.tushare_provider import TushareProvider
from app.data.validators import DataValidator


class ProviderManager:
    benchmark_symbol = BENCHMARK_SYMBOL

    def __init__(self, provider=None, *, cache=None, resolver=None, tushare=None, retries=2, providers=None, config_path=None):
        if providers is not None and provider is not None:
            raise ValueError('Use provider or providers, not both')
        if providers is None:
            if provider is not None:
                providers = [provider]
            else:
                config = Path(config_path) if config_path else Path(__file__).resolve().parents[2]/'config/data_providers.yaml'
                order = yaml.safe_load(config.read_text('utf-8'))['provider_order']
                factories = {'baostock':BaoStockProvider, 'akshare':AKShareProvider, 'tushare':TushareProvider}
                if not order or len(set(order)) != len(order) or any(x not in factories for x in order):
                    raise ValueError('Invalid provider_order')
                providers = [factories[name]() for name in order]
        self.providers = [p for p in providers if getattr(p, 'enabled', True)]
        if not self.providers:
            raise ValueError('No enabled providers')
        self.supports_security_lookup = any(isinstance(p, BaoStockProvider) for p in self.providers)
        self.provider = self.providers[0]
        self.cache = cache if cache is not None else DataCache()
        self.resolver = resolver or SymbolResolver(provider=self)
        self.tushare = tushare
        if tushare is None and not self.provider.is_mock:
            self.tushare = TushareProvider()
        self.retries = min(3, max(1, retries))
        self.limit_resolver = MarketLimitResolver()

    def lookup_securities(self, text):
        """Verify both exchange candidates remotely; never infer an exchange."""
        source = next((p for p in self.providers if isinstance(p, BaoStockProvider)), None)
        if source is None:
            return self.list_securities()
        day = str(pd.Timestamp.now(tz='Asia/Shanghai').date())
        codes = [text] if '.' in text else [text+'.SH', text+'.SZ']
        frames = []
        for code in codes:
            key = CacheKey(source.name, code, day, day, 'verified_security')
            data = self.cache.get(key)
            if data is None:
                for attempt in range(self.retries):
                    try:
                        data = source.query_stock_basic(code)
                        self.cache.put(key, data)
                        break
                    except Exception:
                        if attempt + 1 == self.retries:
                            return self.list_securities()  # Preserve the existing provider fallback chain.
            frames.append(data)
        data = pd.concat(frames, ignore_index=True)
        data = data.loc[data.type.eq('1') & data.code.isin([source.source_code(c) for c in codes])].copy()
        data['canonical_symbol'] = data.code.str[3:] + '.' + data.code.str[:2].str.upper()
        return data.rename(columns={'code_name':'name', 'ipoDate':'listing_date'}).assign(asset_type='STOCK')

    def list_securities(self):
        failures = []
        day = str(pd.Timestamp.now(tz='Asia/Shanghai').date())
        for provider in self.providers:
            key = CacheKey(provider.name, 'SH_SZ', day, day, 'validated_securities')
            cached = None if provider.is_mock else self.cache.get(key)
            if cached is not None and not cached.empty and 'canonical_symbol' in cached:
                return cached
            for attempt in range(self.retries):
                try:
                    data = provider.list_securities()
                    if data is None or data.empty or 'canonical_symbol' not in data:
                        raise DataError('Invalid security list')
                    return data if provider.is_mock else self.cache.put(key, data)
                except Exception as exc:
                    if attempt + 1 == self.retries:
                        failures.append(f'{provider.name}: {type(exc).__name__}')
        raise ProviderError('Security lists unavailable: ' + '; '.join(failures))

    def fetch(self, symbol, *args, **kwargs):
        symbol = symbol if isinstance(symbol, Security) else self.resolver.resolve(symbol)
        failures = []
        for provider in self.providers:
            try:
                data = self._fetch_from_provider(symbol, *args, provider=provider, **kwargs)
                data.metadata['provider_attempts'] = failures + [{'provider':provider.name, 'status':'SUCCESS'}]
                data.warnings[:0] = [f"PROVIDER_FALLBACK: {f['provider']} {f['error']}" for f in failures]
                return data
            except Exception as exc:
                if len(self.providers) == 1:
                    raise
                failures.append({'provider':provider.name, 'status':'FAILED',
                                 'error':str(exc) if isinstance(exc,(ProviderError,DataError)) else type(exc).__name__})
        raise ProviderError('All providers unavailable: ' + '; '.join(f"{f['provider']}: {f['error']}" for f in failures))

    def _fetch(self, provider, symbol, start, end, adjustment, call, refresh):
        key = CacheKey(provider.name, symbol, str(start), str(end), adjustment)
        cached = self.cache.get(key, force_refresh=refresh)
        if cached is not None:
            return cached
        for attempt in range(self.retries):
            try:
                frame = call()
                frame = DataValidator.dates(frame, allow_empty=adjustment in ('limits', 'basic'))
                return self.cache.put(key, frame)
            except DataError:
                raise
            except Exception as exc:
                if attempt + 1 == self.retries or not getattr(exc, 'retryable', True):
                    detail = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                    raise ProviderError(f'{provider.name} {adjustment} 获取失败（{attempt+1}轮）：{detail}') from exc

    def _fetch_from_provider(self, symbol, start_date='2000-01-01', end_date=None, *, as_of=None, refresh=False, force_refresh=False, provider=None):
        refresh = refresh or force_refresh
        security = symbol if isinstance(symbol, Security) else self.resolver.resolve(symbol)
        now = pd.Timestamp.now(tz='Asia/Shanghai')
        # 保守地只允许已经收盘的日期；盘中不能把当天日线当成完成日线。
        latest = now.normalize().tz_localize(None)
        if now.hour < 16:
            latest -= pd.Timedelta(days=1)
        end = min(pd.Timestamp(end_date or as_of or latest).normalize(), latest)
        if as_of is not None:
            end = min(end, pd.Timestamp(as_of).normalize())
        start = pd.Timestamp(start_date).normalize()
        if start > end:
            raise DataError('开始日期晚于结束日期')
        provider = provider or self.provider
        warnings = []
        provenance = []
        def fetch_part(kind, callback, source=provider, code=security.symbol):
            frame = self._fetch(source, code, start, end, kind, callback, refresh)
            provenance.append({'provider': source.name, 'symbol': code, 'adjustment_type': kind,
                               'last_updated': frame.attrs.get('last_updated'), 'cache_hit': frame.attrs.get('cache_hit', False)})
            return frame
        def index_bars():
            errors = []
            for source in [provider, *[p for p in self.providers if p is not provider]]:
                try:
                    frame = fetch_part('NONE', lambda: source.fetch_benchmark(start, end), source=source, code=BENCHMARK_SYMBOL)
                    frame = DataValidator.validate(frame, suffixes=('',))
                    frame = frame.loc[frame.date.between(start, end)].reset_index(drop=True)
                    return DataValidator.align_raw_qfq(frame, frame)
                except Exception as exc:
                    errors.append(f'{source.name}: {type(exc).__name__}')
            raise ProviderError('Benchmark unavailable: ' + '; '.join(errors))
        if security.asset_type == 'INDEX':
            bars = index_bars()
            benchmark = bars.copy()
            raw_rows = adjusted_rows = len(bars)
        else:
            raw = fetch_part('raw', lambda: provider.fetch_stock_daily(security.symbol, start, end, 'raw'))
            qfq = fetch_part('qfq', lambda: provider.fetch_stock_daily(security.symbol, start, end, 'qfq'))
            # 先限定评价窗口，再做严格一对一日期校验；不接受按位置拼接。
            raw = raw.loc[raw.date.between(start, end)].reset_index(drop=True)
            qfq = qfq.loc[qfq.date.between(start, end)].reset_index(drop=True)
            bars = DataValidator.align_raw_qfq(raw, qfq)
            raw_rows, adjusted_rows = len(raw), len(qfq)
            try:
                benchmark = DataValidator.benchmark_coverage(bars, index_bars())
            except (ProviderError, DataError) as exc:
                benchmark = None
                warnings.append(f'BENCHMARK_UNAVAILABLE: {exc}')
            limit_provider = self.tushare if self.tushare is not None and self.tushare.enabled else provider
            reported = None
            try:
                reported = fetch_part('limits', lambda: limit_provider.fetch_limits(security.symbol, start, end), source=limit_provider)
            except (ProviderError, DataError) as exc:
                warnings.append(f'LIMIT_PRICE_UNRELIABLE: {exc}')
            try:
                bars = self.limit_resolver.apply(bars, reported)
            except DataError:
                bars = self.limit_resolver.apply(bars)
                warnings.append('LIMIT_PRICE_UNRELIABLE: Provider 涨跌停日期无效')
            if bars.limit_up_price.isna().any():
                warnings.append('LIMIT_PRICE_UNRELIABLE: 缺少可靠历史涨跌停价，相关规则应返回 UNKNOWN')
            if self.tushare is not None and self.tushare.enabled:
                try:
                    basic = fetch_part('basic', lambda: self.tushare.fetch_daily_basic(security.symbol, start, end), source=self.tushare)
                    if not basic.empty:
                        basic = DataValidator.dates(basic).set_index('date').turnover_rate
                        candidate = bars.copy()
                        existing = candidate.get('turnover_rate', pd.Series(float('nan'), index=candidate.index))
                        candidate['turnover_rate'] = existing.fillna(candidate.date.map(basic))
                        bars = DataValidator.validate(candidate)
                except (ProviderError, DataError) as exc:
                    warnings.append(f'TURNOVER_ENHANCEMENT_UNAVAILABLE: {exc}')
        for col in ('volume', 'amount', 'turnover_rate', 'limit_up_price', 'limit_down_price'):
            if col not in bars:
                bars[col] = float('nan')
        bars['symbol'], bars['name'], bars['exchange'] = security.symbol, security.name, security.exchange
        bars = DataValidator.validate(bars, as_of=as_of)
        metadata = {'provider': provider.name, 'is_mock': provider.is_mock,
                    'fetch_time': datetime.now(timezone.utc).isoformat(), 'data_provenance': provenance,
                    'asset_type': security.asset_type, 'adjustment_type': 'NONE' if security.asset_type == 'INDEX' else 'qfq',
                    'adjustment_consistent': True, 'benchmark_symbol': BENCHMARK_SYMBOL,
                    'benchmark_metadata': {'asset_type': 'INDEX', 'adjustment_type': 'NONE'},
                    'raw_rows': raw_rows, 'adjusted_rows': adjusted_rows,
                    'benchmark_rows': 0 if benchmark is None else len(benchmark),
                    'volume_unit': 'provider_native' if security.asset_type == 'INDEX' else 'shares',
                    'turnover_unit': 'percent_points',
                    'adjustment_point_in_time': False}
        warnings.append('前复权为获取时数据源口径，不是历史复权快照')
        return MarketData(security=security, bars=bars, benchmark=benchmark,
                          metadata=metadata, warnings=warnings)

    get_market_data = fetch
