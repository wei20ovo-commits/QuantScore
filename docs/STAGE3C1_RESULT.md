# Stage 3C.1 Performance & Runtime Optimization

Status: **PASS**. Audited HEAD and fetched origin/main: `ba3b8e64aad0160e7c573f3337603a0950721afe`. No commit/push, UI, SSOT, scoring weights, candidate policy, or universe changes. Initial Git connection failures were followed by a successful fetch.

## Measurement and scope

Fixed genuine BaoStock archive: 2026-09-30, C15 (47), C26 (354), H61 (5). All 406 expected members retained; all 47 eligible C15 stocks processed. C15 Heat=70; H61 DATA_INCOMPLETE; C26 retains the original DATA_ERROR. No Top N or stock sampling. The performance loop is **recorded normalized transport**, not a new live full-market run. Source SHA256 and per-file evidence hashes are in run_metadata.json.

| Run | Seconds | Normalized requests | Cache hits | Retries | Observed speedup |
|---|---:|---:|---:|---:|---:|
| baseline | 3248.499 | 797 | 65 | 44 | 1.00x |
| optimized_final | 871.855 | 685 | 120 | 6 | 3.73x |
| warm_after_final | 235.550 | 9 | 843 | 6 | 13.79x |

Baseline measured full QuantScore time: 3039.473s; SectorHeat 0.001900s; sector phase 26.440s; serialization 7.339s. Baseline stock fetch/presentation residual is stock_phase minus QuantScore, not a separately instrumented fetch timer. Nested timings overlap and must not be summed. The baseline normalized adapter does not use SDK throttle/timeout waits; those are not measured as network latency. Baseline scoring source was frozen from the audited active HEAD in baseline_source; no superseded history was restored.

The largest cold archived-data cost was full QuantScore CPU work. No rule algorithm was changed. Cold wall-clock improvement includes host scheduling/caching variance and is **not evidence of a faster scoring formula**. The defensible warm improvement is input-validated memo reuse plus fewer transport calls. Request categories separate raw, qfq, benchmark, membership/basic/calendar. Some retry reduction reflects cancelling queued work after genuine C26 archive failures, not request deduplication alone.

## Implementation

- RequestCache indexes validated ranges by provider/symbol/adjustment; a lock protects existing acquisition threads. Calendar unions require every calendar date, without filling holidays or shrinking a window. Benchmark, membership and metadata remain shared in the run; Heat/returns remain memoized once per industry/date.
- HistoryCache persists provider/symbol/raw-qfq/range/fetched_at/VALID. A subsequent date fetches a 14-calendar-day overlap plus new dates. Any changed overlap (including qfq anchor movement) forces a full refresh. Failed/invalid increments never advance coverage. The initial sector-to-full-stock extension fetches a full range once, ensuring one qfq anchor. Force refresh bypasses persistence and retains per-run deduplication.
- ScoreMemo fingerprints full bars/benchmark, business metadata, frozen snapshots, registry/parameters, and engine/rule/feature source hashes. Different input recomputes the entire unchanged engine; no renormalization. Transport provenance is refreshed on a hit. Clear this derived memo when upgrading the numerical runtime. Core engines and all rule definitions are unchanged.
- Atomic checkpoint manifest plus SHA256-verified per-object files saves completed industries/stocks, eligible industries, errors, date, versions and full universe. Resume verifies date/version/policy/universe/selection and hydrates Heat contexts. It repeats only preparation validation and incomplete objects; it does not retry already completed error objects implicitly.
- Default operational limits: request 60s, sector 1800s, stock 300s, run 43200s; maximum 3 acquisition attempts; 1s preparation backoff plus existing SDK throttle/error backoff. CLI exposes the four deadlines and --resume. Queue time counts toward the run deadline. Provider large responses use atomic files before a small IPC notification; bounded termination/kill protects request completion. Production cold score misses execute the same pure engines in an isolated process, killed at the object/run deadline. Local validation/serialization checks are cooperative; process cleanup may add up to 4s. A whole-run stop returns STOPPED, complete=false, checkpoint retained, CLI nonzero; object failures remain NOT_EVALUABLE/DATA_ERROR, never 0.
- No provider concurrency increase: one serialized SDK worker, existing data acquisition pool retained. No 2-worker live throughput experiment was needed or used.

