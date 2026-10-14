# QuantScore Stage 4 Final Engineering Result

Date: 2026-10-14. Published starting baseline: `8b57a7989612dd37727e8b1941bfacdb04477135`.

## Acceptance scope and status

| Area | Status | Evidence / limitation |
|---|---|---|
| Local engineering and regression | LOCAL_PASS | 1084 PASS / 0 FAIL / 0 ERROR / 1 existing SKIP |
| Same-input scoring semantics | LOCAL_PASS | Exact equality of 41 RuleResults, full score, Risk, B1/B2 industry context and candidate-policy result |
| Baseline public stock analysis | PUBLIC_PASS | Actual deployed SHA identified; two successful 600519 requests, second Web cache HIT |
| New release public verification | PENDING_RELEASE_VERIFICATION | Updated below after ordinary push and independent deployment check |
| Atomic daily publication implementation | LOCAL_PASS | Failure retention, generation pinning, corruption rejection and date-quality tests |
| Current daily market data / scheduled production | PARTIAL / EXTERNAL_BLOCKED | Calendar works; controlled real update failed at industry-provider initialization; no dedicated runner registered |
| Overall product closure | PARTIAL | A working stock request does not establish reliable daily industry updates |

No frozen scoring, Risk, B1/B2, candidate, Provider retry policy, cache TTL or 240-second Web cutoff was changed. No Stage 5, UI redesign or new investment strategy was started.

## Current audit and preserved work

Before edits, local HEAD and fetched origin/main both matched the starting baseline. Existing staged index was empty. Related unfinished publication/diagnostic work was completed rather than replaced. Other uncommitted reports, tools and historical Stage26 files were retained and excluded from this release. Existing README edits are preserved; only this release's appended operations section is selected for publication.

`outputs/final_engineering/initial_integrity.json` records initial file hashes; `security_and_gate.json` checks unrelated-file preservation and the frozen core/config inventory. The only changed file in that core inventory is `app/screening/batch_provider.py`, for process-resource cleanup, not scoring or data validation.

## Proven defects and fixes

1. **Startup cleanup can mask the original exception.** Injecting process-start rejection reproduced `PermissionError` followed by `AssertionError` when cleanup attempted to join an unstarted process. Pipe/temp resources also remained owned. Cleanup now checks whether a process actually started, releases both pipe endpoints and temporary storage, and preserves the original error. Constructor/start rejection tests use no market requests. `startup_before.json` and `startup_after.json` contain safe exception classes and resource observations.
2. **Rebuilt diagnostic events were double counted.** Existing capture used Python object identity, while failure summaries rebuild sanitized event objects. Multiset subtraction now removes captured copies without collapsing genuinely repeated identical events. Unknown Provider counts remain UNKNOWN; no events does not mean zero requests.
3. **Initial publication scaffold failed on Windows long paths.** Immutable-generation paths exceeded the native path limit in temporary test roots. Read operations now use the Windows extended path form only after validating a resolved project-relative path. Hash/date checks remain strict.
4. **Daily-update error labeling was misleading.** The controlled real run returned DATA_ERROR before determining a trade date; the earlier scaffold labeled it a date mismatch. DATA_ERROR is now handled before date comparison, with `UPDATE_PREPARATION_FAILED`. The original real evidence is retained, not rewritten as a successful run.

The historical 2.6035-second public DATA_VALIDATION_ERROR still lacks its original Worker evidence. Existing pre-worker instrumentation and local success/failure/timeout tests cover the blind spot, but the historical root cause is **NOT_PROVEN**, not attributed to these later defects.

## Market update and publication architecture

Explicit backend invocation performs:

`actual BaoStock calendar → eligible completed trade date → unchanged Stage3C full universe with persistent caches/checkpoints → quality/date checks → immutable generation → atomic current pointer → pinned Web reader`.

The calendar differentiates holidays, pre-close, missing dates and eligible sessions without weekday guesses. The current 16:00 Shanghai daily-data cutoff is preserved. READY does not prove the source has updated: actual output dates must agree with the target date before publication.

