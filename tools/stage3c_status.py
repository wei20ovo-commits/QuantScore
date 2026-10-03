"""Audit current evidence, including incomplete live runs, without network access."""
from pathlib import Path
import json,hashlib,shutil,xml.etree.ElementTree as ET
from datetime import datetime,timezone
import sys,time
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/stage3c'

def read(path):
    return json.loads(path.read_text('utf-8-sig')) if path.exists() else {}

def main():
    small=read(OUT/'small_live/screening_details.json')
    full=read(OUT/'full_market/screening_details.json')
    replay=read(OUT/'replay/screening_details.json')
    gate=read(OUT/'small_live_gate.json')
    api=read(OUT/'api_screen.json')
    exitfile=OUT/'cli_exit.txt'
    cli_exit=int(exitfile.read_text('utf-8').strip()) if exitfile.exists() else None
    log=(OUT/'live_log.txt').read_text('utf-8',errors='replace') if (OUT/'live_log.txt').exists() else ''
    tests={}
    if (OUT/'pytest.xml').exists():
        suite=ET.parse(OUT/'pytest.xml').getroot().find('testsuite')
        tests={k:int(suite.attrib[k]) for k in ['tests','failures','errors','skipped']}
        tests['passed']=tests['tests']-tests['failures']-tests['errors']-tests['skipped']
    complete=bool(full and full.get('end_time') and full['stats'].get('industry_total')==full.get('industry_universe_total')
                  and full['stats'].get('stock_analyzed')==full['stats'].get('stock_expected'))
    clean=complete and full['stats'].get('provider_error')==0 and not full['errors'] and not any(s['data_status']=='DATA_ERROR' for s in full['sectors'])
    passed=bool(gate.get('verified') and clean and cli_exit==0 and 'CLI_API_SUCCESS' in log
                and api.get('is_mock') is False and api.get('status')!='DATA_ERROR'
                and tests and tests['failures']==tests['errors']==0 and replay.get('status')=='COMPLETE')
    status='PASS' if passed else 'PARTIAL'
    source=OUT/'full_market' if full else OUT/'small_live'
    for name in ['sector_scan.csv','sector_quality.csv','stock_scan.csv','stock_failures.csv',
                 'strategy_match_candidates.csv','screening_details.json','performance.json']:
        if (source/name).exists():shutil.copyfile(source/name,OUT/name)
    def summary(r):
        return dict(state=r.get('status','NOT_STARTED'),trade_date=r.get('trade_date'),stats=r.get('stats',{}),
                    stocks_completed=len(r.get('stocks',[])),sectors_completed=len(r.get('sectors',[])),
                    performance=r.get('performance',{}),start_time=r.get('start_time'),end_time=r.get('end_time'))
    meta=dict(stage='3C',status=status,observed_at=datetime.now(timezone.utc).isoformat(),
              evidence_scope=str(source.relative_to(ROOT)),small_live=summary(small),full_market=summary(full),
              small_gate=gate,full_universe_completed=complete,cli_exit=cli_exit,
              api_assertion_passed='CLI_API_SUCCESS' in log,tests=tests,
              scoring_spec_version='1.4',assumption_version='v1.3',data_contract_version='1.4',
              screening_semantics_version='stage3c-user-confirmed-2026-10-02',commit=False,push=False)
    meta['evidence_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()
                            if p.is_file() and p.suffix in ('.csv','.json','.xml') and p.name!='run_metadata.json'}
    (OUT/'run_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    report=f'''# QuantScore Stage 3C Automatic Screening Result

## Current Audit
本地HEAD=origin/main=c87fa9afec354b65ebf917d49f418c559c321e2b。
初次git fetch连接重置；仅本次命令关闭代理并使用HTTP/1.1后成功同步，
再次确认HEAD=origin/main为上述提交。保留原有Stage26未跟踪文件。
未reset/checkout/rebase，未commit/push。

## SSOT Audit
USER_CONFIRMED 2026-10-02活动语义见STAGE3C_RULE_FREEZE.md。
Heat>=70、完整QuantScore>=80、Risk非HIGH；无全局Coverage门槛，无Top5业务限制。
旧AutoScreenScore为SUPERSEDED / NOT USED。历史规范未改。

## Screening Architecture
app/screening仅编排现有PrimaryIndustryService、SectorHeatEngine和StockAnalysisService。
共享行业结果与基准；顺序工作进程每个请求仍fresh login/finally logout，保留原有传输保护。

## Sector Universe / Filtering
SH/SZ primary industry，metadata.type=1；BJ/非普通股票单列排除。
未知元数据不缩减成员分母；相关行业不可评。行业状态不是低分替代物。

## Stock / QuantScore / Risk
已有120交易日最低历史要求；完整现有评分和独立Risk不变。
MATCHED/NOT_MATCHED/NOT_EVALUABLE严格区分。确定性输出顺序不是投资优先级。
每只股票保留完整analysis文件及风险细节，失败不从统计中消失。

## Replay
真实存档子集离线回放={replay.get('status','NOT_RUN')}。
Stage35 S1–S7由原引擎重算，H61仍无完整Heat；Stage3B.1三个真实分析存档用于资格判定。
回放明确标记archived-real-subset，不冒充全市场或新live。

## Small Live Smoke
状态={small.get('status','NOT_STARTED')}；已完成行业={len(small.get('sectors',[]))}，
已完成股票={len(small.get('stocks',[]))}；完整统计={small.get('stats',{})}。
验收门={gate}。未结束的时间仅为已测运行时间，不是完整扫描耗时。

## Full Market Dry Run
状态={full.get('status','NOT_STARTED')}；已完成行业={len(full.get('sectors',[]))}，
已完成股票={len(full.get('stocks',[]))}；完整Universe已结束={complete}。
统计={full.get('stats',{})}。尚未完成时不得宣称PASS或伪造完整率。

## Performance
真实小规模测量={small.get('performance',{})}。
真实全市场测量={full.get('performance',{})}。
provider_requests为Provider逻辑查询尝试数，不含SDK内部分页报文；cache_hits为合法查询复用次数。
早期中断运行保留在before_*_small_live，不当作完整运行。

## CLI / API
screen CLI exit={cli_exit}；真实CLI/API断言已通过={'CLI_API_SUCCESS' in log}。
API使用现有FastAPI路由及真实Provider，测试夹具不作为live证据。
GET /api/screen是同步长任务，运行范围参数不是业务过滤规则。

## Tests
{tests}。原有测试均保留；历史T20旧AutoCoverage门槛标SUPERSEDED并保留SKIP。
初次Windows临时目录PermissionError已保留，改用项目内独立basetemp解决。

## Evidence Files
outputs/stage3c包含replay、small_live、full_market（实际启动后）、pytest、CLI/API和计时证据。
根目录CSV/JSON是最近阶段快照，scope见run_metadata.json；未完成快照不是全市场结果。

## Files Added / Updated
app/screening/，config/screening.yaml，app/cli.py，app/api.py，tests/test_screening.py，
真实回放fixtures，tests/test_spec_acceptance.py历史SKIP说明，tools/stage3c_*.py，README，Stage3C规范与报告。
核心评分引擎、规则权重、SectorHeat评分及Web UI未修改。

## Remaining Issues
真实全量运行及验收以状态和证据为准。外部网络、长历史获取和同步扫描耗时仍是实际限制。
任务未达到全部live门时保持PARTIAL；候选可以合法为零，不强行制造股票。

## Status
{status}
'''
    (ROOT/'docs/STAGE3C_RESULT.md').write_text(report,encoding='utf-8')
    print(json.dumps({k:v for k,v in meta.items() if k not in ('evidence_sha256','small_live','full_market')},ensure_ascii=False))

if __name__=='__main__':
    if '--watch' not in sys.argv:
        main()
    else:
        while True:
            main()
            full=read(OUT/'full_market/screening_details.json')
            log=(OUT/'live_log.txt').read_text('utf-8',errors='replace') if (OUT/'live_log.txt').exists() else ''
            if full.get('end_time') or 'Traceback (most recent call last)' in log:
                break
            time.sleep(30)
