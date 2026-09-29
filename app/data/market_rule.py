"""保守涨跌停解析：无可核验历史规则与元数据时不按代码前缀推算。"""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import pandas as pd
from app.data.validators import DataValidator
from enum import Enum


class LimitSupport(str, Enum):
    SUPPORTED = 'SUPPORTED'
    UNSUPPORTED = 'UNSUPPORTED'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class LimitResult:
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    limit_source: str = 'UNKNOWN'
    limit_confidence: str = 'UNKNOWN'
    reason_code: str | None = 'LIMIT_PRICE_UNRELIABLE'
    status: str = 'DATA_ERROR'
    support: str = 'UNKNOWN'
    limit_ratio: float | None = None
    rule_id: str | None = None
    rule_source: str | None = None
    is_price_limited: bool | None = None
    touched_limit_up: bool | None = None
    closed_at_limit_up: bool | None = None
    effective_from: str | None = None


def _positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


class LimitPriceEngine:
    @staticmethod
    def market_support(metadata=None):
        m=metadata or {}; ex=str(m.get('exchange','')).upper(); board=str(m.get('board','')).upper()
        if ex=='BJ' or board in {'BSE','BEIJING','北交所'}: return LimitSupport.UNSUPPORTED
        if ex not in {'SH','SZ'} or board in {'','UNKNOWN','OTHER'}: return LimitSupport.UNKNOWN
        return LimitSupport.SUPPORTED


class MarketLimitResolver(LimitPriceEngine):
    def resolve(self, *, date=None, reported=None, metadata=None, previous_close=None):
        reported, m = reported or {}, metadata or {}
        up, down = reported.get('limit_up_price'), reported.get('limit_down_price')
        if _positive(up) and _positive(down) and float(up) >= float(down):
            return LimitResult(float(up), float(down), 'PROVIDER_REPORTED', 'HIGH', None, support=LimitSupport.SUPPORTED, status='VALID')
        support = self.market_support(m)
        if support is LimitSupport.UNSUPPORTED:
            return LimitResult(reason_code='LIMIT_MARKET_UNSUPPORTED', support=support)
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


class CurrentMarketLimitEngine(MarketLimitResolver):
    """当前交易日涨跌停引擎，保留旧解析器兼容行为。"""
    RULES = {('SH','MAIN'):('SSE_MAIN_NORMAL_20260706',Decimal('.10')),('SH','MAIN_ST'):('SSE_MAIN_RISK_20260706',Decimal('.10')),('SH','STAR'):('SSE_STAR_CURRENT',Decimal('.20')),('SZ','MAIN'):('SZ_MAIN_CURRENT',Decimal('.10')),('SZ','MAIN_ST'):('SZ_MAIN_RISK_20260706',Decimal('.10')),('SZ','GEM'):('SZ_GEM_CURRENT',Decimal('.20')),('BJ','BSE'):('BSE_CURRENT',Decimal('.30'))}
    EFFECTIVE_FROM = '2026-07-06'
    OFFICIAL_SOURCES = {
        'SH': 'https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml',
        'SZ': 'https://www.szse.cn/lawrules/rule/trade/t20260424_620190.html',
    }
    @staticmethod
    def board_for(symbol, exchange, *, is_st=False):
        code=str(symbol).split('.')[0].zfill(6); ex=str(exchange).upper()
        if ex=='BJ': return 'BSE'
        if ex=='SH' and code.startswith('688'): return 'STAR'
        if ex=='SZ' and code.startswith(('300','301')): return 'GEM'
        if is_st and ex in {'SH','SZ'}: return 'MAIN_ST'
        return 'MAIN'
    def resolve_current(self, *, trade_date, symbol, exchange, previous_close, ipo_date=None, trading_days_since_ipo=None, is_st=False, high=None, close=None):
        ex=str(exchange).upper(); board=self.board_for(symbol,ex,is_st=is_st); rid_ratio=self.RULES.get((ex,board))
        if ex == 'BJ':
            return LimitResult(reason_code='OUT_OF_SCOPE_FOR_V1', status='NOT_APPLICABLE', support='UNSUPPORTED')
        try:
            day = pd.Timestamp(trade_date)
            count = int(trading_days_since_ipo)
            if (pd.isna(day) or day < pd.Timestamp(self.EFFECTIVE_FROM)
                    or count < 1 or count != float(trading_days_since_ipo)
                    or is_st not in (True, False, 0, 1)):
                return LimitResult(reason_code='CURRENT_RULE_METADATA_UNRELIABLE')
            if ipo_date is not None and (pd.isna(pd.Timestamp(ipo_date)) or pd.Timestamp(ipo_date) > day):
                return LimitResult(reason_code='IPO_METADATA_UNRELIABLE')
        except (TypeError, ValueError, OverflowError):
            return LimitResult(reason_code='CURRENT_RULE_METADATA_UNRELIABLE')
        if rid_ratio is None or not _positive(previous_close): return LimitResult(reason_code='LIMIT_PRICE_UNRELIABLE')
        rid,ratio=rid_ratio
        source = self.OFFICIAL_SOURCES[ex]
        if count<=5: return LimitResult(limit_source='CURRENT_MARKET_RULE',limit_confidence='VERIFIED',reason_code='NO_DAILY_PRICE_LIMIT',status='NOT_APPLICABLE',support='SUPPORTED',rule_id=rid,rule_source=source,is_price_limited=False,effective_from=self.EFFECTIVE_FROM)
        c=Decimal(str(previous_close)); tick=Decimal('.01'); up=(c*(1+ratio)/tick).quantize(Decimal(1),rounding=ROUND_HALF_UP)*tick; down=(c*(1-ratio)/tick).quantize(Decimal(1),rounding=ROUND_HALF_UP)*tick
        # Both exchanges specify at least one tick of movement and a one-tick floor.
        up = max(up, c + tick)
        down = max(tick, min(down, c - tick))
        touched=None if not _positive(high) else Decimal(str(high))>=up
        # V1.4 S4 explicitly uses close_raw >= verified limit_up_price.
        closed=None if not _positive(close) else Decimal(str(close))>=up
        return LimitResult(float(up),float(down),'CURRENT_MARKET_RULE','VERIFIED',None,'VALID','SUPPORTED',float(ratio),rid,source,True,touched,closed,self.EFFECTIVE_FROM)



# Backward-compatible public import.
MarketLimitResolver = CurrentMarketLimitEngine
