"""Real SDK + Service + API + CLI acceptance; no synthetic fallback."""
from datetime import datetime, timezone
from importlib.metadata import version
import inspect
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys

import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.data.cache import DataCache
from app.data.models import DataError, ProviderError
from app.data.provider_manager import ProviderManager
from app.features.technical import build_features
from app.services.stock_analysis_service import StockAnalysisService

ROOT = Path(__file__).resolve().parents[1]


def error_record(exc):
    # SDK tracebacks can contain credentials; only app-sanitized errors are public.
    return {'status': 'NETWORK_FAILED' if isinstance(exc, ProviderError) else 'DATA_FAILED',
            'error': str(exc) if isinstance(exc, (ProviderError, DataError)) else type(exc).__name__}


def verify_averages(bars):
    if len(bars) < 64:
        return {'status': 'INSUFFICIENT_HISTORY', 'samples': []}
    features = build_features(bars)
    selected = sorted(random.Random(14).sample(range(59, len(bars)), 5))
    samples = []
    for i in selected:
        row = {'date': str(bars.date.iloc[i].date())}
        for window in (5, 30, 60):
            expected = math.fsum(float(x) for x in bars.close_adj.iloc[i-window+1:i+1]) / window
            actual = float(features[f'M{window}'].iloc[i])
            row[f'M{window}'] = {'manual': expected, 'system': actual,
                               'pass': math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-10)}
        samples.append(row)
    return {'status': 'PASS' if all(x[f'M{w}']['pass'] for x in samples for w in (5,30,60)) else 'FAIL',
            'samples': samples}


