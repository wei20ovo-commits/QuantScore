import pandas as pd
from app.data.models import DataError
from app.data.validators import DataValidator


def resample_bars(bars, timeframe='W', as_of=None, *, completed_only=True, trading_calendar=None):
    """默认以日历周期保守确认；完整交易日历可确认节假日缩短周期。"""
    if timeframe not in ('W', 'M'):
        raise DataError('只支持 W/M 聚合')
    d = DataValidator.dates(bars)
    cutoff = pd.Timestamp(as_of) if as_of is not None else d.date.iloc[-1]
    d = d.loc[d.date <= cutoff].copy()
    frequency = 'W-FRI' if timeframe == 'W' else 'M'
    fields = [f'{x}_{s}' for s in ('raw', 'adj') for x in ('open', 'high', 'low', 'close')]
    fields += ['volume', 'amount']
    columns = ['date', *[c for c in fields if c in d], 'is_complete', 'is_complete_period']
    if d.empty:
        return pd.DataFrame(columns=columns)
    calendar = None
    if trading_calendar is not None:
        calendar = pd.DatetimeIndex(pd.to_datetime(trading_calendar)).normalize().sort_values().unique()
    d['_period'] = d.date.dt.to_period(frequency)
    rows = []
    for period, group in d.groupby('_period', sort=True):
        start, end = period.start_time.normalize(), period.end_time.normalize()
        if calendar is None:
            expected = pd.bdate_range(start, end)
            # 没有交易所日历时不猜测节假日；缺任何工作日日线均保守视为未完成。
            complete = bool(len(expected) and end <= cutoff.normalize()
                            and set(expected) == set(group.date))
            label = end
        else:
            expected = calendar[(calendar >= start) & (calendar <= end)]
            complete = bool(len(expected) and expected[-1] <= cutoff and set(expected) == set(group.date)
                            and calendar[0] <= start and calendar[-1] >= end)
            label = expected[-1] if len(expected) else end
        if completed_only and not complete:
            continue
        row = {'date': label, 'is_complete': complete, 'is_complete_period': complete}
        for col in fields:
            if col not in group:
                continue
            series = group[col]
            if series.isna().any():
                row[col] = float('nan')
            elif col.startswith('open_'):
                row[col] = series.iloc[0]
            elif col.startswith('close_'):
                row[col] = series.iloc[-1]
            elif col.startswith('high_'):
                row[col] = series.max()
            elif col.startswith('low_'):
                row[col] = series.min()
            else:
                row[col] = series.sum()
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def build_period_bars(bars, as_of=None, trading_calendar=None):
    return {p: resample_bars(bars, p, as_of, trading_calendar=trading_calendar) for p in ('W', 'M')}
