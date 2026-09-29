import pandas as pd
import pytest
from datetime import date, datetime, timezone

from app.sector import (
    AKShareSectorProvider,
    ConstituentRecord,
    FieldStatus,
    Provenance,
    SectorRecord,
    cache_key,
    validate_mapping,
    canonical_symbol,
    quality_stats,
    DataStatus,
)


def test_canonical_symbol_uses_explicit_code_rules_when_market_missing():
    cases = {
        "600000": "600000.SH", "688001": "688001.SH", "000001": "000001.SZ",
        "300750": "300750.SZ",
    }
    for raw, expected in cases.items():
        assert canonical_symbol(raw) == expected
    with pytest.raises(ValueError):
        canonical_symbol("123456")
    # Historical 4/8/92 prefixes are not sufficient evidence of a current BJ listing.
    for raw in ("830001", "870001", "920001"):
        with pytest.raises(ValueError):
            canonical_symbol(raw)
    assert canonical_symbol("830001.BJ") == "830001.BJ"


def test_quality_stats_marks_missing_and_stale_with_complete_counts():
    stats = quality_stats([1.0, None], expected=3)
    assert (stats.total, stats.valid, stats.missing, stats.coverage) == (3, 1, 2, 1 / 3)
    assert stats.status == DataStatus.DATA_ERROR
    stale = quality_stats([1.0, None], expected=3, stale=True)
    assert stale.status == DataStatus.DATA_STALE


def test_sector_records_preserve_as_of_status_and_provenance():
    retrieved = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
    provenance = Provenance("fixture", retrieved, "fixture://sector", {"as_of": "2026-01-01"})
    sector = SectorRecord("BK001", "测试行业", as_of=date(2026, 1, 1), provenance=provenance)
    constituent = ConstituentRecord("830001.BJ", sector_id="BK001", as_of=date(2026, 1, 1), provenance=provenance)

    assert sector.as_of == date(2026, 1, 1)
    assert constituent.as_of == date(2026, 1, 1)
    assert sector.field_status["sector_id"] == FieldStatus.PRESENT
    assert constituent.field_status["weight"] == FieldStatus.MISSING
    assert sector.provenance.as_dict()["retrieved_at"].endswith("+00:00")
    validate_mapping([sector], [constituent])


def test_cache_keys_are_deterministic_and_date_sensitive():
    first = cache_key("constituents", sector_id="BK001", as_of=date(2026, 1, 1))
    second = cache_key("constituents", sector_id="BK001", as_of=date(2026, 1, 1))
    next_day = cache_key("constituents", sector_id="BK001", as_of=date(2026, 1, 2))
    assert first == second
    assert first != next_day
    assert first == ("sector-data", "constituents", "BK001", "2026-01-01")


def test_mapping_rejects_unknown_sector_without_fallback_or_silent_aggregation():
    sector = SectorRecord("BK001", "测试行业")
    orphan = ConstituentRecord("600000.SH", sector_id="UNKNOWN")
    with pytest.raises(ValueError, match="未知 sector_id"):
        validate_mapping([sector], [orphan])
