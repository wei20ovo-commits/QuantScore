"""Thin public Web adapter: no score calculations and no synthetic data."""
import re
from pathlib import Path
from time import perf_counter
from app.data.models import DataError
from app.services.stock_analysis_service import StockAnalysisService


def normalize_stock_code(value):
    code = str(value).strip().upper()
    if not re.fullmatch(r'(?:\d{6}(?:\.(?:SH|SZ|BJ))?|(?:SH|SZ|BJ)\d{6})', code):
        raise DataError('请输入6位股票代码，例如600519或000001，也可使用600519.SH。')
    if code in ('000001.SH', 'SH000001'):
        raise DataError('当前页面只分析股票；平安银行请输入000001或000001.SZ。')
    return code


def create_web_service(root=None, cache=None):
    from app.data.cache import DataCache
    from app.data.provider_manager import ProviderManager
    from app.data.baostock_provider import BaoStockProvider
    from app.screening.batch_provider import BatchBaoStockProvider
    from app.screening.runtime import RunControl,RuntimeLimits
    from app.web_snapshots import WebContextSnapshots,SnapshotIndustryService,WebMarketCache
    root=Path(root or Path(__file__).resolve().parents[1])
    started=perf_counter()
    snapshots=WebContextSnapshots(root)
    memo=WebMarketCache(cache or DataCache(),snapshots)
    manager=ProviderManager(cache=memo)
    control=RunControl(RuntimeLimits(request_seconds=30,stock_seconds=230,run_seconds=230))
    providers=[]
    for provider in manager.providers:
        if type(provider) is BaoStockProvider:
            provider=BatchBaoStockProvider(timeout=30)
            provider.control=control
        # Benchmark must always use the date-checked publication cache. Even a
        # missing cache may never silently trigger an online benchmark request.
        from app.web_snapshots import SnapshotUnavailable
        provider.fetch_benchmark=lambda *args,**kwargs: (_ for _ in ()).throw(SnapshotUnavailable('BENCHMARK_SNAPSHOT_UNAVAILABLE'))
        providers.append(provider)
    manager.providers=providers;manager.provider=providers[0]
    service=StockAnalysisService(provider_manager=manager,industry_service=SnapshotIndustryService(snapshots))
    service.web_latency={'architecture':'same_date_snapshots_v1','phase_seconds':{'market_context_load':round(perf_counter()-started,4)},
                         'provider_requests':0,'provider_events':[],
                         'provider_request_count_scope':'BaoStock SDK queries, including retry attempts; fallback provider HTTP internals not observed',
                         'ai_call_seconds':0,'screening_snapshot_source':snapshots.screening.source}
    def wrap(obj,name,label):
        original=getattr(obj,name)
        def measured(*args,**kwargs):
            before=perf_counter();status='OK'
            try:return original(*args,**kwargs)
            except Exception as exc:
                status=type(exc).__name__
                raise
            finally:
                phases=service.web_latency['phase_seconds']
                phases[label]=round(phases.get(label,0)+perf_counter()-before,4)
                if label=='provider_request':
                    service.web_latency['provider_requests']+=1
                    service.web_latency['provider_events'].append(dict(provider=obj.name,
                        method=args[0] if args else None,code=kwargs.get('code'),
                        adjustflag=kwargs.get('adjustflag'),status=status,seconds=round(perf_counter()-before,4)))
        setattr(obj,name,measured)
    for provider in providers:
        wrap(provider,'fetch_stock_daily','stock_raw_qfq_fetch')
        if hasattr(provider,'_call'): wrap(provider,'_call','provider_request')
    if service.industry_service is not None:
        wrap(service.industry_service,'build','industry_context_load')
    wrap(service.score_engine,'evaluate','rule_scoring')
    original=service.rule_engine.evaluate
    def evaluate(rule_id,context):
        before=perf_counter()
        try:return original(rule_id,context)
        finally:
            if rule_id in ('B1','B2'):
                phases=service.web_latency['phase_seconds']
                phases['B1_B2']=round(phases.get('B1_B2',0)+perf_counter()-before,4)
    service.rule_engine.evaluate=evaluate
    return service


def _analyze_inprocess(code,root=None,cache=None,service=None):
    service=service or create_web_service(root,cache)
    try:
        return _analysis_and_chart(code,service)
    finally:
        for provider in service.provider_manager.providers:
            close=getattr(provider,'close',None)
            if close: close()


def analyze_stock(code):
    code=normalize_stock_code(code)
    # Construction is network-free and retains the existing mock rejection seam.
    service=create_web_service()
    if service.provider_manager.provider.is_mock:
        raise DataError('当前数据源不是可用于公开展示的真实行情。')
    from app.web_runtime import bounded_web_call
    return bounded_web_call(_analyze_inprocess,(code,),root=Path(__file__).resolve().parents[1])


def _analysis_and_chart(code,service):
    output = service.analyze(normalize_stock_code(code)).to_dict()
    if output['data_status']['is_mock']:
        raise DataError('当前数据源不是可用于公开展示的真实行情。')
    if output['data_status']['status'] != 'UNAVAILABLE':
        try:
            chart_started=perf_counter()
            import json
            from app.features.technical import build_features
            # Reuse the same provider/cache and evaluation date as the analysis.
            market = service.provider_manager.fetch(output['symbol'])
            if market.metadata['is_mock']:
                raise DataError('图表数据不是可用于公开展示的真实行情。')
            bars = build_features(market.bars, as_of=output['evaluation_date'])
            fields = ['date','open_adj','high_adj','low_adj','close_adj','volume','M5','M30','M60']
            output['chart'] = json.loads(bars.tail(120)[fields].to_json(orient='records', date_format='iso'))
            row = bars.iloc[-1]
            import math
            reference = row.get('preclose')
            if reference is not None and math.isfinite(float(reference)) and float(reference)>0:
                change = float(row.close_raw) - float(reference)
                output['quote_change'] = {'amount':change, 'percent':change/float(reference)*100, 'basis':'BaoStock preclose'}
            output['chart_provider'] = market.metadata['provider']
            if hasattr(service,'web_latency'):
                service.web_latency['phase_seconds']['chart_data']=round(perf_counter()-chart_started,4)
        except Exception:
            output['chart'] = []
            output['chart_warning'] = '行情图数据暂不可用，已有规则分析结果保持不变。'
    if hasattr(service,'web_latency'):
        cache=service.provider_manager.cache
        service.web_latency['phase_seconds']['benchmark_snapshot_load']=round(cache.benchmark_seconds,4)
        service.web_latency.update(cache_hits=cache.hits,cache_misses=cache.misses,
                                   benchmark_status=cache.benchmark_status,
                                   provider_timeouts=sum(getattr(p,'timeout_count',0) for p in service.provider_manager.providers),
                                   provider_worker_starts=sum(getattr(p,'worker_starts',0) for p in service.provider_manager.providers),
                                   benchmark_snapshot=cache.snapshots.benchmark_evidence)
        output['web_latency']=service.web_latency
        if output['industry_context'].get('data_status')!='VALID':
            output['warnings'].append('行业快照缺失、日期不匹配或不可用；B1/B2按原规则返回对应数据状态，不实时抓取整个行业。')
        if cache.benchmark_status!='VALID':
            output['warnings'].append('同交易日指数快照不可用；大盘相关规则按原有缺数据语义处理，不使用旧值。')
    return output


def coverage_text(value):
    return '暂不可计算' if value is None else f'{value * 100:.1f}%'


def number_text(value):
    return '—' if value is None else f'{value:g}'
