# Stage 4C.8-R1 — Pre-Worker Failure Diagnosis

Date: 2026-10-10. Baseline: `36f199b9bd1d20829dace585edfed25edb2a5629`.

Scope: local boundary diagnosis and instrumentation only. No public requests,
market requests, paid API calls, commit or push were performed for this stage.
Controlled fixtures below are offline tests, not evidence of live 600519 success.

## Public evidence and conclusion

The user supplied the following production observation; this run did not independently
retrieve the corresponding Cloud request or Worker logs:

| Field | User-provided value |
|---|---|
| request_id | `d21eb708d6a54029b6b4e654af302b60` |
| outcome / reason_code | FAILURE / DATA_VALIDATION_ERROR |
| total latency | 2.6035 seconds |
| Web cache | MISS |
| events / partial_events | `[]` / false |
| last_completed_stage | UNKNOWN |
| available terminal | WEB REQUEST_COMPLETE only |

**PUBLIC_ROOT_CAUSE_NOT_PROVEN.** The reason code alone does not prove invalid
OHLCV or a Provider failure. A missing Worker log does not prove the Worker never
started. The short duration does not independently establish where execution stopped.
`600519` is a valid input to the existing normalizer.

## Reproduced code defects

Before changing source, a controlled parent `create_web_service()` DataError reproduced
FAILURE / DATA_VALIDATION_ERROR / MISS / empty events / UNKNOWN completed stage /
partial_events=false. The patched Worker callable was not called in that control.
This reproduces the public result's *structure*, not its exact latency or actual cause.
Evidence: `outputs/stage4c8_r1/before_preworker_reproduction.json`.

| Boundary | Previous blind spot | Local repair |
|---|---|---|
| Web normalization | Ran before request identity/terminal wrapper | Same normalizer now runs inside the correlated wrapper |
| Parent service initialization | Constructor before bounded call had no captured phases | Parent initialization, snapshot, cache, Provider and component phases recorded |
| Provider policy | Explicit mock refusal surfaced as generic DataError | Same refusal, classified PROVIDER_CONFIGURATION_REJECTED |
| Provider constructor | Configuration/init failure could appear as unqualified data/network error | Exception type and known constructor boundary classify the error |
| Worker preparation | Directory/Pipe/Process setup outside previous error handler | Correlated WORKER_SETUP_FAILED with owned-resource cleanup |
| Worker start | Generic startup error | WORKER_START_FAILED and measured setup/start events |
| Request summary | No events could still produce zero observed timeout/retry counters | Without relevant observation, these counts remain UNKNOWN |

Provider configuration ValueError is labeled PROVIDER_CONFIGURATION_ERROR, but
the particular rejected value is deliberately not serialized. Constructor exception
messages are not used to infer a network failure. Permission, file-not-found and
import failures have distinct safe categories. A generic initialization DataError
retains DATA_VALIDATION_ERROR alongside its actual failing stage; its specific data
meaning remains unknown.

## Exception and log chain

`app/web.py` delegates preprocessing to `run_observed_analysis()`. That wrapper binds
request_id, captures allowlisted parent events, forwards an existing sink, and restores
both sink and identity on exit. Worker IPC evidence is merged with captured parent
events. Same-object in-process events are not counted twice.

`analyze_stock()` retains its existing parent construction and Provider refusal.
`bounded_web_call()` retains the spawn architecture and 240-second production
deadline. Setup/start failures now emit safe WORKER and WEB terminal evidence.
Worker initialization failures retain their innermost typed boundary category.

Events and terminal JSON use the existing WARNING-level
`QUANTSCORE_WEB_DIAGNOSTIC` transport. Local logging tests verify the emitted
records and matching request IDs. Cloud receipt/filtering has not been reverified.
Only allowlisted stages, reason codes, providers, dates and measured durations are
serialized; arbitrary exception messages and tracebacks are not included.

## Date and UNKNOWN integrity

Snapshot dates are emitted immediately after the actual snapshot reader completes,
before subsequent cache/Provider construction can fail. No date is synthesized.
The controlled published fixture reads 2026-09-30; stock date and validity remain
UNKNOWN when stock analysis has not happened. A snapshot date does not mean VALID.
Existing same-date requirements and DATA_STALE/B1/B2 semantics are unchanged.

No Provider events means Provider calls, timeout/retry counts and raw/qfq durations
remain UNKNOWN. It does not mean zero calls. A successful `worker_start` event proves
parent dispatch succeeded, not that the child entered its target. Before an internal
child event, that distinction remains unobserved.

## Local validation

`tools/stage4c8_r1_verify.py` produced seven offline controls and correlated terminal
logs in `outputs/stage4c8_r1/local_boundary_smoke.json`:

| Control | Result | Reason |
|---|---|---|
| Web preprocessing rejection | FAILURE | WEB_INPUT_REJECTED |
| Parent service DataError | FAILURE | DATA_VALIDATION_ERROR, with initialization stage |
| Explicit Provider policy refusal | FAILURE | PROVIDER_CONFIGURATION_REJECTED |
| Provider constructor rejection | FAILURE | PROVIDER_CONFIGURATION_ERROR |
| Worker start rejection | FAILURE | WORKER_START_FAILED |
| Spawned offline engine-result transport | SUCCESS | NONE |
| Spawned unavailable-result transport | FAILURE | DATA_UNAVAILABLE |

