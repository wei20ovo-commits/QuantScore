"""Read-only presentation contracts. No provider, screening runner or scoring calls."""
from dataclasses import dataclass, field
from datetime import date, datetime
import json
import math
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
STATUS_HELP = {
    'VALID': '数据通过上游校验，可按已有规则评分。',
    'UNKNOWN': '证据、字段或确认期不足；不等于条件失败。',
    'NOT_APPLICABLE': '当前对象不适用该规则。',
    'DATA_INCOMPLETE': '必需数据或样本不足，完整评分不可生成。',
    'DATA_ERROR': '数据读取或上游请求失败，不能作为零分。',
    'DATA_STALE': '数据日期不符合评价日期要求。',
    'DATA_INCONSISTENT': '字段、日期或来源校验不一致。',
}
RUN_HELP = {
    'COMPLETE': '后台批处理已完成',
    'PARTIAL': '后台已结束，部分对象不可评',
}


@dataclass
class ScreeningSnapshot:
    status: str
    message: str = ''
    source: str | None = None
    payload: dict = field(default_factory=dict)

    @property
    def available(self):
        return bool(self.payload)

    @property
    def generated_at(self):
        return self.payload.get('generated_at') or self.payload.get('updated_at') or self.payload.get('end_time')

    @property
    def providers(self):
        names = set()
        for sector in self.payload.get('sectors', []):
            context = sector.get('context') or {}
            for provenance in [context.get('provenance'), (context.get('sector_heat') or {}).get('provenance')]:
                if isinstance(provenance, dict) and provenance.get('provider'):
                    names.add(str(provenance['provider']))
        return ' / '.join(sorted(names)) or '来源未记录'


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def display_score(value, data_status='VALID'):
    """Missing/invalid evidence is always an em dash, even in a malformed artifact."""
    return value if data_status == 'VALID' and finite(value) else None


def _relative_file(root, value):
    path = Path(value)
    if path.is_absolute() or re.match(r'^[A-Za-z]:', str(value)) or '\\' in str(value):
        raise ValueError('结果路径必须为项目内相对路径')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('结果路径超出项目目录')
    return resolved


def _validate(payload):
    if not isinstance(payload, dict) or payload.get('is_mock') is not False or payload.get('mode') != 'live':
        raise ValueError('仅接受有真实 live 来源标记的正式结果')
    if payload.get('scope') != 'SH_SZ_PRIMARY_INDUSTRIES' or payload.get('operational_limit_industries') is not None:
        raise ValueError('不展示子集、性能样本或其他范围结果')
    if payload.get('status') not in RUN_HELP or payload.get('complete') is False:
        raise ValueError('结果尚未完成，不能作为正式结果')
    date.fromisoformat(payload['trade_date'])
    generated = payload.get('generated_at') or payload.get('updated_at') or payload.get('end_time')
    if not generated or datetime.fromisoformat(generated).tzinfo is None:
        raise ValueError('缺少带时区的结果生成时间')
    for name in ['sectors', 'stocks', 'candidates']:
        if not isinstance(payload.get(name), list):
            raise ValueError('结果缺少完整列表')
    stats = payload.get('stats')
    if not isinstance(stats, dict):
        raise ValueError('结果缺少统计信息')
    for key in ['industry_total', 'industry_scoreable', 'industry_candidate', 'industry_invalid',
                'stock_expected', 'stock_analyzed', 'stock_error', 'stock_incomplete', 'strategy_match_candidates']:
        value = stats.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError('统计信息不完整')
    sectors = payload['sectors']
    if (len(sectors) != payload.get('industry_universe_total') or stats['industry_total'] != len(sectors)
            or stats['stock_expected'] != stats['stock_analyzed'] or stats['stock_analyzed'] != len(payload['stocks'])
            or stats['strategy_match_candidates'] != len(payload['candidates'])):
        raise ValueError('Universe / 批次统计不一致')
    if stats['industry_scoreable'] + stats['industry_invalid'] != len(sectors):
        raise ValueError('行业统计不一致')
    if (stats['industry_scoreable'] != sum(s.get('data_status') == 'VALID' for s in sectors)
            or stats['industry_candidate'] != sum(s.get('candidate_status') == 'ELIGIBLE' for s in sectors)):
        raise ValueError('统计与已保存判定不一致')
    if len({s['sector_id'] for s in sectors}) != len(sectors):
        raise ValueError('重复行业')
    for sector in sectors:
        if (not isinstance(sector.get('sector_id'), str) or not isinstance(sector.get('sector_name'), str)
                or not isinstance(sector.get('context'), dict)
                or not isinstance(sector.get('constituent_count'), int)):
            raise ValueError('行业展示字段缺失')
        if sector.get('trade_date') != payload['trade_date'] or sector.get('data_status') not in STATUS_HELP:
            raise ValueError('行业日期或数据状态不一致')
        if sector['data_status'] == 'VALID' and not finite(sector.get('sector_heat')):
            raise ValueError('可评行业缺少评分')
    for stock in payload['stocks'] + payload['candidates']:
        if not isinstance(stock.get('symbol'), str) or not isinstance(stock.get('stock_name'), str):
            raise ValueError('股票展示字段缺失')
        if stock.get('trade_date') != payload['trade_date'] or stock.get('data_status') not in STATUS_HELP:
            raise ValueError('股票日期或数据状态不一致')
        if stock.get('candidate_status') not in ('MATCHED', 'NOT_MATCHED', 'NOT_EVALUABLE'):
            raise ValueError('缺少正式候选状态')
    by_symbol = {s['symbol']: s for s in payload['stocks']}
    if len(by_symbol) != len(payload['stocks']):
        raise ValueError('重复股票')
    for candidate in payload['candidates']:
        stock = by_symbol.get(candidate['symbol'])
        if candidate.get('candidate_status') != 'MATCHED' or not stock or stock.get('candidate_status') != 'MATCHED':
            raise ValueError('候选列表与后台判定不一致')
        if candidate.get('data_status') != 'VALID' or not finite(candidate.get('QuantScore')):
            raise ValueError('候选缺少合法评分')
        for key in ['sector_heat', 'B1', 'B2', 'QuantScore', 'Risk', 'data_status', 'trade_date']:
            if candidate.get(key) != stock.get(key):
                raise ValueError('候选字段与股票结果不一致')
    if len(payload['candidates']) != sum(s['candidate_status'] == 'MATCHED' for s in payload['stocks']):
        raise ValueError('候选列表缺项')
    # This validates transport, not Heat / QuantScore / risk threshold semantics.
    return payload


