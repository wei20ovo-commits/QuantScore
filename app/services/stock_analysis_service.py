from copy import deepcopy

from app.data.models import BENCHMARK_SYMBOL, DataError, ProviderError
from app.data.provider_manager import ProviderManager
from app.engine.rule_engine import RuleEngine
from app.engine.score_engine import ScoreEngine
from app.features.market_context import build_context, market_context
from app.features.technical import FeatureBuilder
from app.models.schemas import AnalysisResult, DataStatus
from app.rules.base import UnknownData, result

_DEFAULT_INDUSTRY = object()


class StockAnalysisService:
    def __init__(self, provider_manager=None, rule_engine=None, feature_builder=None, industry_service=_DEFAULT_INDUSTRY):
        self.provider_manager = provider_manager if provider_manager is not None else ProviderManager()
        self.rule_engine = rule_engine if rule_engine is not None else RuleEngine()
        self.feature_builder = feature_builder if feature_builder is not None else FeatureBuilder(self.rule_engine.parameters)
        self.score_engine = ScoreEngine(self.rule_engine)
        if industry_service is _DEFAULT_INDUSTRY:
            if self.provider_manager.provider.is_mock:
                industry_service = None  # Offline fixtures never trigger real industry requests.
            else:
                from app.sector.industry_context import PrimaryIndustryService
                industry_service = PrimaryIndustryService(cache=self.provider_manager.cache)
        self.industry_service = industry_service

    def rules(self):
        return deepcopy(list(self.rule_engine.registry.values()))

    def _load(self, symbol, as_of=None, refresh=False):
        manager = self.provider_manager
        status = DataStatus(requested_symbol=symbol, status='UNAVAILABLE',
                            provider=manager.provider.name, is_mock=manager.provider.is_mock)
        try:
            security = manager.resolver.resolve(symbol)
        except ProviderError as exc:
            status.error_code = exc.code
            status.warnings.append(str(exc))
            return None, status
        # 非法/歧义代码属于请求错误；有效代码的数据失败才进入降级。
        status.symbol = security.symbol
        try:
            data = manager.fetch(security, as_of=as_of, refresh=refresh)
            if data.metadata.get('benchmark_symbol', BENCHMARK_SYMBOL) != BENCHMARK_SYMBOL:
                raise DataError('大盘基准必须为 000001.SH')
            context = build_context(data, as_of, self.feature_builder)
            status.rows = len(context.bars)
            status.evaluation_date = str(context.bars.date.iloc[-1].date()) if status.rows else None
            status.benchmark_available = context.benchmark is not None and not context.benchmark.empty
            status.raw_rows = data.metadata.get('raw_rows', status.rows)
            status.adjusted_rows = data.metadata.get('adjusted_rows', status.rows)
            status.benchmark_rows = 0 if context.benchmark is None else len(context.benchmark)
            status.last_trade_date = status.evaluation_date
            status.limit_price_source = str(context.bars.limit_source.iloc[-1]) if 'limit_source' in context.bars else 'UNKNOWN'
            status.field_coverage = {key:float(context.bars[key].notna().mean()) for key in context.bars.columns}
            status.provider = data.metadata['provider']
            status.is_mock = data.metadata['is_mock']
            status.metadata = dict(data.metadata)
            status.warnings = list(data.warnings)
            optional = ('volume', 'amount', 'turnover_rate', 'limit_up_price', 'limit_down_price')
            missing = [key for key in optional if key not in context.bars or context.bars[key].isna().any()]
            if missing:
                status.warnings.append('部分字段缺失，相关规则可能 UNKNOWN：' + ', '.join(missing))
            status.status = ('UNAVAILABLE' if not status.rows else
                             'PARTIAL' if missing or not status.benchmark_available else 'AVAILABLE')
            return (data, context), status
        except (ProviderError, DataError, UnknownData) as exc:
            status.error_code = exc.code
            status.warnings.append(str(exc))
            return None, status

    def data_status(self, symbol, *, as_of=None, refresh=False):
        return self._load(symbol, as_of, refresh)[1]

    def analyze(self, symbol, *, as_of=None, refresh=False):
        loaded, status = self._load(symbol, as_of, refresh)
        forward_confirmation = None
        industry_context = {}
        if loaded is None or not status.rows:
            unknown = [result(rule, 'UNKNOWN', reason_code='DATA_INSUFFICIENT',
                              raw=({'upstream_data_status':'DATA_ERROR','data_status':'DATA_ERROR',
                                    'sector_heat_status':'DATA_ERROR','provider_error_code':status.error_code,
                                    'provider_errors':list(status.warnings)} if rule['rule_id'] in ('B1','B2') else {}),
                              explanation='行情不可用，不能执行自动判断。')
                       for rule in self.rule_engine.registry.values() if rule['rule_type'] != 'SECTOR']
            score = self.score_engine.aggregate(unknown)
            score['evaluation_date'] = None
            name, market = '', market_context(None)
        else:
            data, context = loaded
            if self.industry_service is not None and data.security.asset_type == 'STOCK':
                try:
                    industry_context = self.industry_service.build(status.symbol, status.evaluation_date, refresh=refresh)
                except Exception as exc:
                    industry_context = {'data_status':'DATA_ERROR','reason_code':str(exc)}
                context.metadata['industry_context'] = industry_context
                context.metadata['symbol'] = status.symbol
            from app.rules.risks.should_rise import ScoreSnapshot
            snapshots = self.provider_manager.cache.score_snapshots(status.symbol)
            if snapshots:
                context.metadata['score_snapshots'] = snapshots
            score = self.score_engine.evaluate(context)
            # Presentation field only: the existing aggregate algorithm is unchanged.
            score['sector_heat_score'] = (industry_context.get('sector_heat') or {}).get('total_score')
            # An on-demand historical evaluation is not a contemporaneous signal.
            # Never manufacture historical snapshots for later forward confirmation.
            if as_of is None:
                self.provider_manager.cache.freeze_score(status.symbol, ScoreSnapshot.freeze(score, context.bars))
            # Historical forward confirmation is separate from the as_of score.
            # Only a pre-existing immutable snapshot can be checked; never backfill it.
            frozen = [s for s in snapshots if s.signal_date == status.evaluation_date]
            if as_of and frozen:
                try:
                    future_data = self.provider_manager.fetch(data.security, refresh=refresh)
                    from app.rules.base import Context
                    forward_context = Context(future_data.bars, metadata={**future_data.metadata,'score_snapshots':frozen})
                    forward_confirmation = self.rule_engine.evaluate('R7',forward_context).to_dict()
                except (DataError,ProviderError,UnknownData) as exc:
                    forward_confirmation = {'status':'UNKNOWN','reason_code':exc.code}
            name, market = data.security.name, market_context(context.benchmark, as_of)
        import math
        price, indicators = {}, {}
        if loaded is not None and status.rows:
            row = loaded[1].bars.iloc[-1]
            def value(key):
                x = row.get(key)
                return float(x) if x is not None and math.isfinite(float(x)) else None
            price = {key:value(key+'_raw') for key in ('open','high','low','close')}
            indicators = {key:value(key) for key in ('M5','M20','M30','M60','VMA20','volume_ratio_20')}
        rules = deepcopy(score['rules'])
        for item in rules:
            item['data_provenance'] = status.metadata.get('data_provenance', [])
        fields = {key:score[key] for key in ('positive_score','risk_penalty','risk_level','positive_coverage','risk_coverage','score_status','top_positive_reasons','top_risk_reasons')}
        return AnalysisResult(requested_symbol=symbol, symbol=status.symbol, name=name,
                              as_of=status.evaluation_date, evaluation_date=status.evaluation_date, data_status=status,
                              r7_forward_confirmation=forward_confirmation,
                              market=market, price=price, indicators=indicators, rules=rules,
                              industry_context=industry_context,
                              final_quant_score=score['final_score'], **fields,
                              market_context=market, score=score, warnings=list(status.warnings))
