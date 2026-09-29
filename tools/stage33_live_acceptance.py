"""Stage 3A.3 live BaoStock acceptance evidence generator.

This script never fabricates missing observations: failed provider calls and incomplete
coverage are written as explicit status rows and the final report remains PARTIAL.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from app.sector.providers import BaoStockIndustryProvider, canonical_symbol
from app.sector.market_data import sector_snapshot, s6_daily_comparisons, s7_strong_ratio
from app.data.baostock_provider import BaoStockProvider
from app.data.models import ProviderError

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "stage33"
OUT.mkdir(parents=True, exist_ok=True)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def safe_csv(frame, name):
    frame.to_csv(OUT / name, index=False, encoding="utf-8-sig")


def main():
    retrieved_at = now_utc()
    evidence = {"retrieved_at": retrieved_at, "provider": "baostock"}
    try:
        import baostock
        industry = BaoStockIndustryProvider(client=baostock)._query()
    except Exception as exc:
        evidence.update({"status": "DATA_ERROR", "error": f"{type(exc).__name__}: {exc}"})
        (OUT / "industry_snapshot.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        raise

    industry = industry.copy()
    industry["industry"] = industry["industry"].fillna("").astype(str).str.strip()
    industry["code"] = industry["code"].astype(str)
    valid = industry[industry["industry"].ne("")].copy()
    canonical, invalid = [], []
    for code in valid["code"]:
        try:
            canonical.append(canonical_symbol(code))
        except Exception:
            canonical.append(None); invalid.append(code)
    valid["symbol"] = canonical
    valid = valid[valid["symbol"].notna()].copy()
    valid["exchange"] = valid["symbol"].str[-2:]
    dup = int(valid.duplicated(["industry", "symbol"]).sum())
    groups = valid.groupby("industry")["symbol"].agg(lambda x: sorted(set(x)))
    sizes = groups.map(len).sort_values()
    # Select genuinely different sizes, preferring broad coverage and >= 50 names.
    small = next(((n, s) for n, s in sizes.items() if 5 <= s <= 15), (sizes.index[0], sizes.iloc[0]))
    medium = next(((n, s) for n, s in sizes.items() if 16 <= s <= 40), (sizes.index[len(sizes)//2], sizes.iloc[len(sizes)//2]))
    large = next(((n, s) for n, s in sizes.items() if s >= 41), (sizes.index[-1], sizes.iloc[-1]))
    selected = [("small", small[0], small[1]), ("medium", medium[0], medium[1]), ("large", large[0], large[1])]
    selected_rows = []
    for bucket, name, count in selected:
        for symbol in groups[name]: selected_rows.append({"bucket": bucket, "sector_id": name, "expected_count": count, "symbol": symbol})
    selected_df = pd.DataFrame(selected_rows)
    safe_csv(pd.DataFrame([{
        "retrieved_at": retrieved_at, "updateDate_min": industry.get("updateDate", pd.Series(dtype=str)).min(),
        "updateDate_max": industry.get("updateDate", pd.Series(dtype=str)).max(), "industry_count": int(valid["industry"].nunique()),
        "total_rows": int(len(industry)), "valid_industry_rows": int(len(valid)),
        "missing_industry_rows": int(len(industry) - len(valid)), "unique_symbols": int(valid["symbol"].nunique()),
        "SH": int((valid.exchange == "SH").sum()), "SZ": int((valid.exchange == "SZ").sum()),
        "BJ": int((valid.exchange == "BJ").sum()), "invalid_symbol_count": len(invalid), "duplicate_count": dup,
        "status": "VALID" if not invalid and not dup else "DATA_INCONSISTENT"
    }]), "industry_snapshot.csv")
    safe_csv(selected_df, "selected_industries.csv")

    end = date.today(); start = end - timedelta(days=120)
    provider = BaoStockProvider(timeout=45)
    bars_by_symbol, quality = {}, []
    for symbol in sorted(selected_df.symbol.unique()):
        row = {"symbol": symbol, "provider": "baostock", "requested_start": start, "requested_end": end}
        try:
            bars = provider.fetch_stock_daily(symbol, start, end, adjustment="raw")
            bars = bars.copy(); bars["symbol"] = symbol
            bars_by_symbol[symbol] = bars
            dates = pd.to_datetime(bars["date"], errors="coerce").dt.date
            row.update({"latest_trade_date": max(dates) if len(dates) else None, "bar_count": len(bars), "status": "VALID" if len(bars) >= 35 else "DATA_INCONSISTENT", "failure_reason": None if len(bars) >= 35 else "less_than_35_bars"})
        except Exception as exc:
            row.update({"latest_trade_date": None, "bar_count": 0, "status": "DATA_ERROR", "failure_reason": f"{type(exc).__name__}: {exc}"})
        quality.append(row)
    quality_df = pd.DataFrame(quality); safe_csv(quality_df, "bar_quality.csv")
    allbars = pd.concat(bars_by_symbol.values(), ignore_index=True) if bars_by_symbol else pd.DataFrame()
    benchmark = None
    try: benchmark = provider.fetch_benchmark(start, end)
    except Exception: pass

    metrics = {k: [] for k in ("s1_inputs.csv", "s2_inputs.csv", "s3_inputs.csv", "s5_inputs.csv", "s6_inputs.csv", "s7_inputs.csv")}
    for bucket, sector, expected in selected:
        syms = groups[sector]
        frame = allbars[allbars.symbol.isin(syms)].copy() if not allbars.empty else pd.DataFrame()
        snap = sector_snapshot(sector, frame, symbols=syms)
        base = {"bucket": bucket, "sector_id": sector, "expected_constituents": expected, "as_of": snap.as_of, "status": snap.quality.status.value, "detail": snap.quality.detail}
        metrics["s1_inputs.csv"].append({**base, "return_1d": snap.return_1d})
        metrics["s2_inputs.csv"].append({**base, "return_5d": snap.return_5d})
        metrics["s3_inputs.csv"].append({**base, "breadth": snap.breadth})
        metrics["s5_inputs.csv"].append({**base, "amount": snap.amount, "amount_20d_mean": snap.amount_20d_mean, "amount_20d_ratio": snap.amount_20d_ratio})
        s7 = s7_strong_ratio(frame, expected_constituents=syms)
        metrics["s7_inputs.csv"].append({**base, "strong_ratio": s7.value, "status": s7.status.value, "detail": s7.detail})
        if benchmark is not None:
            s6 = s6_daily_comparisons(frame, benchmark, days=5)
            metrics["s6_inputs.csv"].append({**base, "beats": s6.value, "status": s6.status.value, "detail": s6.detail})
        else:
            metrics["s6_inputs.csv"].append({**base, "beats": None, "status": "DATA_ERROR", "detail": "benchmark_fetch_failed"})
    for name, rows in metrics.items(): safe_csv(pd.DataFrame(rows), name)

    # S4 is intentionally evidence-only until a provider supplies auditable limit prices.
    s4 = []
    for symbol in sorted(selected_df.symbol.unique()):
        s4.append({"symbol": symbol, "exchange": symbol[-2:], "board": "UNKNOWN", "preclose": None, "isST": None, "listing_date": None, "limit_up_price": None, "limit_down_price": None, "source": "baostock_history", "status": "DATA_ERROR", "reason": "BaoStock history does not provide auditable limit prices/listing metadata for S4"})
    safe_csv(pd.DataFrame(s4), "s4_limit_validation.csv")
    evidence.update({"status": "PARTIAL", "industry_count": int(valid.industry.nunique()), "selected_symbol_count": int(len(selected_df)), "bar_valid_count": int((quality_df.status == "VALID").sum()), "s4_status": "DATA_ERROR"})
    (OUT / "run_metadata.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__": main()
