"""只从评价日及之前的前复权日线计算规范派生变量。"""
import numpy as np
import pandas as pd
from app.data.validators import DataValidator


def build_features(bars, as_of=None, parameters=None):
    d = DataValidator.dates(bars)
    if as_of is not None:
        d = d.loc[d.date <= pd.Timestamp(as_of)].reset_index(drop=True)
    g = (parameters or {}).get('GLOBAL', {})
    if 'close_adj' in d:
        close = d.close_adj
        for w in g.get('ma_windows', [5, 20, 30, 60]):
            d[f'M{w}'] = close.rolling(w, min_periods=w).mean()
        for w in (1, 5, 20, 60):
            d[f'return_{w}d'] = close / close.shift(w).replace(0, np.nan) - 1
        if 'M60' in d:
            d['M60_slope_10'] = d.M60 / d.M60.shift(g.get('slope_window', 10)).replace(0, np.nan) - 1
        if {'high_adj', 'low_adj'} <= set(d):
            w = g.get('position_window', 120)
            low, high = d.low_adj.rolling(w).min(), d.high_adj.rolling(w).max()
            d['position_120'] = (close - low) / (high - low).replace(0, np.nan)
            previous = close.shift(1)
            ranges = pd.concat([d.high_adj - d.low_adj, (d.high_adj - previous).abs(),
                                (d.low_adj - previous).abs()], axis=1)
            tr = ranges.max(axis=1, skipna=False)
            d['ATR10'] = tr.rolling(10, min_periods=10).mean()
            d['ATR10_pct'] = d.ATR10 / close.replace(0, np.nan)
    if 'volume' in d:
        w = g.get('volume_window', 20)
        d['VMA20'] = d.volume.rolling(w, min_periods=w).mean()
        d['volume_ratio_20'] = d.volume / d.VMA20.shift(1).replace(0, np.nan)
    return d


class FeatureBuilder:
    def __init__(self, parameters=None):
        self.parameters = parameters

    def build(self, bars, as_of=None):
        return build_features(bars, as_of, self.parameters)
