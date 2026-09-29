> 最新验收：2026-09-29 Stage 3A.5 Industry V1 (SH/SZ) = PASS。详见 [STAGE35_FINAL_ACCEPTANCE.md](STAGE35_FINAL_ACCEPTANCE.md)。以下保留Stage3A初始审计历史，不代表最新数据可用性。

# QuantScore Stage 3A Result

## Current Project Audit

Stage 0–2.6 remain complete per current repository state. `HEAD` and `origin/main` are both `e994a1c`; existing untracked Stage 2.6 evidence remains untouched. This work does not modify the single-stock analysis path, scoring weights, RuleEngine, ScoreEngine, ProviderManager, or public UI.

Stage 3A scope is limited to a sector data contract and rule audit. No ranking, SectorHeat score executor, automatic stock selection, or UI was added.

## Existing Sector Rules Audit

The SSOT is `docs/SPEC_EXTRACTED.txt`, cross-checked against `docs/RULE_IMPLEMENTATION_MATRIX.md` and `docs/RULE_AMBIGUITIES.md`.

| Rule | Existing semantic | Required data | Availability | Feasibility | Semantic gap / next action |
|---|---|---|---|---|---|
| S1 | 1-day sector excess return; coverage >=80%; >2%, 1–2%, 0.5–1%, 0–0.5% score 20/16/10/5 | sector_return_1d, benchmark_return_1d, constituents | UNAVAILABLE online | DERIVABLE after source | Need operational sector aggregation/index choice |
| S2 | 5-day sector excess return; score 20/16/12/6 by >6/4–6/2–4/0–2% | sector_return_5d, benchmark_return_5d | UNAVAILABLE online | DERIVABLE after source | Need exact return/holiday alignment |
| S3 | advancing constituents / valid constituents; >=10 and >=80% coverage | component daily returns | UNAVAILABLE online | DERIVABLE | Need invalid/停牌 handling confirmation |
| S4 | limit-up count and ratio; >=5 plus >=5% ratio, or count 3/2/1 | close_raw, limit_up_price, constituents | UNAVAILABLE / unreliable via current network | DERIVABLE only with reliable limits | Must not treat near-limit as limit-up; preserve UNKNOWN |
| S5 | today sector amount / prior 20-day mean; >=1.8/1.4/1.15/0.9 | amount, 20 prior trading days | UNAVAILABLE online | DERIVABLE | Need sector amount aggregation and point-in-time constituents |
| S6 | number of five days sector beats benchmark, daily comparison | daily sector and benchmark returns | UNAVAILABLE online | DERIVABLE | Must align each trading day; no cumulative substitute |
| S7 | constituents with daily return >=5% / valid constituents | component daily returns | UNAVAILABLE online | DERIVABLE | Need sample and suspension rules |
| B1 | read final SectorHeatScore; >=85/75/70/60/50 mapping to 8/7/6/4/2 | final SectorHeatScore + stock-sector mapping | UNAVAILABLE | BLOCKED by S1–S7 and mapping | Multi-sector policy is not specified |
| B2 | stock 5-day return minus sector 5-day return; >8/4–8/1–4/0–1% mapping | stock and sector returns | stock available; sector unavailable | BLOCKED | Need multi-sector selection policy and exact point-in-time membership |

All S1–S7, B1 and B2 remain `NOT_IMPLEMENTED / NOT_TESTED` in the existing matrix. B3 remains implemented, but its full constituent data dependency is not available in the current system.

## Sector Data Source

Primary adapter implemented for AKShare Eastmoney board APIs:

- Industry list: `stock_board_industry_name_em`
- Industry constituents: `stock_board_industry_cons_em`
- Concept list: `stock_board_concept_name_em`
- Concept constituents: `stock_board_concept_cons_em`

No token is normally required. However, the current environment smoke test failed with `ProxyError`; therefore this source is an adapter, not a verified live source. Cloud reachability must be separately verified before claiming production availability.

Alternatives audited:

- BaoStock `query_stock_industry`: free industry affiliation fallback, but not concept boards and no reliable historical membership snapshot.
- Tushare `index_classify` / `index_member`: richer membership and validity metadata, but requires a token and is not a default dependency.

## Sector Data Contract

Added:

- `app/sector/contract.py`
  - `SectorRecord`
  - `ConstituentRecord`
  - `FieldStatus`
  - `Provenance`
  - deterministic cache keys
  - sector-to-stock mapping validation
- `app/sector/providers.py`
  - injectable `SectorProvider`
  - `AKShareSectorProvider`
  - industry/concept separation via `level`
  - honest `ProviderError` propagation
- `app/sector/__init__.py`

