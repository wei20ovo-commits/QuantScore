from dataclasses import dataclass, field
from pathlib import Path
import math
import numpy as np
import pandas as pd
import yaml
from functools import lru_cache
from copy import deepcopy
from app.models.schemas import RuleResult, Status

ROOT = Path(__file__).resolve().parents[2]


def load_config():
    return deepcopy(_read_config())


@lru_cache(maxsize=1)
def _read_config():
    registry = yaml.safe_load((ROOT/'config/scoring_rules.yaml').read_text(encoding='utf-8'))
    parameters = yaml.safe_load((ROOT/'config/parameters.yaml').read_text(encoding='utf-8'))
    for r in registry['rules']:
        r['implementation_status'] = r['code_status']
    return {r['rule_id']: r for r in registry['rules']}, parameters


class UnknownData(Exception):
    def __init__(self, reason, code='DATA_INSUFFICIENT', raw=None):
        super().__init__(reason)
        self.code, self.raw = code, raw or {}


@dataclass
class Context:
    bars: pd.DataFrame
    benchmark: pd.DataFrame | None = None
    metadata: dict = field(default_factory=dict)
    as_of: str | None = None

    def prepared(self):
        def prepare(df):
            if df is None:
                return None
            df = df.copy(deep=True)
            if 'date' not in df:
                if isinstance(df.index, pd.DatetimeIndex):
                    df.insert(0, 'date', df.index)
                else:
                    raise UnknownData('缺少 date 交易日索引', 'INVALID_DATA')
            dates = pd.to_datetime(df['date'], errors='coerce')
            if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
                raise UnknownData('交易日必须有效、唯一、按时间升序', 'INVALID_DATA')
            df['date'] = dates
            if self.as_of is not None:
                df = df.loc[dates <= pd.Timestamp(self.as_of)]
            return df.reset_index(drop=True)
        bars = prepare(self.bars)
        benchmark = prepare(self.benchmark)
        if benchmark is not None and len(bars):
            benchmark = benchmark.loc[benchmark.date <= bars.date.iloc[-1]].reset_index(drop=True)
        return Context(bars, benchmark, dict(self.metadata), self.as_of)


def require(df, fields, count):
    if df is None or len(df) < count:
        raise UnknownData(f'需要 {count} 根已完成K线，当前 {0 if df is None else len(df)} 根')
    missing = [f for f in fields if f not in df]
    if missing:
        raise UnknownData('缺少字段：' + ', '.join(missing))
    tail = df.iloc[-count:][fields]
    try:
        arr = tail.to_numpy(dtype=float)
    except (TypeError, ValueError):
        raise UnknownData('非数值行情字段', 'INVALID_DATA')
    if not np.isfinite(arr).all():
        limit_missing = any(f in ('limit_up_price','limit_down_price') and not np.isfinite(tail[f].to_numpy(dtype=float)).all() for f in fields)
        raise UnknownData('窗口内存在空值或非有限值', 'LIMIT_PRICE_UNRELIABLE' if limit_missing else 'INVALID_DATA')
    for f in fields:
        values = tail[f].to_numpy(dtype=float)
        if (values < 0).any() or (f not in ('volume','turnover_rate') and (values <= 0).any()):
            raise UnknownData(f'{f} 含不合法价格/数量', 'INVALID_DATA')
    for suffix in ('adj','raw'):
        names = [f'{x}_{suffix}' for x in ('high','low','close')]
        if set(names) <= set(fields):
            h,l,c = [tail[n] for n in names]
            o=tail[f'open_{suffix}'] if f'open_{suffix}' in fields else c
            if ((h < pd.concat([o,c,l],axis=1).max(axis=1)) | (l > pd.concat([o,c,h],axis=1).min(axis=1))).any():
                raise UnknownData('OHLC 高低价关系不合法', 'INVALID_DATA')


def divide(a, b):
    if not math.isfinite(float(b)) or b <= 0:
        raise UnknownData('分母为零或不可计算', 'INVALID_DATA')
    return float(a / b)


def indicators(df, p):
    from app.features.technical import build_features
    return build_features(df, parameters=p)


def high_zone(df, p, index=-1):
    prefix = df.iloc[:index+1] if index >= 0 else df
    g = p['GLOBAL']
    require(prefix, ['close_adj'], 61)
    ret60 = divide(prefix.close_adj.iloc[-1],prefix.close_adj.iloc[-61])-1
    if ret60 >= g['high_zone_ret60']:
        return True, {'return_60d':ret60}
    require(prefix, ['close_adj','high_adj','low_adj'],g['position_window'])
    recent=prefix.iloc[-g['position_window']:]
    pos=divide(prefix.close_adj.iloc[-1]-recent.low_adj.min(),recent.high_adj.max()-recent.low_adj.min())
    ret20=divide(prefix.close_adj.iloc[-1],prefix.close_adj.iloc[-21])-1
    return pos >= g['high_zone_position'] and ret20 >= g['high_zone_ret20'], {'position_120':pos,'return_20d':ret20,'return_60d':ret60}


def result(rule, status=None, score=0, penalty=0, raw=None, conditions=None, explanation='', **extra):
    if status is None:
        value, maximum = (penalty,rule['max_penalty']) if rule['rule_type']=='RISK' else (score,rule['max_score'])
        status = 'PASS' if value==maximum and value>0 else 'PARTIAL' if value>0 else 'FAIL'
    if status=='UNKNOWN':
        score=penalty=None
    prefix='V1.3代理规则/工程阈值；' if rule['source_type']=='AUTO_PROXY' else '规范 v1.3 工程阈值；'
    return RuleResult(rule_id=rule['rule_id'],name_cn=rule['name_cn'],category=rule['category'],
        rule_type=rule['rule_type'],source_type=rule['source_type'],status=status,score=score,
        max_score=rule['max_score'],penalty=penalty,max_penalty=rule['max_penalty'],
        raw_values=raw or {},conditions=conditions or {},explanation=prefix+explanation,
        code_status=rule['code_status'],source_note_pages=rule['source_note'],**extra)


def ambiguous_boundary(value, boundaries):
    """Compatibility stub: V1.3 uses explicit left-closed score tiers."""
    return None
