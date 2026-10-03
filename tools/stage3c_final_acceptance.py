"""Observe the ORIGINAL run and finalize evidence; never fetch market data or scan.

Only runs pytest after the original process has exited with a finished artifact.
Historical snapshots and the original full_market files remain unchanged.
"""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import argparse
import csv
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/stage3c'
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text('utf-8-sig')) if path.exists() else {}


def write(path, payload):
    temp = path.with_suffix(path.suffix + '.acceptance.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), 'utf-8')
    temp.replace(path)


def alive(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise OSError(ctypes.get_last_error(), 'Cannot inspect original process safely')
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise OSError('Cannot inspect original exit code')
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def csv_write(name, rows, columns):
    with (OUT / name).open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def finalize(original_pid):
    from app.screening.policy import ScreeningPolicy
    full = read(OUT / 'full_market/screening_details.json')
    errors = []
    sectors, stocks = full['sectors'], full['stocks']
    policy = ScreeningPolicy.current()
    if len(sectors) != 83 or len({s['sector_id'] for s in sectors}) != 83:
        errors.append('Not exactly 83 unique final sector records')
    if full.get('is_mock') is not False or full.get('mode') != 'live':
        errors.append('Not a genuine live artifact')
    expected = {}
    eligible = [s for s in sectors if s['candidate_status'] == 'ELIGIBLE']
    for s in sectors:
        ctx = s.get('context', {})
        heat = ctx.get('sector_heat', {})
        if ctx:
            state, quality = policy.sector(heat, full['trade_date'])
            if ctx.get('data_status') != 'VALID':
                state, quality = 'NOT_EVALUABLE', ctx.get('data_status', 'DATA_INCOMPLETE')
            if ctx.get('primary_industry', {}).get('sector_id') != s['sector_id']:
                state, quality = 'NOT_EVALUABLE', 'DATA_INCONSISTENT'
            if (state, quality) != (s['candidate_status'], s['data_status']):
                errors.append('Sector policy mismatch: ' + s['sector_id'])
        if s['candidate_status'] == 'ELIGIBLE':
            members = [r['symbol'] for r in heat.get('s4', {}).get('raw_inputs', {}).get('limit_details', [])]
            if len(set(members)) != s['constituent_count']:
                errors.append('Expected-member evidence mismatch: ' + s['sector_id'])
            for symbol in members:
                if symbol in expected:
                    errors.append('Duplicate primary membership: ' + symbol)
                expected[symbol] = s['sector_id']
    actual = {s['symbol']: s['primary_industry'] for s in stocks}
    if actual != expected or len(actual) != len(stocks):
        errors.append('Actual stock universe differs from all eligible-sector members')
    for stock in stocks:
        if stock.get('analysis_file'):
            analysis = read(OUT / 'full_market' / stock['analysis_file'])
            state, quality, explanation = policy.stock(analysis, full['trade_date'], stock['primary_industry'])
            if (state, quality, explanation) != (stock['candidate_status'], stock['data_status'], stock['explanation']):
                errors.append('Stock policy replay mismatch: ' + stock['symbol'])
            if quality != 'VALID' and stock.get('QuantScore') is not None:
                errors.append('Invalid data presented as a numerical score: ' + stock['symbol'])
        elif stock['candidate_status'] != 'NOT_EVALUABLE' or stock.get('QuantScore') is not None:
            errors.append('Missing stock analysis not isolated correctly: ' + stock['symbol'])
    matched = [s for s in stocks if s['candidate_status'] == 'MATCHED']
    if {s['symbol'] for s in matched} != {s['symbol'] for s in full['candidates']}:
        errors.append('Candidate export differs from evaluated MATCHED set')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    history = OUT / 'acceptance_history' / stamp
    history.mkdir(parents=True)
    for p in [ROOT / 'docs/STAGE3C_RESULT.md', OUT / 'pytest.xml', OUT / 'pytest.txt', OUT / 'run_metadata.json']:
        if p.exists():
            shutil.copy2(p, history / p.name)
    # This is intentionally after the real task exited, never parallel with live scans.
    temp = ROOT / 'outputs/tmp/pytest' / ('stage3c_acceptance_' + stamp)
    temp.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(TMP=str(temp.parent), TEMP=str(temp.parent), TMPDIR=str(temp.parent))
    test_started = time.time()
    with (OUT / 'pytest.txt').open('w', encoding='utf-8') as log:
        completed = subprocess.run([sys.executable, '-m', 'pytest', '--basetemp=' + str(temp),
                                    '--junitxml=' + str(OUT / 'pytest.xml')], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
    test = {}
    if (OUT / 'pytest.xml').exists() and (OUT / 'pytest.xml').stat().st_mtime >= test_started:
        suite = ET.parse(OUT / 'pytest.xml').getroot().find('testsuite')
        test = {k: int(suite.attrib[k]) for k in ('tests', 'failures', 'errors', 'skipped')}
        test['passed'] = test['tests'] - test['failures'] - test['errors'] - test['skipped']
    sc, st = Counter(s['data_status'] for s in sectors), Counter(s['data_status'] for s in stocks)
    perf = dict(full['performance'])
    metrics = dict(trade_date=full['trade_date'], start_time=full['start_time'], end_time=full['end_time'],
        total_duration_seconds=perf['total_duration_seconds'], industry_total=full['industry_universe_total'],
        industry_processed=len(sectors), industry_scoreable=sc['VALID'],
        industry_not_evaluable=sum(s['candidate_status']=='NOT_EVALUABLE' for s in sectors),
        industry_data_error=sc['DATA_ERROR'], industry_stale=sc['DATA_STALE'], industry_inconsistent=sc['DATA_INCONSISTENT'],
        industry_heat_ge_70=len(eligible), stock_expected=len(expected), stock_attempted=len(stocks),
        stock_success=st['VALID'], stock_not_evaluable=sum(s['candidate_status']=='NOT_EVALUABLE' for s in stocks),
        stock_data_error=st['DATA_ERROR'], stock_stale=st['DATA_STALE'], stock_inconsistent=st['DATA_INCONSISTENT'],
        strategy_match_candidates=len(matched), provider_request_count=perf['provider_requests'],
        cache_hit_count=perf['cache_hits'], retry_count=perf['retry_count'],
        sector_phase_seconds=perf['sector_phase_seconds'], stock_phase_seconds=perf['stock_phase_seconds'],
        sector_average_seconds=perf['sector_phase_seconds']/len(sectors),
        stock_average_seconds=perf['stock_phase_seconds']/len(stocks) if stocks else None)
    log = (OUT / 'live_log.txt').read_text('utf-8', errors='replace')
    cli_api = ('CLI_API_SUCCESS' in log and (OUT/'cli_exit.txt').read_text().strip()=='0')
    small = read(OUT / 'small_live/screening_details.json')
    gate = read(OUT / 'small_live_gate.json')
    replay = read(OUT / 'replay/screening_details.json')
    passed = bool(not errors and completed.returncode==0 and test.get('failures')==0
                  and test.get('errors')==0 and cli_api and gate.get('verified')
                  and replay.get('status')=='COMPLETE' and 'FULL ' in log)
    status = 'PASS' if passed else 'PARTIAL'
    for s in sectors:
        s['sector_heat_status'] = s.get('context',{}).get('sector_heat',{}).get('overall_status',s['data_status'])
        s['screening_status'] = s['candidate_status']
        s['reason'] = (s.get('error') or s.get('context',{}).get('reason_code') or
                       ('Heat满足70门槛' if s['candidate_status']=='ELIGIBLE' else
                        '合法Heat低于70' if s['candidate_status']=='NOT_MATCHED' else '行业热度不可评分'))
    for s in stocks:
        s['failure_reason'] = s.get('error') or (s.get('explanation') if s['candidate_status']=='NOT_EVALUABLE' else '')
        if s.get('analysis_file'):
            s['analysis_file'] = 'full_market/' + s['analysis_file']
    sector_cols = ['sector_id','sector_name','constituent_count','trade_date','sector_heat','sector_heat_status',
                   'data_status','screening_status','reason']
    stock_cols = ['symbol','stock_name','primary_industry','industry_name','sector_heat','B1','B2','QuantScore','Risk',
                  'trade_date','data_status','candidate_status','explanation','failure_reason','analysis_file']
    csv_write('sector_scan.csv',sectors,sector_cols)
    csv_write('sector_quality.csv',[s for s in sectors if s['candidate_status']=='NOT_EVALUABLE'],sector_cols)
    csv_write('stock_scan.csv',stocks,stock_cols)
    csv_write('stock_failures.csv',[s for s in stocks if s['candidate_status']=='NOT_EVALUABLE'],stock_cols)
    candidate_rows = [dict(s, industry=s.get('industry_name'),SectorHeat=s['sector_heat']) for s in matched]
    csv_write('strategy_match_candidates.csv',candidate_rows,
        ['symbol','stock_name','industry','SectorHeat','B1','B2','QuantScore','Risk','trade_date','data_status','candidate_status','explanation'])
    perf.update({k:metrics[k] for k in ('provider_request_count','cache_hit_count','sector_average_seconds','stock_average_seconds')})
    # Measured long batch is not an interactive endpoint latency promise. No scheduler is implemented here.
    runtime = dict(interactive_request=False, manual_daily_scan='long unattended scan only',
                   scheduled_daily_batch='requires deployment scheduling and actual completion before next batch')
    perf.update(PERFORMANCE_OPTIMIZATION_REQUIRED=True, CURRENT_RUNTIME_ACCEPTABLE_FOR=runtime,
                timing_limitations='No separate market-fetch/core-score/IO timers; do not infer a measured split.')
    write(OUT / 'performance.json',perf)
    full['candidates'] = matched
    write(OUT / 'screening_details.json',full)
    meta = dict(stage='3C',status=status,original_process_id=original_pid,metrics=metrics,tests=test,
                final_test_exit_code=completed.returncode,validation_errors=errors,
                sector_quality_counts=dict(sc),stock_quality_counts=dict(st),
                small_live=dict(status=small['status'],stats=small['stats'],gate=gate),
                cli_api_passed=cli_api,full_universe_completed=not errors,
                PERFORMANCE_OPTIMIZATION_REQUIRED=True,CURRENT_RUNTIME_ACCEPTABLE_FOR=runtime,
                history_path=str(history.relative_to(ROOT)),commit=False,push=False,
                scoring_spec_version='1.4',assumption_version='v1.3',data_contract_version='1.4')
    meta['evidence_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()
                           if p.suffix in ('.csv','.json','.xml') and p.name!='run_metadata.json'}
    write(OUT / 'run_metadata.json',meta)
    report = '# QuantScore Stage 3C Final Full-Market Acceptance\n\n'
    sections = {
        'Full Market Completion':str(metrics),
        'Sector Statistics':str(dict(sc)),
        'Qualified Sectors':str([(s['sector_id'],s['sector_heat'],s['constituent_count']) for s in eligible]),
        'Stock Scan Statistics':str(dict(st)),
        'Strategy Match Candidates':f'{len(matched)} 策略匹配候选。无Top5限制；输出顺序仅为ENGINEERING_DISPLAY_ORDER。',
        'Data Quality':'不可评对象保留分母和原因，QuantScore为null；合法低分与数据错误分开。',
        'Failure Isolation':f'原任务最终结束；逐对象结果和纯离线policy复核错误：{errors}。',
        'Performance':str(perf),
        'Bottleneck Diagnosis':'行业阶段获取全部成分股raw/qfq并复用行业评分，股票阶段获取长历史并运行完整QuantScore。Provider逻辑请求数不含SDK分页包。现有计时不能独立量化数据获取、计算、IO或timeout占比，不虚构归因。',
        'Performance Optimization Required':'true。本轮未进行性能重构，未启动新扫描。',
        'CLI / API':f'此前真实验收保持：{cli_api}；API使用真实Provider的TestClient，非公网接口验收。',
        'Tests':str(test)+f'；扫描进程退出后执行pytest，exit={completed.returncode}。',
        'Evidence Files':'outputs/stage3c根目录为原运行最终导出；full_market原件未修改。历史PARTIAL报告与先前测试保存在 '+str(history.relative_to(ROOT)),
        'Small Live Smoke':str(small['stats'])+'；gate='+str(gate),
        'Remaining Issues':'长时间同步批处理不适合交互请求；细分瓶颈需未来专项测量。隔离的数据不可评项见quality/failures CSV。未修改评分、UI，未commit/push。',
        'Stage 3C Final Status':status,
    }
    report += '\n\n'.join('## '+k+'\n\n'+v for k,v in sections.items())+'\n'
    (ROOT/'docs/STAGE3C_RESULT.md').write_text(report,'utf-8')
    print(json.dumps(meta,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--original-pid',type=int,required=True)
    args=parser.parse_args()
    while True:
        current=read(OUT/'full_market/screening_details.json')
        running=alive(args.original_pid)
        if not running:
            if not current.get('end_time'):
                write(OUT/'final_acceptance_state.json',dict(status='PARTIAL',reason='ORIGINAL_RUN_INTERRUPTED',
                    original_pid=args.original_pid,sectors_completed=len(current.get('sectors',[])),
                    stocks_completed=len(current.get('stocks',[])),tests='NOT_RERUN_INCOMPLETE_SCAN'))
                return
            # Allow the existing 30-second status watcher to finish its final copy.
            time.sleep(35)
            finalize(args.original_pid)
            return
        write(OUT/'final_acceptance_state.json',dict(status='WAITING_ORIGINAL_RUN',original_pid=args.original_pid,
            observed_at=datetime.now(timezone.utc).isoformat(),sectors_completed=len(current.get('sectors',[])),
            stocks_completed=len(current.get('stocks',[])),new_scan_started=False,tests_started=False))
        time.sleep(30)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        write(OUT/'final_acceptance_state.json',dict(status='PARTIAL',reason='FINAL_ACCEPTANCE_TOOL_ERROR',
              error=str(exc),new_scan_started=False))
        raise
