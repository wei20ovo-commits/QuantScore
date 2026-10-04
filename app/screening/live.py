"""Real BaoStock adapter. No scoring implementations or mock market data."""
from copy import deepcopy
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.data.cache import CacheKey, DataCache
from app.data.provider_manager import ProviderManager
from app.sector.industry_context import PrimaryIndustryService
from app.sector.providers import canonical_symbol
from app.services.stock_analysis_service import StockAnalysisService
from .service import RequestCache, SharedIndustryContext


class LiveScreeningAdapter:
    mode = 'live'
    is_mock = False

    def __init__(self, provider=None, cache=None, *, history_cache=None, score_memo=None, control=None, profile=None):
        from .batch_provider import BatchBaoStockProvider
        self.provider = provider or BatchBaoStockProvider(timeout=150)
        self.cache = RequestCache(cache or DataCache())
        self.control=control
        self.history_cache=history_cache
        self.score_memo=score_memo
        from .profiling import RunProfile
        self.profile=profile or RunProfile()
        self.provider.control=control
        self.provider_requests = 0
        self.retry_count = 0
        self.request_errors = []
        self.failed_requests = set()
        self.consecutive_failures={}
        original = self.provider._call

        def counted(method, **kwargs):
            if self.control:
                self.control.check()
            signature = (method, repr(sorted(kwargs.items())))
            if self.control and self.consecutive_failures.get(signature,0)>=self.control.limits.max_attempts:
                from .runtime import RuntimeDeadline
                raise RuntimeDeadline('Request retry budget exhausted')
            if signature in self.failed_requests:
                self.retry_count += 1
            self.provider_requests += 1
            try:
                with self.profile.phase('provider_request'):
                    value = original(method, **kwargs)
                if self.control:
                    self.control.check()
                self.failed_requests.discard(signature)
                self.consecutive_failures.pop(signature,None)
                return value
            except Exception as exc:
                self.failed_requests.add(signature)
                self.consecutive_failures[signature]=self.consecutive_failures.get(signature,0)+1
                self.request_errors.append(dict(method=method, parameters={k:str(v) for k,v in kwargs.items()}, error=str(exc)))
                raise
        self.provider._call = counted
        self.profile.wrap(self.provider,'fetch_stock_daily','stock_history_fetch')
        self.profile.wrap(self.provider,'fetch_benchmark','benchmark_fetch')
        self.profile.wrap(self.provider,'query_trade_dates','calendar_fetch')

    def begin_run(self):
        """Run memo lifetime ends here, even when an adapter is reused."""
        self.cache=RequestCache(self.cache.cache)
        self.provider_requests=self.retry_count=0
        self.request_errors.clear();self.failed_requests.clear();self.consecutive_failures.clear()
        with self.profile.lock:
            self.profile.counts.clear();self.profile.seconds.clear()
        if self.history_cache:
            self.history_cache.memory.clear()
            self.history_cache.control=self.control
        if self.score_memo:
            self.score_memo.hits=self.score_memo.misses=0

    def _fetch(self, key, call, refresh):
        value = self.cache.get(key, force_refresh=refresh)
        if value is not None:
            return value
        for attempt in range(3):
            try:
                value = call()
                if value.empty:
                    raise ValueError('EMPTY_PROVIDER_RESPONSE')
                return self.cache.put(key, value)
            except Exception:
                if self.control:
                    self.control.check()
                    if attempt<2:
                        self.control.wait(self.control.limits.backoff_seconds)
                if attempt == 2:
                    raise

    def prepare(self, *, refresh=False):
        if self.history_cache:
            self.history_cache.bind(self.provider,refresh=refresh)
        p = self.provider
        now = pd.Timestamp.now(tz='Asia/Shanghai')
        cutoff = now.normalize().tz_localize(None)
        if now.hour < 16:
            cutoff -= pd.Timedelta(days=1)
        calendar = self._fetch(CacheKey('baostock','screen_calendar',str((cutoff-pd.Timedelta(days=21)).date()),str(cutoff.date()),'calendar'),
                               lambda:p.query_trade_dates(cutoff-pd.Timedelta(days=21),cutoff), refresh)
        day = str(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date']).max().date())
        self.cache.frames[CacheKey('baostock','calendar',str(cutoff.date()),str(cutoff.date()),'industry_context:recent_calendar').encode()]=calendar.copy(deep=True)
        membership = self._fetch(CacheKey('baostock','SH_SZ',day,day,'industry_context:membership'),
                                 lambda:p._call('query_stock_industry'), refresh).copy()
        basic = self._fetch(CacheKey('baostock','all',day,day,'industry_context:metadata'), p.query_stock_basic, refresh)
        membership['symbol'] = membership.code.map(canonical_symbol)
        # Verify metadata for members missing from the all-security response.
        codes = set(basic.code)
        for code in sorted(set(membership.loc[membership.symbol.str.endswith(('.SH','.SZ')),'code'])-codes):
            try:
                frame = self._fetch(CacheKey('baostock',code,day,day,'screen_metadata'), lambda code=code:p.query_stock_basic(code), refresh)
                basic = pd.concat([basic, frame], ignore_index=True)
            except Exception:
                pass  # Included in exclusions below, never silently counted as a stock.
        basic = basic.drop_duplicates('code',keep='last')
        meta = basic.set_index('code')
        exclusions = []
        rows = []
        for row in membership.to_dict('records'):
            symbol = row['symbol']
            reason = None
            if not symbol.endswith(('.SH','.SZ')):
                reason = 'OUT_OF_SCOPE_FOR_V1'
            elif row['code'] not in meta.index:
                reason = 'METADATA_UNAVAILABLE'
            elif str(meta.loc[row['code'],'type']) != '1':
                reason = 'NON_STOCK_ASSET_TYPE'
            elif not row.get('industry'):
                reason = 'NO_PRIMARY_INDUSTRY'
            if reason:
                exclusions.append(dict(symbol=symbol, reason=reason))
                if reason == 'METADATA_UNAVAILABLE':
                    rows.append(row)  # Preserve the expected membership denominator.
            else:
                rows.append(row)
        accepted = pd.DataFrame(rows)
        if accepted.empty:
            raise ValueError('EMPTY_STOCK_INDUSTRY_UNIVERSE')
        ambiguous = accepted.groupby('symbol').industry.nunique()
        bad = set(ambiguous[ambiguous.gt(1)].index)
        exclusions.extend(dict(symbol=s,reason='MULTIPLE_PRIMARY_INDUSTRIES') for s in sorted(bad))
        blockers = {name[:3]:'DATA_INCONSISTENT' for name in accepted.loc[accepted.symbol.isin(bad),'industry']}
        unknown_metadata = accepted.loc[~accepted.code.isin(meta.index)]
        blockers.update({name[:3]:'DATA_ERROR' for name in unknown_metadata.industry})
        accepted = accepted.drop_duplicates(['symbol','industry'])
        # The existing industry service consumes this validated membership from
        # request memory; persistent raw membership evidence remains unchanged.
        key = CacheKey('baostock','SH_SZ',day,day,'industry_context:membership')
        self.cache.frames[key.encode()] = accepted.copy(deep=True)
        self.cache.frames[CacheKey('baostock','all',day,day,'industry_context:metadata').encode()] = basic.copy(deep=True)
        # Resolver asks for canonical symbols. Reuse the validated basic table
        # already fetched for this run, preserving its actual source timestamp.
        lookup_day=str(now.date())
        for i,row in enumerate(basic.to_dict('records')):
            code=row['code']
            if code.startswith(('sh.','sz.')):
                canonical=canonical_symbol(code)
                frame=basic.iloc[[i]].copy(deep=True)
                self.cache.frames[CacheKey('baostock',canonical,lookup_day,lookup_day,'verified_security').encode()]=frame
        universe = {name[:3]:dict(name=name,symbols=sorted(group.symbol.tolist()),quality_blocker=blockers.get(name[:3]))
                    for name,group in accepted.groupby('industry')}
        mapping = {row['symbol']:row['industry'][:3] for row in accepted.to_dict('records') if row['symbol'] not in bad}
        if len(universe) != accepted.industry.nunique():
            raise ValueError('SECTOR_ID_COLLISION')
        industry = PrimaryIndustryService(cache=self.cache,provider=p)
        self.shared = SharedIndustryContext(industry,mapping)
        manager = ProviderManager(providers=[p],cache=self.cache)
        self.analysis_service = ScreeningStockAnalysisService(manager,industry_service=self.shared)
        self.profile.wrap(self.analysis_service,'_load','stock_data_fetch')
        self.profile.wrap(self.analysis_service.score_engine,'evaluate','QuantScore')
        if self.score_memo:
            self.score_memo.bind(self.analysis_service.score_engine,self.profile)
        self._fetch(CacheKey('baostock','000001.SH','2000-01-01',day,'NONE'),
                    lambda:p.fetch_benchmark('2000-01-01',day),refresh)
        return day, universe, exclusions

    def sector(self, sector_id, representative, day, *, refresh=False):
        with self.profile.phase('sector_data_and_scoring'):
            return self.shared.build(representative,day,refresh=refresh)

    def stock(self, symbol, day, *, refresh=False):
        with self.profile.phase('stock_data_and_scoring'):
            return self.analysis_service.analyze(symbol,as_of=day,refresh=refresh).to_dict()

    def metrics(self):
        return dict(provider_requests=self.provider_requests,cache_hits=self.cache.hits,
                    cache_misses=self.cache.misses,retry_count=self.retry_count,
                    industry_heat_evaluations=getattr(getattr(self,'shared',None),'evaluations',0),
                    worker_starts=getattr(self.provider,'worker_starts',None),
                    profiling=self.profile.to_dict(),
                    history_cache=dict(self.history_cache.metrics) if self.history_cache else None,
                    score_memo=dict(hits=self.score_memo.hits,misses=self.score_memo.misses) if self.score_memo else None,
                    timeout_count=getattr(self.provider,'timeout_count',0),
                    retry_timeout_wait_seconds=getattr(self.provider,'wait_seconds',0),
                    provider_request_errors=deepcopy(self.request_errors))

    def close(self):
        close = getattr(self.provider,'close',None)
        if close:
            close()


class ScreeningStockAnalysisService(StockAnalysisService):
    """Gate the existing full scoring service before evaluation of short history."""
    def _load(self, symbol, as_of=None, refresh=False):
        loaded, status = super()._load(symbol,as_of,refresh)
        from .policy import ScreeningPolicy
        if loaded is not None and status.rows < ScreeningPolicy.current().history_min:
            status.warnings.append('SCREENING_HISTORY_INCOMPLETE')
            return None, status
        return loaded, status
