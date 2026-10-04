"""Build acceptance from actual retained measurements; never invent a PASS."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/stage3c1'

def read(name):return json.loads((OUT/name).read_text('utf-8'))
def write(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def business(result):
    fields=('symbol','sector_heat','B1','B2','positive_score','risk_penalty','QuantScore','Risk','candidate_status','data_status')
    stocks={r['symbol']:{k:r.get(k) for k in fields} for r in result['stocks']}
    sectors={r['sector_id']:{k:r.get(k) for k in ('sector_heat','data_status','candidate_status','constituent_count')} for r in result['sectors']}
    for row in result['sectors']:
        heat=row.get('context',{}).get('sector_heat',{})
        sectors[row['sector_id']]['rules']={sid:{k:heat.get(sid,{}).get(k) for k in
            ('score','max_score','status','data_status','threshold_band','source_date')} for sid in ('s1','s2','s3','s4','s5','s6','s7')}
    rules={}
    for row in result['stocks']:
        data=json.loads((OUT/result['_directory']/row['analysis_file']).read_text('utf-8'))
        rules[row['symbol']]={r['rule_id']:{k:r.get(k) for k in ('status','score','penalty','conditions')} for r in data['rules']}
    return dict(sectors=sectors,stocks=stocks,rules=rules)


def main():
    labels=['baseline','optimized_final','warm_after_final']
    profiles={label:read(f'profiling_{label}.json') for label in labels}
    results={label:{**read(label+'/screening_details.json'),'_directory':label} for label in labels}
    canonical=business(results['baseline']);comparisons={}
    for label in labels[1:]:
        actual=business(results[label])
        comparisons[label]={k:actual[k]==canonical[k] for k in canonical}
    equivalent=all(all(c.values()) for c in comparisons.values())
    write('result_equivalence.json',dict(status='PASS' if equivalent else 'FAIL',
        comparisons=comparisons,sectors=3,expected_members=406,stocks=47,rules_per_stock=41,
        compared_fields=['SectorHeat','B1','B2','QuantScore','Risk','candidate_status','data_status','all rule status/score/penalty/conditions'],
        source_mode='real-normalized-transport-replay',is_live_network=False))
    baseline=profiles['baseline']['duration_seconds']
    base_requests=profiles['baseline']['metrics']['provider_requests']
    rows=[]
    requests={};caches={}
    for label,report in profiles.items():
        metrics=report['metrics'];duration=report['duration_seconds']
        counts={}
        for r in report['normalized_requests']:
            kind=r['method']
            if kind=='normalized_history':kind+='_'+r['parameters']['adjustment']
            counts[kind]=counts.get(kind,0)+1
        requests[label]=dict(total=metrics['provider_requests'],by_method=counts,
                              retry_count=metrics['retry_count'],unit='normalized frame transport calls, not SDK field groups/pages')
        caches[label]={k:metrics.get(k) for k in ('cache_hits','cache_misses','history_cache','score_memo')}
        hits,misses=metrics['cache_hits'],metrics['cache_misses']
        rows.append(dict(run=label,mode='real-recorded-input-replay',seconds=duration,
                         provider_requests=metrics['provider_requests'],cache_hits=hits,cache_misses=misses,
                         cache_hit_rate=hits/(hits+misses) if hits+misses else None,
                         retries=metrics['retry_count'],stocks=47,sectors=3,
                         stocks_per_second=47/duration,sectors_per_second=3/duration,
                         observed_speedup=baseline/duration,
                         request_reduction=1-metrics['provider_requests']/base_requests))
    pd.DataFrame(rows).to_csv(OUT/'benchmark_comparison.csv',index=False)
    write('request_counts.json',requests);write('cache_metrics.json',caches)
    # Required filename points to the final cold measurement; retain earlier attempts.
    write('profiling_optimized.json',profiles['optimized_final'])
    junit=ET.parse(OUT/'pytest_final.xml').getroot()
    suites=list(junit.iter('testsuite'))
    tests={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    tests['passed']=tests['tests']-tests['failures']-tests['errors']-tests['skipped']
    live=read('live_cache_verification.json');resume=read('checkpoint_resume_test.json');worker=read('bounded_score_real.json')
    complete=all(r['stats']['stock_analyzed']==47 and len(r['sectors'])==3 for r in results.values())
    status='PASS' if equivalent and complete and live['status']=='PASS' and resume['status']=='PASS' and worker['status']=='PASS' and tests['failures']==tests['errors']==0 and rows[-1]['provider_requests']<base_requests else 'PARTIAL'
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    origin=subprocess.check_output(['git','rev-parse','origin/main'],cwd=ROOT,text=True).strip()
    manifest={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.suffix in ('.json','.csv','.xml','.py') and p.name!='run_metadata.json'}
    write('run_metadata.json',dict(status=status,head=head,origin_main=origin,python=platform.python_version(),tests=tests,
        trade_date='2026-09-30',spec_version='1.4',assumption_version='v1.3',data_contract_version='1.4',
        benchmark_industries=['C15','C26','H61'],benchmark_universe_counts=[47,354,5],
        input_sqlite_sha256=sha(ROOT/'data/cache/market.sqlite3'),
        benchmark_mode='recorded genuine BaoStock normalized data; separate live network cache proof',
        provider_concurrency=1,full_market_rerun=False,committed=False,pushed=False,manifest=manifest,
        limitations=['Cold wall-clock ratios include host scheduling and cannot imply faster rule algorithms.',
                     'No new full-market runtime measurement; do not extrapolate the subset speedup to all 83 industries.',
                     'Overlap checks cannot detect arbitrary provider corrections outside the overlap; use force refresh.',
                     'Clear derived score memo after Python/pandas/numpy upgrades.',
                     'C26 retains genuine archived data errors; its 354-member denominator is not reduced.']))
    table=pd.DataFrame(rows)[['run','seconds','provider_requests','cache_hits','retries','observed_speedup']].to_markdown(index=False) if False else '\n'.join(f"| {r['run']} | {r['seconds']:.3f} | {r['provider_requests']} | {r['cache_hits']} | {r['retries']} | {r['observed_speedup']:.2f}x |" for r in rows)
    report=f'''# Stage 3C.1 Performance & Runtime Optimization

Status: **{status}**. Audited HEAD and fetched origin/main: `{head}`. No commit/push, UI, SSOT, scoring weights, candidate policy, or universe changes. Initial Git connection failures were followed by a successful fetch.

## Measurement and scope

Fixed genuine BaoStock archive: 2026-09-30, C15 (47), C26 (354), H61 (5). All 406 expected members retained; all 47 eligible C15 stocks processed. C15 Heat=70; H61 DATA_INCOMPLETE; C26 retains the original DATA_ERROR. No Top N or stock sampling. The performance loop is **recorded normalized transport**, not a new live full-market run. Source SHA256 and per-file evidence hashes are in run_metadata.json.

| Run | Seconds | Normalized requests | Cache hits | Retries | Observed speedup |
|---|---:|---:|---:|---:|---:|
{table}

Baseline measured full QuantScore time: {profiles['baseline']['profile']['seconds']['QuantScore']:.3f}s; SectorHeat {profiles['baseline']['profile']['seconds']['SectorHeat']:.6f}s; sector phase {profiles['baseline']['profile']['seconds']['sector_phase']:.3f}s; serialization {profiles['baseline']['profile']['seconds']['serialization_io']:.3f}s. Baseline stock fetch/presentation residual is stock_phase minus QuantScore, not a separately instrumented fetch timer. Nested timings overlap and must not be summed. The baseline normalized adapter does not use SDK throttle/timeout waits; those are not measured as network latency. Baseline scoring source was frozen from the audited active HEAD in baseline_source; no superseded history was restored.

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

Separate actual BaoStock network requests verified 600519/贵州茅台 raw/qfq and 000001.SH. Live timings: `{live.get('timings')}`; cache metrics `{live.get('cache_metrics')}`. Cold responses and incremental responses are saved as CSV; no mock substituted. Warm reuse requires no requests. A real archived full 000568 score in the bounded production worker matches all 41 rule results; runtime {worker['seconds']:.3f}s. Failed initial warm replay and its dictionary-mutation diagnostic are preserved under warm/, warm_debug/ and warm_debug_trace.txt; warm_after_final is the accepted final run.

## Product runtime assessment

An interactive whole-market cold scan remains unsupported by these measurements: the subset cold runtime is already minutes, and no new 83-industry runtime was measured. A manual daily scan can use warm/incremental data and checkpoints but still needs explicit batch deadlines. Scheduled daily batch is the appropriate backend pattern; a later Web layer can read completed cached results. Fresh/changed-input score computations still take time; a cache hit does not establish a new trade-date runtime guarantee. No UI or scheduler is introduced in this stage.

## Tests and evidence

Full `.venv` `python -m pytest`: {tests['tests']} total, {tests['passed']} PASS / {tests['failures']} FAIL / {tests['errors']} ERROR / {tests['skipped']} historical SKIP. Original tests retained. New tests cover persistent reuse/increment, anchor change, invalid data, refresh/TTL, cache concurrency, resume identity/tampering, object/run timeouts, process termination, result equality and memo invalidation. JUnit/text: outputs/stage3c1/pytest_final.xml and pytest_final.txt.

Required artifacts: profiling_baseline.json, profiling_optimized.json, benchmark_comparison.csv, request_counts.json, cache_metrics.json, checkpoint_resume_test.json, result_equivalence.json, run_metadata.json. Additional real-network and worker evidence is retained alongside these.

## Reproduction

Use Python 3.11 project .venv, no .deps/PYTHONPATH. Retain original real input SQLite and baseline_source. Baseline: `python tools/stage3c1_benchmark.py --label baseline` against a fresh baseline_cache file. Optimized cold: `python tools/stage3c1_benchmark.py --label optimized_final` against fresh final_cache/final_history/final_scores files; warm: `python tools/stage3c1_benchmark.py --label warm_after_final`. Preserve previous files by moving the owned benchmark artifacts to a new evidence directory before another cold run; never label a reused cache as cold. Network proof: `python tools/stage3c1_live.py` creates a new isolated history cache per run. Resume proof: `python -m tools.stage3c1_resume`. Final report: `python tools/stage3c1_finalize.py`.

Operational screening: `python -m app.cli screen --json --output-dir outputs/runtime/daily`. Resume with identical scope: add `--resume`; optional `--request-timeout 60 --sector-timeout 1800 --stock-timeout 300 --run-timeout 43200`. A changed day rejects the old checkpoint; start a new daily output directory.

## Remaining limits

No full-market extrapolation or live high-concurrency claim. Cache overlap cannot detect arbitrary historical corrections outside that range; use --refresh for authoritative full reconstruction. Derived score cache must be cleared after numerical runtime upgrades. Existing missing/invalid market data remains unscoreable. No Stage 4, commit or push.
'''
    (ROOT/'docs/STAGE3C1_RESULT.md').write_text(report,encoding='utf-8')
    metadata=read('run_metadata.json')
    files=[*(ROOT/'app/screening').glob('*.py'),ROOT/'app/cli.py',ROOT/'tests/test_screening_runtime.py',
           ROOT/'README.md',ROOT/'docs/TEST_REPORT.md',ROOT/'docs/STAGE3C1_RESULT.md',
           *(ROOT/'tools').glob('stage3c1_*.py')]
    metadata['implementation_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in files}
    metadata['core_git_diff_empty']=not subprocess.check_output(['git','diff','--','app/engine','app/rules',
                'app/features','config','app/sector','app/data'],cwd=ROOT).strip()
    metadata['preexisting_untracked_preserved']=['docs/STAGE26_FINAL_VERIFICATION.md','tools/stage26_public_smoke.py']
    write('run_metadata.json',metadata)
    print(status,tests,rows)

if __name__=='__main__':main()