def main():
    import baostock
    from fastapi.testclient import TestClient
    from app.api import create_app
    provider = BaoStockProvider(timeout=60)
    manager = ProviderManager(cache=DataCache(), retries=1)
    service = StockAnalysisService(manager)
    report = {'run_at': datetime.now(timezone.utc).isoformat(), 'provider': provider.name,
              'baostock_version': version('baostock'), 'spec_version': '1.4',
              'assumption_version': 'v1.3', 'data_contract_version': '1.4',
              'mock_used': False, 'synthetic_fallback': False, 'benchmark_symbol': '000001.SH',
              'date_policy': 'Latest source-completed trading day; no fixed smoke date',
              'initial_analysis_force_refresh': True, 'cases': []}
    methods = ('login', 'logout', 'query_history_k_data_plus', 'query_stock_basic')
    report['sdk_signatures'] = {name: str(inspect.signature(getattr(baostock, name))) for name in methods}
    now = pd.Timestamp.now(tz='Asia/Shanghai')
    latest = now.normalize().tz_localize(None) - pd.Timedelta(days=int(now.hour < 16))
    probe_start = (latest - pd.DateOffset(years=3)).strftime('%Y-%m-%d')
    probe_end = latest.strftime('%Y-%m-%d')
    report['probe_interval'] = [probe_start, probe_end]
    for value, expected in [('600519','600519.SH'), ('000001','000001.SZ'), ('000001.SH','000001.SH')]:
        print(f'Real acceptance: {value}', flush=True)
        case = {'input': value, 'expected_symbol': expected, 'mock_used': False}
        try:
            security = manager.resolver.resolve(value)
            case['resolution'] = {'symbol': security.symbol, 'name': security.name,
                                  'asset_type': security.asset_type,
                                  'status': 'PASS' if security.symbol == expected else 'FAIL'}
        except Exception as exc:
            case['resolution'] = error_record(exc)
        try:
            result = service.analyze(value, refresh=True)
            case['analysis'] = result.to_dict()
            if result.data_status.status == 'UNAVAILABLE':
                case['status'] = 'NETWORK_FAILED' if result.data_status.error_code == 'PROVIDER_UNAVAILABLE' else 'DATA_FAILED'
                case['ma_verification'] = {'status':'NOT_EXECUTED', 'reason':'Real daily bars unavailable'}
            else:
                data = manager.fetch(value)
                row = data.bars.iloc[-1]
                case['actual_provider'] = data.metadata['provider']
                data.bars.to_csv(ROOT/f'outputs/smoke/{expected}_baostock_bars.csv', index=False)
                case['latest_values'] = {k: None if pd.isna(row[k]) else float(row[k]) for k in ('close_raw','close_adj','volume','turnover_rate')}
                case['ma_verification'] = verify_averages(data.bars)
                case['benchmark_last_date'] = None if data.benchmark is None else str(data.benchmark.date.iloc[-1].date())
                case['unknown_rules'] = [{'rule_id':r['rule_id'],'reason':r['reason_code']} for r in result.rules if r['status']=='UNKNOWN']
                case['status'] = ('PASS' if case['resolution']['status']=='PASS' and data.metadata['provider']=='baostock' and data.bars.volume.notna().all() and (value=='000001.SH' or data.bars.turnover_rate.notna().any()) and result.data_status.benchmark_available and case['ma_verification']['status']=='PASS' else 'PARTIAL')
        except Exception as exc:
            case.update(error_record(exc))
        case['direct_probes'] = []
        for adjustment in (['NONE'] if value=='000001.SH' else ['raw','qfq']):
            probe = {'adjustment': adjustment, 'requested_symbol': expected}
            try:
                d = (provider.fetch_benchmark(probe_start,probe_end) if adjustment=='NONE' else provider.fetch_stock_daily(expected,probe_start,probe_end,adjustment))
                probe.update(status='FETCH_SUCCEEDED', columns=list(d), rows=len(d), last_date=str(d.date.iloc[-1].date()))
            except Exception as exc:
                probe.update(error_record(exc))
            case['direct_probes'].append(probe)
        report['cases'].append(case)
    print('Real-backed FastAPI endpoints', flush=True)
    client = TestClient(create_app(service))
    report['api'] = {}
    for route in ('/api/health','/api/rules','/api/data/status/600519','/api/analyze/600519','/docs'):
        try:
            response = client.get(route)
            detail = {'http_status': response.status_code}
            if route.startswith('/api/analyze'):
                detail['data_status'] = response.json().get('data_status',{}).get('status')
                detail['provider'] = response.json().get('data_status',{}).get('provider')
                (ROOT/'outputs/smoke/stage22_api_600519.json').write_text(response.text, encoding='utf-8')
            report['api'][route] = detail
        except Exception as exc:
            report['api'][route] = error_record(exc)
    report['cli'] = []
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / '.deps') + os.pathsep + str(ROOT)
    env['PYTHONIOENCODING'] = 'utf-8'
    for suffix in ([], ['--json']):
        print('Real CLI: analyze 600519 ' + ' '.join(suffix), flush=True)
        command = [sys.executable,'-m','app.cli','analyze','600519',*suffix]
        try:
            run = subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
            entry = {'command': 'python -m app.cli analyze 600519 ' + ' '.join(suffix), 'exit_code': run.returncode}
            if suffix and run.stdout.strip():
                parsed=json.loads(run.stdout)
                (ROOT/'outputs/smoke/stage22_cli_600519.json').write_text(run.stdout, encoding='utf-8')
                entry.update(json_valid=True,data_status=parsed.get('data_status',{}).get('status'),symbol=parsed.get('symbol'))
            elif not suffix:
                entry['stdout']=run.stdout
            if run.stderr: entry['stderr_present']=True
            report['cli'].append(entry)
        except Exception as exc:
            report['cli'].append({'command':command[1:], 'status':'ERROR','error':type(exc).__name__})
    report['status'] = ('PASS' if all(c.get('status')=='PASS' for c in report['cases']) and all(x.get('http_status')==200 for x in report['api'].values()) and report['api'].get('/api/analyze/600519',{}).get('data_status') in ('AVAILABLE','PARTIAL') and all(x.get('exit_code')==0 for x in report['cli']) else 'PARTIAL')
    path = ROOT/'outputs/smoke/stage2_smoke_report.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# Stage 2 真实数据 Smoke Report','',f"运行时间：{report['run_at']}。BaoStock {report['baostock_version']}。",
           '真实网络调用，无 mock / 人工行情回退；先 refresh，再允许同轮真实缓存复用。日期自动取最近已完成日线。','',
           '| 输入 | 解析 | 状态 |','|---|---|---|']
    for case in report['cases']:
        lines.append(f"| {case['input']} | {case['resolution'].get('symbol','未解析')} | {case.get('status')} |")
    lines += ['', '完整评分、来源、字段覆盖、独立 SDK 请求、API、两种 CLI 与五日均线核对保存在 outputs/smoke/stage2_smoke_report.json。',
              '网络失败时不提供虚构价格、分数或均线核验结果；API 的 HTTP 200 仅表示诚实降级响应，不能算真实行情通过。', '',f"本轮真实验收：**{report['status']}**。"]
    (ROOT/'docs/STAGE2_DATA_SMOKE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'cases':[{k:c.get(k) for k in ('input','status')} for c in report['cases']]},ensure_ascii=False))


if __name__=='__main__':
    main()
