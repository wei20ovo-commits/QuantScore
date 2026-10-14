# Market context backend operations

The Web app does not run the market updater. It reads the last published industry
and benchmark context. Its default homepage index display is also offline, with
the actual source date. Explicit index refresh remains a separate user action.

## Commands

Use the project Python 3.11 environment from the repository root:

```text
python tools/update_published_context.py live-plan
python tools/update_published_context.py run --run-timeout 43200
python tools/update_published_context.py run --resume --run-timeout 43200
```

`live-plan` queries the genuine BaoStock trading calendar, never scans industries.
`run` is an explicit, expensive full SH/SZ primary-industry operation using the
unchanged Stage3C service, persistent HistoryCache/ScoreMemo and checkpoints.
Resume requires the same day, versions, policy, universe and scope. Completed
error objects retain their existing resume semantics; use a new job directory or
the existing explicitly refreshed full reconstruction process when authoritative
recovery is required. No implicit repeat of failed completed objects is added.

At or after 16:00 Shanghai time a trading day is eligible for completed daily data.
Before that the plan is MARKET_NOT_CLOSED. Holidays/weekends are determined by the
actual calendar, not weekday arithmetic. A missing calendar date is UNKNOWN.
Nontrading/pre-close plans do not start a full scan. A READY calendar does not
prove prices are updated: result date, completion and benchmark coverage must
also pass publication checks. No incomplete scan is published.

## Atomic publication and retention

Each validated generation under `data/published/market_context/generations/` has
screening, benchmark, source time, contract versions, SHA256 and validation metadata.
The writer takes an exclusive publication lock, validates all inputs, writes an
immutable generation and validates it again. Only its final `os.replace` changes
`current.json`. A request pins that generation for both industry and benchmark.

Failure retains the previous pointer; there is no fallback to an unvalidated
generation. An invalid pointer returns DATA_ERROR. A different stock evaluation
date keeps DATA_STALE and the existing B1/B2 UNKNOWN behavior. Older generations
are audit history, not a reason to label old data as today's VALID data.
The legacy published files remain compatible until the first valid new generation.
Do not delete historic generations while active readers may be using them.
After an interrupted writer, inspect its `.publish.lock` and confirm the owner
is gone before manually clearing it. There is no automatic lock stealing.

Safe job status is `outputs/runtime/market-update/latest_attempt.json`.
Raw upstream checkpoints stay local and must be reviewed before sharing;
the publisher rejects credential/private-directory markers in public payloads.
No API key is required for BaoStock. Never publish the cache directory or secrets.

## Scheduling and resource conditions

The measured Stage3C full 83-industry archive took 30,064.172 seconds (8.35h),
10,329 requests; 25,882.125s was the sector phase. This is historic real evidence,
not a forecast of a new-day optimized run. Stage3C.1's improved timings were a
three-industry archive subset, so they do not establish full 83-industry capacity.
Peak RAM and disk for a new full optimized daily job remain unmeasured.

GitHub-hosted jobs have a [6-hour task limit](https://docs.github.com/en/actions/reference/limits).
Standard public-repository runners are [free subject to platform limits](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Community Cloud's documented [memory range is 690MB–2.7GB](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).
Neither is assumed to support this workload reliably.

`.github/workflows/market-update.yml` therefore requires a trusted dedicated
**self-hosted** runner labeled `quantscore-market-data` and repository variable
`QUANTSCORE_DAILY_UPDATES_ENABLED=true`. It runs weekdays at 17:23 Shanghai time,
still checks the calendar, and permits a manual same-date resume. Its full-run
budget remains 12h; queue, scheduler availability and cleanup are separate operational
limits. It caches validated data/checkpoints and commits **only** the validated
generation/pointer with an ordinary non-force push. A concurrent main update
causes a push failure, not a destructive merge/reset. Branch policy must allow
that narrowly scoped bot publication. Workflow and repo permissions are required.

This workflow is opt-in and is **not** evidence that a runner has been registered,
enabled, or has completed a daily production publication. Registration must be
performed by the repository owner. A permanently available local machine can also
run `tools/scheduled_market_update.py` via its own scheduler, with D-drive working
storage and a separate controlled publication step. No Windows task or paid service
was registered by this engineering change.

After enabling, verify one completed whole-universe job, actual peak RAM/disk/runtime,
source date, published pointer and cloud reader; only then call daily updates operational.
Keep monitoring failed/missing scheduled runs. A daily deadline is not a guarantee
of data source availability or a permission to weaken quality gates.
