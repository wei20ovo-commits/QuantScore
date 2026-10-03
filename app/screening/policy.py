"""Eligibility policy: unresolved business meanings are explicit, never inferred."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import yaml


@dataclass(frozen=True)
class ScreeningPolicy:
    heat_min: float
    history_min: int
    quant_score_min: float | None = None
    coverage_field: str | None = None
    coverage_min: float | None = None
    excluded_risks: tuple[str, ...] | None = None
    sector_cap: int | None = None
    sector_cap_resolved: bool = False
    resolution_source: str = 'SEMANTIC_GAP'
    semantic_gaps: tuple[str, ...] = field(default_factory=lambda: (
        'QUANTSCORE_CANDIDATE_THRESHOLD', 'SCREENING_COVERAGE_DEFINITION',
        'HIGH_RISK_ELIGIBILITY', 'SECTOR_BUSINESS_CAP'))

    @classmethod
    def current(cls):
        p = yaml.safe_load((Path(__file__).resolve().parents[2] / 'config/parameters.yaml').read_text('utf-8'))['SECTOR']
        frozen = yaml.safe_load((Path(__file__).resolve().parents[2] / 'config/screening.yaml').read_text('utf-8'))
        return cls(heat_min=frozen['sector_heat_min'], history_min=p['history_min'],
                   quant_score_min=frozen['quant_score_min'], excluded_risks=tuple(frozen['excluded_risks']),
                   sector_cap_resolved=True, resolution_source=frozen['resolution_source'], semantic_gaps=())

    @property
    def resolved(self):
        return (not self.semantic_gaps and self.quant_score_min is not None
                and self.excluded_risks is not None and self.sector_cap_resolved
                and self.resolution_source != 'SEMANTIC_GAP')

    def sector(self, heat, day):
        if heat.get('trade_date') != day:
            return 'NOT_EVALUABLE', 'DATA_STALE'
        if heat.get('overall_status') != 'VALID' or heat.get('total_score') is None:
            return 'NOT_EVALUABLE', heat.get('overall_status', 'DATA_INCOMPLETE')
        value = heat['total_score']
        if not math.isfinite(value):
            return 'NOT_EVALUABLE', 'DATA_INCONSISTENT'
        return ('ELIGIBLE' if value >= self.heat_min else 'NOT_MATCHED'), 'VALID'

    def stock(self, analysis, day, sector_id):
        ds = analysis.get('data_status', {})
        if ds.get('status') == 'UNAVAILABLE':
            return 'NOT_EVALUABLE', 'DATA_ERROR', '行情不可用；不是零分或策略不匹配。'
        if ds.get('rows', 0) < self.history_min:
            return 'NOT_EVALUABLE', 'DATA_INCOMPLETE', '历史交易日数量不足。'
        context = analysis.get('industry_context') or {}
        primary = context.get('primary_industry') or {}
        if analysis.get('evaluation_date') != day or primary.get('as_of') != day:
            return 'NOT_EVALUABLE', 'DATA_STALE', '评价日或行业归属日期不一致。'
        if primary.get('sector_id') != sector_id or primary.get('symbol') != analysis.get('symbol'):
            return 'NOT_EVALUABLE', 'DATA_INCONSISTENT', '不是本次扫描的唯一primary industry。'
        state, quality = self.sector(context.get('sector_heat') or {}, day)
        if state == 'NOT_EVALUABLE':
            return state, quality, '行业热度不可评，保留上游数据状态。'
        if context.get('data_status') != 'VALID':
            return 'NOT_EVALUABLE', context.get('data_status', 'DATA_INCOMPLETE'), '行业数据无效。'
        if not self.resolved:
            return 'NOT_EVALUABLE', 'SEMANTIC_GAP', '候选门槛尚未冻结：' + ', '.join(self.semantic_gaps)
        score = analysis.get('final_quant_score')
        rules = {r['rule_id']: r for r in analysis.get('rules', [])}
        if score is None or not math.isfinite(score):
            return 'NOT_EVALUABLE', 'DATA_INCOMPLETE', 'QuantScore不能合法生成。'
        for rid in ('B1','B2'):
            raw = rules.get(rid, {}).get('raw_values') or {}
            for field in ('upstream_data_status','data_status','sector_heat_status'):
                if raw.get(field) in ('DATA_ERROR','DATA_STALE','DATA_INCONSISTENT'):
                    return 'NOT_EVALUABLE', raw[field], f'{rid}关键输入存在数据质量问题。'
        returns = context.get('returns') or {}
        if returns.get('data_status') in ('DATA_ERROR', 'DATA_STALE', 'DATA_INCONSISTENT'):
            return 'NOT_EVALUABLE', returns['data_status'], '行业收益关键输入存在数据质量问题。'
        risk = analysis.get('risk_level')
        if risk not in ('LOW', 'MEDIUM', 'HIGH'):
            return 'NOT_EVALUABLE', 'DATA_INCOMPLETE', 'Risk不可判定。'
        matched = (state == 'ELIGIBLE' and score >= self.quant_score_min and risk not in self.excluded_risks)
        explanation = (f'行业Heat={context["sector_heat"]["total_score"]}，QuantScore={score}，'
                       f'Risk={risk}；'
                       + ('满足冻结策略条件，属于策略匹配候选。' if matched else '未满足冻结策略条件。'))
        return ('MATCHED' if matched else 'NOT_MATCHED'), 'VALID', explanation
