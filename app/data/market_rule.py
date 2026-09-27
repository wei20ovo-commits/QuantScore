"""保守涨跌停解析：无可核验历史规则与元数据时不按代码前缀推算。"""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import pandas as pd
from app.data.validators import DataValidator


@dataclass(frozen=True)
class LimitResult:
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    limit_source: str = 'UNKNOWN'
    limit_confidence: str = 'UNKNOWN'
    reason_code: str | None = 'LIMIT_PRICE_UNRELIABLE'


def _positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


class MarketLimitResolver:
    def resolve(self, *, date=None, reported=None, metadata=None, previous_close=None):
        reported, m = reported or {}, metadata or {}
        up, down = reported.get('limit_up_price'), reported.get('limit_down_price')
        if _positive(up) and _positive(down) and float(up) >= float(down):
            return LimitResult(float(up), float(down), 'PROVIDER_REPORTED', 'HIGH', None)
        # 历史规则必须由调用方提供带有效期的证据，默认源不会伪造这些字段。
        required = ('exchange', 'board', 'listing_date', 'status_date', 'is_st',
                    'rule_valid_from', 'rule_valid_to', 'rule_source', 'limit_ratio', 'price_tick')
        if date is None or any(m.get(k) is None for k in required):
            return LimitResult()
        try:
            day = pd.Timestamp(date).normalize()
            reliable = (m.get('metadata_verified') is True and m.get('rule_verified') is True
                        and m.get('special_session') is False and m.get('normal_listing_period') is True
                        and m.get('reference_price_verified') is True and isinstance(m['is_st'], bool)
                        and m['exchange'] in ('SH', 'SZ', 'BJ') and bool(m['board'])
                        and bool(m['rule_source']) and pd.Timestamp(m['listing_date']) < day
                        and pd.Timestamp(m['status_date']).normalize() == day
                        and pd.Timestamp(m['rule_valid_from']) <= day <= pd.Timestamp(m['rule_valid_to']))
            if not reliable or not _positive(previous_close):
                return LimitResult()
            ratio, tick, close = (Decimal(str(x)) for x in (m['limit_ratio'], m['price_tick'], previous_close))
            if not all(x.is_finite() for x in (ratio, tick, close)) or not 0 < ratio < 1 or tick <= 0:
                return LimitResult()
            def rounded(value):
                return float((value / tick).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick)
            up, down = rounded(close * (1 + ratio)), rounded(close * (1 - ratio))
            if down <= 0 or up <= down:
                return LimitResult()
            return LimitResult(up, down, 'MARKET_RULE_CALCULATED', 'VERIFIED', None)
        except (ValueError, TypeError, InvalidOperation):
            return LimitResult()

    def apply(self, bars, reported=None, historical_metadata=None):
        d = DataValidator.dates(bars)
        supplied = {}
        if reported is not None and not reported.empty:
            limits = DataValidator.dates(reported)
            supplied = {r['date']: r for r in limits.to_dict('records')}
        history = historical_metadata or {}
        rows = []
        for i, row in d.iterrows():
            metadata = history.get(row.date, history.get(str(row.date.date()), {}))
            # A verified ex-rights reference can differ from yesterday's raw close.
            reference = metadata.get('reference_price', d.close_raw.iloc[i - 1] if i else None)
            result = self.resolve(date=row.date, reported=supplied.get(row.date), metadata=metadata,
                                  previous_close=reference)
            rows.append(asdict(result))
        for col in LimitResult.__dataclass_fields__:
            d[col if col != 'reason_code' else 'limit_reason_code'] = [r[col] for r in rows]
        return d