## Correctness and real network proof

SectorHeat, B1/B2, positive/penalty/QuantScore, Risk, candidate/data status and all 41 rule status/score/penalty/conditions match baseline for every stock in both final runs. result_equivalence.json records the independent comparisons. Real archived checkpoint interruption: 3 industries and 1 stock completed; resume ran 0 industry builds and 46 remaining stocks, matching baseline. Version/date/universe mismatch and tampering are rejected by tests.

Separate actual BaoStock network requests verified 600519/贵州茅台 raw/qfq and 000001.SH. Live timings: `{'cold': {'seconds': 3.235000000000582, 'requests': 3}, 'warm': {'seconds': 0.0, 'requests': 0}, 'incremental': {'seconds': 2.061999999990803, 'requests': 3}}`; cache metrics `{'hits': 3, 'cold_fetches': 3, 'incremental_fetches': 3, 'prefix_fetches': 0, 'anchor_refreshes': 0, 'failures': 0}`. Cold responses and incremental responses are saved as CSV; no mock substituted. Warm reuse requires no requests. A real archived full 000568 score in the bounded production worker matches all 41 rule results; runtime 20.813s. Failed initial warm replay and its dictionary-mutation diagnostic are preserved under warm/, warm_debug/ and warm_debug_trace.txt; warm_after_final is the accepted final run.

## Product runtime assessment

An interactive whole-market cold scan remains unsupported by these measurements: the subset cold runtime is already minutes, and no new 83-industry runtime was measured. A manual daily scan can use warm/incremental data and checkpoints but still needs explicit batch deadlines. Scheduled daily batch is the appropriate backend pattern; a later Web layer can read completed cached results. Fresh/changed-input score computations still take time; a cache hit does not establish a new trade-date runtime guarantee. No UI or scheduler is introduced in this stage.

## Tests and evidence

Full `.venv` `python -m pytest`: 788 total, 787 PASS / 0 FAIL / 0 ERROR / 1 historical SKIP. Original tests retained. New tests cover persistent reuse/increment, anchor change, invalid data, refresh/TTL, cache concurrency, resume identity/tampering, object/run timeouts, process termination, result equality and memo invalidation. JUnit/text: outputs/stage3c1/pytest_final.xml and pytest_final.txt.

Required artifacts: profiling_baseline.json, profiling_optimized.json, benchmark_comparison.csv, request_counts.json, cache_metrics.json, checkpoint_resume_test.json, result_equivalence.json, run_metadata.json. Additional real-network and worker evidence is retained alongside these.

## Reproduction

Use Python 3.11 project .venv, no .deps/PYTHONPATH. Retain original real input SQLite and baseline_source. Baseline: `python tools/stage3c1_benchmark.py --label baseline` against a fresh baseline_cache file. Optimized cold: `python tools/stage3c1_benchmark.py --label optimized_final` against fresh final_cache/final_history/final_scores files; warm: `python tools/stage3c1_benchmark.py --label warm_after_final`. Preserve previous files by moving the owned benchmark artifacts to a new evidence directory before another cold run; never label a reused cache as cold. Network proof: `python tools/stage3c1_live.py` creates a new isolated history cache per run. Resume proof: `python -m tools.stage3c1_resume`. Final report: `python tools/stage3c1_finalize.py`.

Operational screening: `python -m app.cli screen --json --output-dir outputs/runtime/daily`. Resume with identical scope: add `--resume`; optional `--request-timeout 60 --sector-timeout 1800 --stock-timeout 300 --run-timeout 43200`. A changed day rejects the old checkpoint; start a new daily output directory.

## Remaining limits

No full-market extrapolation or live high-concurrency claim. Cache overlap cannot detect arbitrary historical corrections outside that range; use --refresh for authoritative full reconstruction. Derived score cache must be cleared after numerical runtime upgrades. Existing missing/invalid market data remains unscoreable. No Stage 4, commit or push.