Screening and benchmark are published as one content-hashed generation. Validation includes existing screening contracts, source date, actual benchmark OHLC/date/hash/source/non-mock status, versions and credential/private-path rejection. Publication holds an exclusive lock; a failed write or validation leaves the last valid pointer intact. Readers pin both industry and benchmark to one generation. A corrupt authoritative pointer is DATA_ERROR and cannot silently fall back to old files. Different stock and snapshot dates remain DATA_STALE, retaining existing B1/B2 UNKNOWN behavior.

The Web never imports/runs the updater. Default homepage index display can read the verified saved benchmark offline; an explicit index-refresh button remains unchanged. Existing legacy snapshots work until the first validated generation is published. This does not make September data current.

### Actual update evidence and capacity

- One genuine calendar-only query succeeded in 1.8364s and identified 2026-10-14 as eligible; no industry scan or AI call occurred.
- One bounded real full-scope update attempt was made, with a 180-second control budget; total including cleanup was 182.9994s. Four Provider requests and three timeouts were observed. The industry-universe query failed before any complete 83-industry result or trade date existed. **Nothing was published.** Evidence: `outputs/final_engineering/controlled_update.txt` and the dated runtime metadata/checkpoint.
- The published industry/index snapshot therefore remains **2026-09-30**. Actual stock day 2026-10-14 does not match. Stale context is visibly stale, never relabeled VALID.
- Historical full 83-industry evidence took 30,064.172s (8.35h), 10,329 requests, including 25,882.125s in the sector phase. Stage3C.1 improvements were measured on a three-industry archive subset, not a new optimized full 83-industry day. New full-run peak memory, disk and runtime remain UNKNOWN.