def load_screening_snapshot(root=None):
    root = Path(root or ROOT).resolve()
    try:
        settings = yaml.safe_load((root / 'config/web.yaml').read_text('utf-8'))
        values = settings['screening_results']
        if not isinstance(values, list) or not values:
            raise ValueError('没有配置正式结果路径')
        results = []
        for value in values:
            path = _relative_file(root, value)
            if not path.exists():
                continue
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('结果文件超出读取大小限制')
            payload = json.loads(path.read_text('utf-8'))
            results.append((path, _validate(payload)))
        if not results:
            return ScreeningSnapshot('UNKNOWN', '暂无最新筛选结果。等待后台发布正式结果；网页不会启动全市场扫描。')
        path, payload = max(results, key=lambda item: (
            item[1]['trade_date'], datetime.fromisoformat(item[1].get('generated_at') or item[1].get('updated_at') or item[1]['end_time'])))
        return ScreeningSnapshot('VALID', source=path.relative_to(root).as_posix(), payload=payload)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return ScreeningSnapshot('DATA_ERROR', '正式结果无法读取或校验未通过。数据错误不等于零分；请由后台检查发布文件。')


def sector_rows(snapshot, query='', descending=True):
    rows = []
    for sector in snapshot.payload.get('sectors', []):
        if query.casefold() not in (sector['sector_id'] + ' ' + sector['sector_name']).casefold():
            continue
        context = sector.get('context') or {}
        heat = context.get('sector_heat') or {}
        row = {'行业代码': sector['sector_id'], '行业': sector['sector_name'],
               'SectorHeat': display_score(sector.get('sector_heat'), sector['data_status']),
               '数据状态': sector['data_status'], '成分股数量': sector.get('constituent_count'),
               '交易日': sector['trade_date']}
        for index in range(1, 8):
            rule = heat.get(f's{index}') or {}
            row[f'S{index}'] = display_score(rule.get('score'), rule.get('data_status', 'UNKNOWN'))
        rows.append(row)
    return sorted(rows, key=lambda row: (row['SectorHeat'] is None,
                   (-(row['SectorHeat'] or 0) if descending else (row['SectorHeat'] or 0)), row['行业代码']))


def candidate_rows(snapshot):
    # Consume backend membership/order verbatim. No UI gate, TopN or rescoring.
    return [{'symbol': row['symbol'], 'stock_name': row.get('stock_name'),
             'industry': row.get('industry_name'), 'SectorHeat': display_score(row.get('sector_heat'), row['data_status']),
             'B1': display_score(row.get('B1'), row['data_status']), 'B2': display_score(row.get('B2'), row['data_status']),
             'QuantScore': display_score(row.get('QuantScore'), row['data_status']), 'Risk': row.get('Risk'),
             'trade_date': row['trade_date'], 'data_status': row['data_status']}
            for row in snapshot.payload.get('candidates', [])]


def active_rules(root=None):
    """Current registry + audited implementation matrix + ACTIVE sector freeze.

    S rules have a separate executor, so their stock-registry NOT_IMPLEMENTED
    flag is not their product implementation status. Never instantiate providers.
    """
    root = Path(root or ROOT)
    registry = yaml.safe_load((root / 'config/scoring_rules.yaml').read_text('utf-8'))
    matrix = {}
    for line in (root / 'docs/RULE_IMPLEMENTATION_MATRIX.md').read_text('utf-8').splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) == 8 and fields[5] in ('IMPLEMENTED', 'PARTIAL', 'NOT_IMPLEMENTED'):
            matrix[fields[1]] = fields[5]
    sector_definitions = {}
    for line in (root / 'docs/STAGE3B_RULE_FREEZE.md').read_text('utf-8').splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) == 12 and re.fullmatch(r'S[1-7]', fields[1]):
            sector_definitions[fields[1]] = fields
    rows = []
    for rule in registry['rules']:
        if rule.get('spec_status') != 'FROZEN_V1_4':
            continue
        row = dict(rule)
        row['code_status'] = matrix.get(rule['rule_id'], rule['code_status'])
        # Do not surface inherited algebra/source_text as ACTIVE: some historical
        # definitions are superseded by later freezes. The current explanation
        # contract describes the rule's purpose without reviving old thresholds.
        row['purpose'] = rule['name_cn'] + '；解释模板：' + rule['explanation_template']
        row['active_source'] = 'config/scoring_rules.yaml · V' + str(registry['spec_version'])
        if rule['rule_id'] in sector_definitions:
            fields = sector_definitions[rule['rule_id']]
            row['purpose'] = f'输入：{fields[3]}。前置：{fields[4]}。分档：{fields[5]}。覆盖：{fields[7]}。'
            row['active_source'] = 'docs/STAGE3B_RULE_FREEZE.md · ' + fields[10]
        rows.append(row)
    return rows
