import numpy as np
import pandas as pd
from app.data.models import DataError, OHLC


class DataValidator:
    @staticmethod
    def dates(frame, *, allow_empty=False):
        if frame is None or 'date' not in frame or (frame.empty and not allow_empty):
            raise DataError('缺少交易日或行情为空')
        d = frame.copy(deep=True)
        try:
            dates = pd.to_datetime(d.date, errors='raise')
            if dates.dt.tz is not None:
                raise DataError('日线交易日不能带时区')
        except (ValueError, TypeError, AttributeError) as exc:
            raise DataError('交易日格式无效') from exc
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise DataError('交易日必须有效、唯一且升序')
        if not dates.eq(dates.dt.normalize()).all():
            raise DataError('日线 date 必须为日期，不能包含盘中时间')
        d['date'] = dates
        return d.reset_index(drop=True)

    @classmethod
    def validate(cls, frame, *, suffixes=('raw', 'adj'), as_of=None):
        d = cls.dates(frame)
        for suffix in suffixes:
            fields = [f'{x}_{suffix}' if suffix else x for x in OHLC]
            if not set(fields) <= set(d):
                raise DataError('缺少 OHLC 字段：' + ','.join(fields))
            for col in fields:
                try:
                    d[col] = pd.to_numeric(d[col], errors='raise')
                except (ValueError, TypeError) as exc:
                    raise DataError(f'{col} 不是数值') from exc
            values = d[fields].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values <= 0).any():
                raise DataError('价格包含缺失值、非有限值或非正值')
            o, h, l, c = (d[f] for f in fields)
            if ((h < pd.concat([o, l, c], axis=1).max(axis=1)) |
                    (l > pd.concat([o, h, c], axis=1).min(axis=1))).any():
                raise DataError('OHLC 高低价关系非法')
        for col in ('volume', 'amount', 'turnover_rate', 'limit_up_price', 'limit_down_price'):
            if col not in d:
                continue
            try:
                d[col] = pd.to_numeric(d[col], errors='raise')
            except (ValueError, TypeError) as exc:
                raise DataError(f'{col} 不是数值') from exc
            known = d[col].dropna().to_numpy(dtype=float)
            if not np.isfinite(known).all() or (known < 0).any():
                raise DataError(f'{col} 包含非法数值')
            if col.startswith('limit_') and (known == 0).any():
                raise DataError('涨跌停价必须为正值或 null')
        if {'limit_up_price', 'limit_down_price'} <= set(d):
            known_pair = d[['limit_up_price', 'limit_down_price']].dropna()
            if (known_pair.limit_up_price < known_pair.limit_down_price).any():
                raise DataError('涨停价低于跌停价')
        if as_of is not None and pd.Timestamp(as_of).normalize() not in set(d.date):
            raise DataError('评价日没有股票行情')
        return d

    @classmethod
    def align_raw_qfq(cls, raw, qfq):
        raw = cls.validate(raw, suffixes=('',))
        qfq = cls.validate(qfq, suffixes=('',))
        if not raw.date.equals(qfq.date):
            raise DataError('raw/qfq 交易日不一致，禁止填充或丢弃日期')
        left = raw.rename(columns={c: f'{c}_raw' for c in OHLC})
        right = qfq[['date', *OHLC]].rename(columns={c: f'{c}_adj' for c in OHLC})
        return left.merge(right, on='date', how='inner', validate='one_to_one')

    @classmethod
    def benchmark_coverage(cls, bars, benchmark):
        b = cls.validate(benchmark)
        if not set(bars.date).issubset(set(b.date)):
            raise DataError('基准日期未覆盖股票交易日')
        return b


align_raw_qfq = DataValidator.align_raw_qfq
