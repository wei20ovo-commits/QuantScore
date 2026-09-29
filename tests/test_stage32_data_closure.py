"""Stage 3A.2 数据闭合的离线边界回归，不访问真实行情服务。"""
from datetime import date

import pandas as pd
import pytest

from app.data.cache import CacheKey, DataCache
from app.data.models import ProviderError
from app.sector import AKShareSectorProvider, cache_key
from app.sector.providers import DataStatus, aggregate_industry
from app.sector.market_data import fetch_aligned, s6_daily_comparisons, sector_snapshot


@pytest.mark.parametrize("operation", ["list_sectors", "list_constituents"])
def test_provider_failure_preserves_cause_instead_of_returning_empty_data(operation):
    class Client:
        def stock_board_industry_name_em(self):
            raise TimeoutError("fixture offline")

        def stock_board_industry_cons_em(self, symbol):
            raise TimeoutError("fixture offline")

    provider = AKShareSectorProvider(Client())
    args = ("BK001",) if operation == "list_constituents" else ()
    with pytest.raises(ProviderError) as caught:
        getattr(provider, operation)(*args)
    assert isinstance(caught.value.__cause__, TimeoutError)


@pytest.mark.parametrize("operation", ["list_sectors", "list_constituents"])
def test_malformed_provider_response_is_not_valid_empty_data(operation):
    class Client:
        def stock_board_industry_name_em(self):
            return pd.DataFrame({"unexpected": [1]})

        def stock_board_industry_cons_em(self, symbol):
            return pd.DataFrame({"unexpected": [1]})

    provider = AKShareSectorProvider(Client())
    args = ("BK001",) if operation == "list_constituents" else ()
    with pytest.raises(ValueError, match="字段缺失"):
        getattr(provider, operation)(*args)


def test_empty_provider_response_does_not_fabricate_sector_members():
    class Client:
        def stock_board_industry_cons_em(self, symbol):
            return pd.DataFrame(columns=["代码", "名称"])

    assert AKShareSectorProvider(Client()).list_constituents("BK001") == []


def test_sector_cache_key_isolates_kind_sector_and_business_date():
    keys = {
        cache_key("constituents", sector_id="BK001", as_of=date(2026, 9, 21)),
        cache_key("constituents", sector_id="BK001", as_of=date(2026, 9, 22)),
        cache_key("constituents", sector_id="BK002", as_of=date(2026, 9, 21)),
        cache_key("bars", sector_id="BK001", as_of=date(2026, 9, 21)),
    }
    assert len(keys) == 4


def test_market_cache_expiry_boundary_and_force_refresh_do_not_leak_stale_data(tmp_path):
    now = [100.0]
    cache = DataCache(tmp_path / "closure.sqlite3", ttl=10, clock=lambda: now[0])
    key = CacheKey("fixture", "600000.SH", "2026-09-01", "2026-09-21", "raw")
    cache.put(key, pd.DataFrame({"close": [10.0]}))
    now[0] = 109.999
    assert cache.get(key).attrs["cache_hit"] is True
    assert cache.get(key, force_refresh=True) is None
    now[0] = 110.0
    assert cache.get(key) is None


def test_market_cache_isolates_source_date_adjustment_and_returned_objects(tmp_path):
    cache = DataCache(tmp_path / "closure.sqlite3")
    key = CacheKey("fixture", "600000.SH", "2026-09-01", "2026-09-21", "raw")
    cache.put(key, pd.DataFrame({"close": [10.0]}))
    for other in (
        CacheKey("other", "600000.SH", "2026-09-01", "2026-09-21", "raw"),
        CacheKey("fixture", "600000.SH", "2026-09-01", "2026-09-22", "raw"),
        CacheKey("fixture", "600000.SH", "2026-09-01", "2026-09-21", "qfq"),
    ):
        assert cache.get(other) is None
    cached = cache.get(key)
    cached.loc[0, "close"] = 999.0
    assert cache.get(key).loc[0, "close"] == 10.0


def _bars(symbol="600000.SH", periods=7):
    return pd.DataFrame({
        "symbol": [symbol] * periods,
        "date": pd.bdate_range("2026-09-01", periods=periods),
        "close": [100.0 + i for i in range(periods)],
        "amount": [1000.0] * periods,
    })


def test_fetch_failure_is_data_error_not_business_unknown():
    class Source:
        def get_bars(self, symbols, start, end):
            raise TimeoutError("fixture offline")

    result = fetch_aligned(Source(), ["600000.SH"])
    assert result.status == DataStatus.DATA_ERROR
    assert result.value is None


def test_fetch_marks_old_observation_stale_without_changing_as_of():
    class Source:
        def get_bars(self, symbols, start, end):
            return _bars(periods=2)

    result = fetch_aligned(Source(), ["600000.SH"], end=date(2026, 9, 21))
    assert result.status == DataStatus.DATA_STALE
    assert result.as_of == date(2026, 9, 2)


def test_s6_rejects_nonoverlapping_business_dates():
    sector = _bars()
    benchmark = _bars("000001.SH")
    benchmark["date"] += pd.Timedelta(days=30)
    result = s6_daily_comparisons(sector, benchmark)
    assert result.status == DataStatus.DATA_INCONSISTENT
    assert result.value is None


def test_snapshot_does_not_label_missing_expected_member_valid():
    result = sector_snapshot("BK001", _bars(), symbols=["600000.SH", "000001.SZ"])
    assert result.quality.status != DataStatus.VALID


def test_snapshot_does_not_forward_fill_missing_current_close():
    bars = _bars()
    bars.loc[bars.index[-1], "close"] = float("nan")
    result = sector_snapshot("BK001", bars)
    assert result.return_1d is None
    assert result.quality.status != DataStatus.VALID


def test_snapshot_does_not_claim_twenty_day_mean_from_short_history():
    result = sector_snapshot("BK001", _bars())
    assert result.amount_20d_mean is None
    assert result.amount_20d_ratio is None


def test_complete_industry_aggregation_is_order_invariant_and_preserves_metadata():
    rows = pd.DataFrame([
        {"symbol": "600000.SH", "return_1d": 0.02, "return_5d": 0.10, "amount": 1000.0},
        {"symbol": "000001.SZ", "return_1d": -0.01, "return_5d": 0.04, "amount": 2000.0},
        {"symbol": "830001.BJ", "return_1d": 0.0, "return_5d": -0.02, "amount": 0.0},
    ])
    as_of = date(2026, 9, 21)
    provenance = {"provider": "fixture", "source": "injected-bars"}
    first = aggregate_industry("BK001", rows, as_of=as_of, provenance=provenance)
    second = aggregate_industry("BK001", rows.iloc[::-1], as_of=as_of, provenance=provenance)
    assert first == second
    assert first.return_1d == pytest.approx(0.01 / 3)
    assert first.return_5d == pytest.approx(0.04)
    assert first.breadth == pytest.approx(1 / 3)
    assert first.amount == 3000.0
    assert first.quality.status == DataStatus.VALID
    assert first.quality.coverage == 1.0
    assert first.as_of == as_of
    assert first.provenance == provenance


def test_industry_aggregation_missing_required_columns_has_no_fabricated_values():
    result = aggregate_industry("BK001", pd.DataFrame({"symbol": ["600000.SH"]}))
    assert result.quality.status == DataStatus.DATA_ERROR
    assert (result.return_1d, result.return_5d, result.breadth, result.amount) == (None,) * 4
