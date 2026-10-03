# Stage 3C SSOT Audit / Rule Freeze

## CURRENT / ACTIVE — USER_CONFIRMED 2026-10-02

本文件是Stage 3C新增候选产品语义的SSOT，与V1.4评分规范共同使用。
不修改历史Word、评分规则、权重或规则各自的Coverage前置。

| Item | Frozen active semantics |
|---|---|
| Industry gate | Same-date scoreable VALID SectorHeat >=70 |
| Sector limit | None: all eligible industries; Top5/TopN only future DISPLAY_LIMIT |
| Stock gate | Existing full QuantScore >=80 |
| Global Coverage gate | NONE; never add 80% or 100%; preserve existing per-rule prerequisites |
| Risk | Existing Risk=HIGH => NOT_MATCHED; LOW/MEDIUM do not independently block |
| MATCHED | Valid Heat>=70 AND legally generated QuantScore>=80 AND non-HIGH Risk AND no critical DATA_ERROR/STALE/INCONSISTENT |
| NOT_MATCHED | Reliable data, business gates not satisfied |
| NOT_EVALUABLE | Data quality prevents reliable candidate evaluation, never converted to zero/NOT_MATCHED |
| NOT_IMPLEMENTED | Existing ScoreEngine behavior only; no new penalty/normalization |
| Output order | QuantScore descending, SectorHeat descending, symbol ascending; ENGINEERING_DISPLAY_ORDER only |
| Full history minimum | Existing SECTOR.history_min=120 trading bars; short histories recorded DATA_INCOMPLETE |
| Old AutoScreenScore | SUPERSEDED / NOT USED in Stage 3C |

Machine configuration: config/screening.yaml. No unresolved Stage 3C candidate
semantics remain. No “buy line”, predictions, or recommendations are emitted.

## HISTORICAL — Initial audit gaps, resolved by user confirmation above

Base: c87fa9afec354b65ebf917d49f418c559c321e2b. Scoring SSOT V1.4;
assumption_version v1.3. No existing scoring definition is changed.

| Item | Current evidence | Resolution |
|---|---|---|
| SectorHeat gate | SPEC_V1_4_EXTRACTED.txt:230; parameters.yaml SECTOR.hot_threshold=70 | ACTIVE: complete VALID Heat >=70 |
| Full stock scoring | User Stage 3C request | Existing StockAnalysisService, RuleEngine and ScoreEngine only |
| History | SECTOR.history_min=120; inherited section 8.2 | Use existing configured minimum, never fill missing bars |
| QuantScore MATCHED threshold | No candidate threshold found; R7's 80 is a forward-signal prerequisite, not screening eligibility | SEMANTIC_GAP |
| Coverage used for MATCHED | SECTOR.auto_coverage_min=.8 exists, but AutoCoverage and its denominator are not implemented/frozen for full QuantScore screening | SEMANTIC_GAP |
| HIGH risk exclusion | Inherited 8.2 distinguishes high-risk candidate area and main ranking, not binary MATCHED eligibility | SEMANTIC_GAP |
| Top5 / all eligible sectors | SECTOR.top_n=5 and inherited 8.2; user requires current-active audit; inherited 8.2 is marked HISTORICAL / SUPERSEDED_BY_V1_3 | SEMANTIC_GAP |
| AutoScreenScore vs QuantScore | Old normalized AutoScreenScore differs from the requested full QuantScore; no active mapping between these eligibility measures | SEMANTIC_GAP |
| Output order | User permits ENGINEERING_DISPLAY_ORDER | QuantScore descending, symbol ascending; does not affect eligibility |
| Universe | User Stage 3C: SH/SZ primary industries; provider metadata type=1 | BJ, index, ETF/funds/non-stock excluded; unverified metadata remains a recorded data error |

Historical initial safeguard: until user semantics were frozen, no production stock could become MATCHED.
The default policy has no stock threshold, Coverage mapping, risk exclusion or
business sector cap. It emits NOT_EVALUABLE / SEMANTIC_GAP. A full-market sector
audit may still run, but stock eligibility and production screening cannot be
accepted as PASS. No invented AutoScore or second scoring engine is added.

Operational --limit-industries selects a deterministic subset for smoke tests;
it is explicitly not a business Top N. All evaluated sectors and excluded
members remain in evidence; data errors never become low numerical scores.
