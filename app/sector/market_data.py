"""Stage 3A.2 market/sector data layer.

Pure calculations over an injectable data source; no scoring or UI dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import pandas as pd
import numpy as np

from .providers import DataStatus, SectorAggregate


class MarketDataSource(Protocol):
    def get_bars(self, symbols: list[str], start: date | None = None,
                 end: date | None = None) -> pd.DataFrame: ...


@dataclass(frozen=True)
class MarketDataResult:
    value: Any
    status: DataStatus
    as_of: date | None = None
    detail: str | None = None


@dataclass(frozen=True)
class SectorSnapshot:
    sector_id: str
    as_of: date | None
    return_1d: float | None
    return_5d: float | None
    breadth: float | None
    amount: float | None
    amount_20d_mean: float | None
    amount_20d_ratio: float | None
    quality: MarketDataResult


class LimitPriceEngine:
    """Interface placeholder. Approximate limit prices are deliberately unsupported."""
    def count_limit_up(self, *args: Any, **kwargs: Any) -> MarketDataResult:
        return MarketDataResult(None, DataStatus.NOT_APPLICABLE, detail="reliable limit_price data required")


def _date_column(frame: pd.DataFrame) -> str | None:
    for name in ("date", "trade_date", "日期", "datetime"):
        if name in frame.columns:
            return name
    return None


def align_bars(bars: pd.DataFrame, *, symbols: list[str] | None = None,
               start: date | None = None, end: date | None = None,
               trading_days: list[date] | None = None) -> pd.DataFrame:
    """Normalize symbols/dates, sort, and remove duplicate symbol/date rows."""
    if not isinstance(bars, pd.DataFrame):
        bars = pd.DataFrame(bars)
    date_col = _date_column(bars)
    if date_col is None or "symbol" not in bars.columns:
        raise ValueError("bars requires symbol and date/trade_date columns")
    out = bars.copy()
    out["date"] = pd.to_datetime(out[date_col], errors="coerce").dt.date
    out["symbol"] = out["symbol"].astype(str)
    out = out.dropna(subset=["date"])
    if symbols is not None:
        out = out[out["symbol"].isin(set(symbols))]
    if start is not None:
        out = out[out["date"] >= start]
    if end is not None:
        out = out[out["date"] <= end]
    out = out.sort_values(["symbol", "date"], kind="mergesort")
    out = out.drop_duplicates(["symbol", "date"], keep="last").reset_index(drop=True)
    if trading_days is not None:
        days = sorted({pd.Timestamp(d).date() for d in trading_days
                       if (start is None or pd.Timestamp(d).date() >= start)
                       and (end is None or pd.Timestamp(d).date() <= end)})
        grid = pd.MultiIndex.from_product([symbols if symbols is not None else out.symbol.unique(), days], names=['symbol','date'])
        out = out.set_index(['symbol','date']).reindex(grid).reset_index()
    return out


def _returns(bars: pd.DataFrame) -> pd.DataFrame:
    if "close" not in bars.columns:
        raise ValueError("bars requires close column")
    out = bars.copy()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["return_1d"] = out.groupby("symbol")["close"].pct_change(fill_method=None)
    out["return_5d"] = out.groupby("symbol")["close"].pct_change(5, fill_method=None)
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    return out


def sector_snapshot(sector_id: str, bars: pd.DataFrame, *, symbols: list[str] | None = None,
                    stale: bool = False, trading_days: list[date] | None = None) -> SectorSnapshot:
    """Compute current sector returns, breadth and amount from constituent bars."""
    try:
        frame = _returns(align_bars(bars, symbols=symbols, trading_days=trading_days))
    except Exception as exc:
        bad = MarketDataResult(None, DataStatus.DATA_ERROR, detail=str(exc))
        return SectorSnapshot(sector_id, None, None, None, None, None, None, None, bad)
    if frame.empty:
        bad = MarketDataResult(None, DataStatus.DATA_ERROR, detail="no bars")
        return SectorSnapshot(sector_id, None, None, None, None, None, None, None, bad)
    latest_date = max(frame["date"])
    latest = frame[frame["date"] == latest_date]
    valid = latest["return_1d"].notna()
    expected_missing = set(symbols or ()) - set(latest["symbol"])
    if expected_missing:
        status = DataStatus.DATA_INCONSISTENT
    else:
        status = DataStatus.DATA_STALE if stale else (DataStatus.VALID if valid.all() and valid.any() else DataStatus.DATA_INCONSISTENT)
    detail = None
    if expected_missing:
        detail = f"missing expected members: {', '.join(sorted(expected_missing))}"
    elif not valid.all():
        detail = "missing constituent returns"
    quality = MarketDataResult(int(valid.sum()), status, latest_date, detail)
    r1 = float(latest.loc[valid, "return_1d"].mean()) if valid.any() else None
    r5v = latest["return_5d"].dropna()
    r5 = float(r5v.mean()) if not r5v.empty else None
    breadth = float((latest.loc[valid, "return_1d"] > 0).mean()) if valid.any() else None
    amount = None
    mean20 = None
    ratio = None
    if "amount" in frame.columns:
        amounts = pd.to_numeric(frame.loc[frame["date"] == latest_date, "amount"], errors="coerce").dropna()
        amount = float(amounts.sum()) if not amounts.empty else None
        expected = len(set(symbols)) if symbols is not None else frame.symbol.nunique()
        daily = frame.groupby("date")["amount"].sum(min_count=expected).sort_index()
        prior = daily[daily.index < latest_date].tail(20)
        mean20 = float(prior.mean()) if len(prior) >= 20 and prior.notna().all() else None
        ratio = amount / mean20 if amount is not None and mean20 not in (None, 0) else None
    return SectorSnapshot(sector_id, latest_date, r1, r5, breadth, amount, mean20, ratio, quality)


def s6_daily_comparisons(sector_bars: pd.DataFrame, benchmark_bars: pd.DataFrame,
                         *, days: int = 5, trading_days: list[date] | None = None,
                         expected_constituents: list[str] | None = None) -> MarketDataResult:
    """Count aligned trading days on which sector return beats benchmark return."""
    try:
        frame = _returns(align_bars(sector_bars, symbols=expected_constituents, trading_days=trading_days))
        daily = frame.groupby("date")["return_1d"]
        s = daily.mean()
        expected = len(set(expected_constituents)) if expected_constituents is not None else frame.symbol.nunique()
        s = s.where(daily.count() == expected)
        b = _returns(align_bars(benchmark_bars, trading_days=trading_days)).groupby("date")["return_1d"].mean()
        joined = pd.concat([s.rename("sector"), b.rename("benchmark")], axis=1).sort_index().tail(days)
    except Exception as exc:
        return MarketDataResult(None, DataStatus.DATA_ERROR, detail=str(exc))
    if len(joined) < days or joined.isna().any().any():
        return MarketDataResult(None, DataStatus.DATA_INCONSISTENT, detail=f"only {len(joined)}/{days} aligned days")
    return MarketDataResult(int((joined["sector"] > joined["benchmark"]).sum()), DataStatus.VALID,
                            joined.index[-1])


def s7_strong_ratio(bars: pd.DataFrame, *, threshold: float = 0.05,
                    expected_constituents: list[str] | None = None,
                    trading_days: list[date] | None = None) -> MarketDataResult:
    """Latest-day ratio of expected constituents whose daily return meets threshold."""
    try:
        frame = _returns(align_bars(bars, symbols=expected_constituents, trading_days=trading_days))
    except Exception as exc:
        return MarketDataResult(None, DataStatus.DATA_ERROR, detail=str(exc))
    if frame.empty:
        return MarketDataResult(None, DataStatus.DATA_ERROR, detail="no bars")
    day = max(frame["date"])
    latest_frame = frame[frame["date"] == day]
    expected_symbols = set(expected_constituents or latest_frame["symbol"].unique())
    latest = latest_frame[latest_frame["symbol"].isin(expected_symbols)]["return_1d"].dropna()
    if latest.empty:
        return MarketDataResult(None, DataStatus.DATA_ERROR, day, "no valid constituent returns")
    expected = len(expected_symbols)
    status = DataStatus.VALID if len(latest) == expected else DataStatus.DATA_INCONSISTENT
    detail = None if len(latest) == expected else f"valid {len(latest)}/{expected} expected constituents"
    return MarketDataResult(float((latest >= threshold).sum() / expected), status, day, detail)


def fetch_aligned(source: MarketDataSource, symbols: list[str], *, start: date | None = None,
                  end: date | None = None, max_stale_days: int = 3,
                  trading_days: set[date] | None = None) -> MarketDataResult:
    """Fetch bars through an injected source and mark stale observations honestly."""
    try:
        bars = align_bars(source.get_bars(symbols, start, end), symbols=symbols, start=start, end=end)
    except Exception as exc:
        return MarketDataResult(None, DataStatus.DATA_ERROR, detail=str(exc))
    if bars.empty:
        return MarketDataResult(bars, DataStatus.DATA_ERROR, detail="no bars")
    as_of = max(bars["date"])
    if end is None:
        return MarketDataResult(bars, DataStatus.VALID, as_of)
    if trading_days is not None:
        eligible = sorted(day for day in trading_days if day <= end)
        stale = not eligible or as_of < eligible[-1]
    else:
        # Compatibility fallback uses business-day distance, never calendar-day distance.
        # Production callers should pass the authoritative exchange calendar.
        observed = pd.Timestamp(as_of)
        target = pd.Timestamp(end)
        trading_gap = max(0, len(pd.bdate_range(observed, target)) - 1)
        stale = trading_gap > max_stale_days
    return MarketDataResult(bars, DataStatus.DATA_STALE if stale else DataStatus.VALID, as_of,
                            "latest observation is before latest expected trading day" if stale else None)