The contract records `sector_id`, `name`, `sector_type/level`, canonical stock symbols, optional weights, as-of date, field status, and provenance. It intentionally contains no SectorHeat scoring logic.

## Real Sector Smoke Test

Attempted real industry list retrieval through the AKShare adapter. Result:

```text
UNAVAILABLE: AKShare stock_board_industry_name_em 失败：ProxyError
```

Consequently, this run cannot claim the required three-sector / ten-constituent live smoke test. No mock data was promoted as real data.

## Stock-to-Sector Mapping

Contract-level mapping validation is implemented and tested. Live stock-to-sector mapping is currently unavailable because the real sector list endpoint is unreachable.

## Sector-to-Stock Mapping

Contract-level constituent records and validation are implemented. Live sector-to-stock mapping is currently unavailable for the same network reason.

## Field Availability Matrix

| Field | Status | Notes |
|---|---|---|
| sector_id | DERIVABLE | AKShare board code when endpoint works |
| sector_name | DERIVABLE | AKShare board name |
| sector_type | AVAILABLE in contract | `industry` and `concept` are kept separate |
| trade_date | UNAVAILABLE in metadata adapter | Must be attached by a historical market-data service |
| constituent_count | DERIVABLE | Count validated constituent records |
| constituent_symbols | DERIVABLE | Canonical `######.SH/SZ/BJ` validation |
| close | AVAILABLE from BaoStock for individual stocks | Batch sector retrieval not implemented |
| return_1d / return_5d | DERIVABLE | Requires aligned constituent history |
| amount | AVAILABLE for individual stock bars | Sector aggregation not implemented |
| turnover | AVAILABLE/partial in existing stock pipeline | Coverage must be checked per constituent |
| limit_up_status | UNRELIABLE currently | Requires reliable historical limit prices |
| relative_strength | DERIVABLE | Depends on sector and benchmark returns |
| breadth | DERIVABLE | Depends on valid constituent daily returns |
| provenance | AVAILABLE in contract | Provider, request, source and retrieval time |

## B1 / B2 Feasibility

B1 is blocked until a frozen SectorHeat result and an explicit multiple-sector membership policy exist. The SSOT says to reuse final SectorHeat and not re-add S1–S7, but does not specify which sector to use when a stock belongs to multiple sectors.

B2 formula and thresholds are frozen in the SSOT, but live execution is blocked by sector return availability and the same multiple-sector policy. Missing sector return must remain UNKNOWN.

## Semantic Gaps

1. Industry versus concept is not selected as the sole active SectorHeat taxonomy.
2. Multi-sector stocks: MAX, AVG, primary sector, or another policy is not frozen.
3. Point-in-time membership and effective dates are not defined for historical evaluation.
4. Sector return aggregation choice (equal-weight, provider index, or other) is not frozen.
5. Suspended/invalid constituents and constituent inclusion/exclusion handling need explicit rules.
6. S4 limit-price reliability and treatment of special boards need confirmation.
7. `trade_date` and stale-data policy for sector metadata need contract-level freezing.
8. Coverage denominator and deduplication policy across provider responses need confirmation.

## Tests

New contract tests:

```text
3 passed
```

Full regression after the Stage 3A contract additions:

```text
440 passed, 1 skipped, 1 warning
0 failed
```

They cover canonical symbol validation, mapping validation, field status, injected AKShare normalization, and honest provider error propagation. Existing Stage 0–2.6 tests remain green.

## Files Added / Updated

Added:

- `app/sector/__init__.py`
- `app/sector/contract.py`
- `app/sector/providers.py`
- `tests/test_sector_contract.py`
- `docs/STAGE3A_RESULT.md`

Existing Stage 2.6 untracked evidence files were not modified.

## User Decisions Required

Please confirm before Stage 3B:

1. Active taxonomy: industry, concept, or separate tracks?
2. Multi-sector stock policy for B1/B2: primary, MAX, AVG, or another explicit rule?
3. Sector return aggregation: equal-weight constituents or an authoritative provider index?
4. Historical membership policy: current membership only, or point-in-time effective membership?
5. S4 handling for missing/unreliable historical limit prices and special boards?
6. Stale-data and minimum coverage thresholds beyond those already in S1–S7?

## Remaining Issues

The data contract and adapter are ready, but live sector data is not currently reachable due to the environment's AKShare `ProxyError`. No reliable public sector source was verified end-to-end in this run. SectorHeat execution and B1/B2 remain intentionally unimplemented.

## Status

**PARTIAL / NEEDS_USER_DECISION**

The contract and audit are complete, but Stage 3A cannot be marked PASS because a real sector list, constituents, and mapping smoke test could not be completed. No Stage 3B work was started.