The success/unavailable controls use a genuine spawned process transporting an
artificial engine fixture. Its 41 rule results, score, Risk and industry context
are compared unchanged. This is diagnostic transport verification, not live-market
or public semantic-equivalence acceptance.

`tests/test_web_preworker_diagnostics.py`: **21 PASS / 0 FAIL / 0 ERROR / 0 SKIP**,
77.762 seconds in the final independent run. Covers all six requested scenario
families, nested constructor failures, sink restoration, Worker cleanup, privacy
sentinels, Web rendering and UNKNOWN counters.

## Test startup evidence and intermediate failures

Intermediate failures are retained in the new evidence directory, not hidden:

| Run | PASS | FAIL | ERROR | SKIP | Notes |
|---|---:|---:|---:|---:|---|
| first_targeted | 96 | 2 | 0 | 0 | Existing UI startup timeouts; preliminary run |
| preworker_targeted | 19 | 1 | 0 | 0 | New cold UI initial 3-second budget |
| ui_isolated | 2 | 1 | 0 | 0 | Independent cold new UI still timed out |
| ui_line_run | 0 | 1 | 0 | 0 | Timeout during initial CSS st.html |
| ui_verified | 1 | 0 | 0 | 0 | New test initial budget justified below |
| combined | 115 | 3 | 0 | 0 | Two legacy UI startup timeouts and a legacy spawn readiness timeout |
| targeted_final | 21 | 0 | 0 | 0 | Final source, independent directed gate |

Cold startup tracing measured total AppTest 7.7677 seconds. An isolated 3-second
failure stopped at the initial CSS call before new request diagnostics executed.
The passing line trace measured initial CSS 4.7077 seconds, deployment identity
0.6488 and home rendering 0.9496. Thus **only the new test's first cold AppTest run**
uses a 10-second test budget; its subsequent submit retains the default 3 seconds.
No existing test budgets/assertions/skips were changed. Production limits were not
changed. Preliminary source work overlapped some early runs; those runs are not
the final release gate. Existing intermittent UI/spawn startup failures cannot be
attributed to this request instrumentation on the evidence available.

Formal full regression in the project's `.venv`:

```text
python -m pytest --basetemp=outputs/tmp/stage4c8-r1/formal \
  --junitxml=outputs/stage4c8_r1/formal.xml
1041 total: 1040 PASS / 0 FAIL / 0 ERROR / 1 SKIP
3811.79 seconds (pytest terminal elapsed time); exit code 0
```

TMP/TEMP/TMPDIR were directed to project-local D-drive temporary storage for this
formal run. The existing T20 historical/superseded skip remains; no skip was added.
Existing real-spawn timeout, pre-snapshot timeout/UNKNOWN-date and Web terminal-log
tests passed in this full run. This demonstrates the local final gate, not a
guarantee that all earlier environment-sensitive startup timeouts are eliminated.

## Changes and protection

Changed source: `app/web.py`, `app/web_backend.py`, `app/web_diagnostics.py`,
`app/web_observability.py`, `app/web_runtime.py`.

Added: this report, `tests/test_web_preworker_diagnostics.py`, and four local tools
`stage4c8_r1_workers.py`, `stage4c8_r1_verify.py`, `stage4c8_r1_ui_timing.py`,
`stage4c8_r1_closure.py` under `tools/`.
Evidence: `outputs/stage4c8_r1/`; temporary fixtures: `outputs/tmp/stage4c8-r1/`.

No changes to rules, scoring, Risk, B1/B2, Candidate,行情校验, Provider retry,
cache TTL or production 240-second deadline. Existing dirty reports/README,
historical artifacts and Git index are protected by baseline hashes.
Final integrity audit: HEAD and Git index hashes unchanged; all 63 tracked core
data/config/scoring files match baseline; the three pre-existing modified files
(`README.md`, `docs/STAGE4C1_RESULT.md`, `docs/STAGE4C2_RESULT.md`) match their
start-of-task hashes. No staged content was changed.

## Privacy and credential scan

`tools/stage4c8_r1_closure.py` scans working/staged diffs, changed files, this
report, new test/tools and all top-level new stage evidence. Scan result:
**0 credential findings / 0 private-user-directory findings**. The first scan
covered 39 items. Raw pytest evidence generated local paths/host metadata; these
were redacted only in this stage's new artifacts before publication. No exception
sentinel appeared in the allowlisted diagnostic records. No credential was used.

Scope is explicit: historical raw outputs/logs and local temporary fixture
directories are preserved and excluded from publication, not claimed to have been
sanitized by this stage. No screenshots were created. Final evidence:
`outputs/stage4c8_r1/closure.json`. The scan is repeated after this report update.

## Remaining verification

After a separately authorized publication, verify the running SHA/fingerprint and
perform one controlled 600519 request. Correlate request_id through parent and child
events. Use the first actual failed boundary, without inferring missing metrics.
This stage made no public requests and cannot determine whether the original failure
was initialization, configuration, deployment environment, missing child evidence,
or another unobserved exception. No Stage5 work was started.

## Status

Local diagnostic repair and test gate: PASS. Overall production diagnosis: PARTIAL.
The original public root cause and deployment of these uncommitted changes remain
unverified. No commit/push or further production request was performed.
