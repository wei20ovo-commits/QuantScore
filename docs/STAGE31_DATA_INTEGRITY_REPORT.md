# QuantScore Stage 3A.1 High-Integrity Data Result

## Current Audit

Stage 3A.1 extends the Stage 3A contract without entering SectorHeat scoring, automatic selection, ranking, UI, or ScoreEngine integration. Existing Stage 0–2.6 behavior is unchanged.

## Data Integrity Principles

The pipeline distinguishes `VALID`, `DATA_ERROR`, `DATA_STALE`, `DATA_INCONSISTENT`, `NOT_APPLICABLE`, and `UNKNOWN`. Provider/network failures are not converted into business UNKNOWN. Missing fields, stale dates, and inconsistent sources remain explicit data-quality outcomes.

## Active Industry Provider

**BaoStockIndustryProvider** is now implemented as a real current-industry affiliation provider using BaoStock `query_stock_industry`.

Verified real response fields:

```text
updateDate, code, code_name, industry, industryClassification
```

The provider records `provider`, `source`, request context and retrieval time in provenance. Empty industry values are not silently assigned.

## Fallback Provider

`AKShareSectorProvider` remains the intended industry/concept board adapter. It is not currently verified online because `stock_board_industry_name_em` returned `ProxyError`.

BaoStock does not provide concept boards or reliable point-in-time membership history, so it is a valid current-industry fallback, not a complete historical SectorHeat source.

Tushare remains optional only because its classification/member interfaces require a token.

## AKShare Verification

Result:

```text
DATA_ERROR: AKShare stock_board_industry_name_em 失败：ProxyError
```

No mock data was substituted.

## BaoStock Industry Verification

Real BaoStock smoke succeeded:

- non-empty industry groups: **83**
- first groups: `A01农业`, `A02林业`, `A03畜牧业`
- first three groups constituent retrieval: **28 records / 28 unique symbols**
- observed update date: **2026-09-21**
- source: BaoStock `query_stock_industry`

This is below the requested 30-stock target for the selected first three small groups, so the smoke is successful but not sufficient for a full Stage 3A.1 PASS. It is a real result, not mock data.

## Real Industry Smoke Test

The real BaoStock path completed industry list and industry-to-constituent retrieval. The sample proves 83 groups and 28 unique canonical symbols across the first three groups. A larger group selection is required to reach the requested 30-stock verification target.

The AKShare path remains DATA_ERROR due to the environment proxy.

## Stock ↔ Industry Mapping

Implemented through BaoStock rows and `ConstituentRecord` creation. Missing industry rows are excluded from formal industry groups and remain observable in quality statistics. No random industry is assigned.

## SH / SZ / BJ Verification

Canonical normalization supports:

- `SH` → `######.SH`
- `SZ` → `######.SZ`
- `BJ` → `######.BJ`

Tests cover representative Shanghai, Shenzhen and Beijing symbols, including `830001.BJ`. Invalid symbols are rejected. Provider-native code and canonical symbol remain traceable through provenance.

## Market Data Alignment

`SectorAggregate` accepts an explicit `as_of` and provenance. Deterministic aggregation sorts by canonical symbol and removes duplicate symbols before computing values. Full cross-source trade-date alignment for sector history is not yet complete because the current BaoStock industry endpoint is an affiliation snapshot rather than a historical membership/bar endpoint.

## Limit-Up Data Solution

No new approximate limit-up implementation was introduced. The pipeline does not use `return >= 9.8%` or a near-limit proxy as a real limit-up result. Reliable historical `limit_up_price` remains required for S4; absent or unreliable limit prices must remain a data-quality failure/UNKNOWN boundary rather than a guessed value.

## S1–S7 Input Availability

| Input | Current status | Notes |
|---|---|---|
| sector_return_1d | DERIVABLE | `aggregate_industry` accepts constituent returns |
| benchmark_return_1d | AVAILABLE in existing stock/index pipeline | Must align `as_of` |
| sector_return_5d | DERIVABLE | Requires aligned constituent history |
| breadth | DERIVABLE | Deterministic from valid `return_1d` rows |
| sector amount | DERIVABLE | Sums valid amount rows; coverage must be reviewed |
| daily win days | NOT_READY | Requires five aligned sector history days |
| reliable limit-up count | DATA_ERROR/UNRELIABLE | No approximate substitute |
| S7 strong ratio | DERIVABLE | Requires complete daily constituent returns |

No SectorHeat score is calculated or injected into QuantScore.

## Cross-Source Verification

AKShare and BaoStock industry classification were not both available for the same live snapshot: AKShare failed with ProxyError, while BaoStock succeeded. Consequently, no silent source selection or match claim is made. Tushare was not called because no token was provided.

## Data Quality Statistics

Real BaoStock smoke statistics:

```text
sector_count: 83
constituent_count (first 3 groups): 28
unique_symbol_count: 28
mapping_success_count: 28
mapping_failure_count: 0 in returned sample
latest industry updateDate: 2026-09-21
AKShare status: DATA_ERROR (ProxyError)
```

Full-market bar fetch, limit-price success/failure counts, stale count and inconsistent count are not claimed because this stage did not fetch full constituent histories.

## Cache / Freshness

Date-sensitive deterministic cache keys are implemented in the sector contract. Provenance retains retrieval time and as-of information. A formal provider cache-fallback policy remains to be added before production SectorHeat use; stale cached data must never be labeled as current.

## Tests

Targeted contract/integrity tests:

```text
12 passed
```

Full regression:

```text
449 passed, 1 skipped, 1 warning
0 failed
```

## Files Added / Updated

- `app/sector/contract.py`
- `app/sector/providers.py`
- `app/sector/__init__.py`
- `tests/test_sector_contract.py`
- `tests/test_stage31_sector_integrity.py`
- `docs/STAGE31_DATA_INTEGRITY_REPORT.md`

No RuleEngine, ScoreEngine, scoring rule, UI or deployment file was changed.

## Unresolved Data Problems

1. AKShare remains blocked by ProxyError in the current environment.
2. BaoStock industry data is current affiliation only, not point-in-time historical membership.
3. The first-three-group smoke produced 28 rather than the requested 30 constituents; a larger real group sample is still needed.
4. Full constituent historical bars, date alignment, amount coverage and S4 limit-price cross-validation are not complete.
5. Industry/concept taxonomy and multi-sector policy were previously identified as decisions; Stage 3 V1 should use industry only as frozen by the user request.
6. A formal validated cache fallback and retry/secondary-provider orchestration is not yet production complete.

## Status

**PARTIAL**

BaoStock now provides a real verified industry affiliation path, canonical mapping, provenance, deterministic aggregation primitives and passing regression tests. However, AKShare is unavailable, the live smoke is below the 30-stock target, historical sector bars and reliable limit-up cross-validation are incomplete, and no full multi-source sector data pipeline is yet proven. Stage 3B is not started.