GitHub-hosted jobs have a [6-hour limit](https://docs.github.com/en/actions/reference/limits). Standard public-repository runners are [free subject to platform limits](https://docs.github.com/en/billing/concepts/product-billing/github-actions). Community Cloud documents [690MB–2.7GB memory limits](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app). The existing measurements do not establish that either platform can reliably run the whole updater.

The prepared workflow is therefore opt-in, using a trusted self-hosted runner labeled `quantscore-market-data`, main-only, repository variable `QUANTSCORE_DAILY_UPDATES_ENABLED=true`, weekday 17:23 Shanghai schedule plus calendar verification, a 12h scan budget, serialized publication and ordinary non-force bot push of only validated snapshot files. No runner, paid service or Windows scheduled task was registered. See [operations](MARKET_UPDATE_OPERATIONS.md).

## Real stock reliability and latency

### Starting public release

The browser independently observed deployed SHA `8b57a7989612dd37727e8b1941bfacdb04477135`, fingerprint `d868c303e94eea170384b2087ca5c1632904bd715fbdf255aca74fc8f3ae53ce`, and unmodified source. Two intentional 600519 clicks generated exactly two analysis submissions; no AI call or full-market scan was submitted.

| Request | Browser seconds | Server seconds | Web cache | Provider requests | Outcome |
|---|---:|---:|---|---:|---|
| `9f7d8f1f7a5e4238b9b2baad530600b0` | 184.687 | 170.7594 | MISS | 10 | Real 600519 analysis/chart success |
| `07d944edf79446fb9bfe084c0eb43fe7` | 3.313 | 0.003 | HIT | 0 | Cached analysis success |

Both returned actual stock date 2026-10-14 and industry/benchmark snapshot date 2026-09-30. Industry was DATA_STALE and benchmark BENCHMARK_SNAPSHOT_DATA_STALE. Warm zero Provider calls is based on the observed cache-hit path, not inferred from missing events. Cold here means a new browser's first request with observed MISS; server caches were not cleared and the app was already awake. Homepage/navigation/network time cannot be separated into a pure Streamlit cold-start measurement.

### Local real Provider failure

One isolated empty-data-cache real request failed in 78.1754s; it was not repeatedly retried for a success. Request ID `355d181b9f9b4753a0035b5b6108fd74`: raw 68.4855s, qfq 2.0983s, six requests, one retry, two SDK timeouts. BaoStock raw timed out; AKShare qfq failed `INVALID_PRICE_VALUES`. The existing validator correctly rejected the data. The result was UNAVAILABLE, not a scored stock; internal engine placeholders in the archived failure payload are **not accepted QuantScore/Risk values** and the Web does not display them. Evidence: `outputs/final_engineering/local_live/verification.json`.

These results prove the failure is diagnosable and bounded; they do not prove that every future connection will succeed. Historic >1200s failures remain historical observations; the new public cold timing is an actual observation, not a universal performance guarantee.

## Automated verification

Final formal environment: project Python 3.11 `.venv`, project-local temporary storage. Full `python -m pytest`: **1084 passed, 1 skipped, 0 failures, 0 errors**, 271.97s console time. JUnit: 1085 total, 271.903s. Existing historical/superseded T20 skip remains; no skip was added, assertion removed or AppTest/production deadline increased.

Initial targeted publication tests exposed Windows path handling and two fixture-contract defects; all were repaired without removing the checks. Targeted publication/snapshot/pre-worker suite: 95 passed. After process cleanup fix, publication/startup/runtime suite: 73 passed. Earlier complete regression: 1082 passed / 1 skipped; final includes the two startup-resource tests.

Added coverage includes calendar boundaries, source-delay/date mismatch, stale state, incomplete scans, write/pointer corruption, last-good preservation, mixed-generation prevention, missing data, privacy rejection, deterministic same-input 41-rule and candidate-policy equivalence, default offline homepage read, event counts and process setup/start rejection. External market outcomes remain separate from offline controlled unit fixtures; fixtures are never passed off as market evidence.

AI safety/fallback is covered by existing full regression tests. Public checks keep Standard Rules selected and inspect AI Explanation/Auto entrances without requesting a paid model call. Earlier real DeepSeek validation is historical evidence, not repeated or falsely attributed to this release.

## Security and release discipline

Release files, staged diff, all current Git-difference inventory and new textual evidence are scanned for credential patterns/current environment secrets and encoded recoverable forms. No key was supplied to this task. No `.env` or local Streamlit secrets are tracked. New logs/JUnit are redacted for user-directory and hostname metadata. Temporary browser profiles, raw caches/checkpoints and outputs are excluded from Git. Initial unrelated files and core/config hash inventory are verified before publication. Actual matching private data is never printed by the scanner.

Latest scan: **0 credential/privacy findings in the release and new textual evidence; unrelated initial-file integrity PASS**. A synthetic privacy-rejection fixture is explicitly classified as synthetic, not real personal data. Scanning cannot establish arbitrary screenshots/OCR or all historical disk contents are secret-free; no new screenshots or API-key-bearing browser sessions were produced in this task.

## Formal release files

Application: `app/market_update.py`, `app/snapshot_publication.py`, `app/screening/batch_provider.py`, `app/web.py`, `app/web_market.py`, `app/web_observability.py`, `app/web_results.py`, `app/web_snapshots.py`.

Tests: `tests/test_market_publication.py`, `tests/test_provider_startup_cleanup.py`.

Operations: `.github/workflows/market-update.yml`, `tools/update_published_context.py`, `tools/scheduled_market_update.py`, `tools/commit_market_publication.py`.

Acceptance tools: `tools/product_public_verify.py`, `tools/final_public_verify.py`, `tools/final_live_probe.py`, `tools/final_startup_probe.py`, `tools/final_engineering_audit.py`, `tools/final_closure_security.py`.

Documentation: this report, `docs/MARKET_UPDATE_OPERATIONS.md`, README appended closure section only. Unrelated initial README/report edits and historical Stage26 files are not staged.

## Remaining minimum external operations

1. Register a trusted continuously available runner with `quantscore-market-data`, adequate storage and working BaoStock connectivity; review repository write/branch permissions, enable the opt-in variable, then run and verify one **complete** daily publication before claiming daily operation. If no such free resource exists, hosting selection remains an owner decision; no paid infrastructure is assumed.
2. If Cloud fails to update automatically, its owner must inspect main/app/web.py deployment logs and reboot/redeploy the existing app. This session has no authenticated Cloud management access. A push alone cannot prove a deployed SHA.

No additional scoring decision or key is required. No full-market scan is started by page navigation.
