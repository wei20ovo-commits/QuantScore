"""Auditable Stage 3A.5 helpers; offline replay of saved real responses."""
from decimal import Decimal, ROUND_HALF_UP
import re
import pandas as pd

S4_FIELDS = {
    'symbol','name','date','exchange','board','preclose','isST','ipoDate',
    'trading_days_since_ipo','limit_ratio','calculated_limit_up','calculated_limit_down',
    'actual_high','actual_close','touched_limit_up','closed_at_limit_up',
    'independent_source','independent_source_id_or_url','independent_limit_up_price',
    'independent_limit_status','price_match','status_match','notes',
}

def money(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def cash_dividend_reference(previous_actual_close, announced_cash_per_share):
    """Only for issuer-confirmed cash-only distributions; never a general ex-rights proxy."""
    return money(Decimal(str(previous_actual_close)) - Decimal(str(announced_cash_per_share)))

def ipo_trading_day_count(calendar, ipo_date, trade_date):
    ipo, day = pd.Timestamp(ipo_date), pd.Timestamp(trade_date)
    dates = pd.to_datetime(calendar.calendar_date)
    if pd.isna(ipo) or pd.isna(day) or ipo > day or dates.min() > ipo or dates.max() < day:
        raise ValueError('Incomplete IPO/calendar evidence')
    return int(((dates >= ipo) & (dates <= day) & calendar.is_trading_day.eq(1)).sum())

def parse_tencent_quotes(payload, expected_date):
    """Tencent quote fields 47/48 are reported limits, not locally reconstructed limits.

    Schema: 1 name, 2 code, 3 last, 4 reference, 30 timestamp, 33 high,
    47 upper limit, 48 lower limit. Reject malformed, stale or intraday responses.
    """
    text = payload.decode('gbk') if isinstance(payload, bytes) else payload
    rows = []
    for source_id, body in re.findall(r'v_((?:sh|sz)\d{6})="([^"]*)"', text):
        fields = body.split('~')
        if len(fields) < 49 or fields[2] != source_id[2:]:
            raise ValueError('Tencent schema/symbol mismatch')
        stamp = fields[30]
        if not re.fullmatch(r'\d{14}', stamp):
            raise ValueError('Tencent timestamp missing')
        dt = pd.to_datetime(stamp, format='%Y%m%d%H%M%S')
        if str(dt.date()) != str(expected_date) or dt.hour < 15:
            raise ValueError('Tencent quote is not the requested completed trading day')
        values = [Decimal(fields[i]) for i in (3,4,33,47,48)]
        if not all(v.is_finite() and v > 0 for v in values):
            raise ValueError('Tencent invalid prices')
        close, reference, high, up, down = values
        if not down < up or close > high:
            raise ValueError('Tencent inconsistent prices')
        rows.append(dict(symbol=source_id[2:]+'.'+source_id[:2].upper(), name=fields[1],
                         date=str(dt.date()), timestamp=stamp, source_id=source_id,
                         close=float(close), preclose=float(reference), high=float(high),
                         limit_up=float(up), limit_down=float(down), closed=close>=up))
    if not rows or len({r['symbol'] for r in rows}) != len(rows):
        raise ValueError('Missing or duplicate Tencent quotes')
    return rows

def comparison_summary(rows):
    frame = pd.DataFrame(rows)
    if not S4_FIELDS <= set(frame):
        raise ValueError('S4 evidence schema incomplete')
    pc = frame.price_match.notna()
    sc = frame.status_match.notna()
    mismatch = (pc & frame.price_match.eq(False)) | (sc & frame.status_match.eq(False))
    return dict(sample_count=len(frame), price_comparable_count=int(pc.sum()),
                price_match_count=int(frame.price_match.eq(True).sum()),
                status_comparable_count=int(sc.sum()), status_match_count=int(frame.status_match.eq(True).sum()),
                mismatch_count=int(mismatch.sum()),
                positive_count=int(frame.independent_limit_status.eq('CLOSED_AT_LIMIT_UP').sum()),
                negative_count=int(frame.independent_limit_status.eq('NOT_CLOSED_AT_LIMIT_UP').sum()),
                comparison_status='PASS' if pc.all() and sc.all() and not mismatch.any() else 'PARTIAL')
