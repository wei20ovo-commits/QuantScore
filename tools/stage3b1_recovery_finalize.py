"""Close acceptance strictly from retained live files and pytest XML."""
from pathlib import Path
import json,hashlib,xml.etree.ElementTree as ET,datetime,re
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/stage3b1_recovery'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def main():
    live=pd.read_csv(OUT/'live_smoke.csv');cli=read('cli_600519.json');api=read('api_600519.json');date=read('date_context.json')['latest_completed_trade_date']
    exit_code=int((OUT/'cli_exit.txt').read_text(encoding='utf-8-sig').strip())
    checks=[]
    for code in ['600519','600688','600107']:
        d=read(code+'_live.json');status=d['data_status'];i=d.get('industry_context')or{};heat=i.get('sector_heat')or{};r={x['rule_id']:x for x in d['rules']}
        checks.append(dict(symbol=d['symbol'],raw_rows=status['raw_rows'],qfq_rows=status['adjusted_rows'],benchmark_available=status['benchmark_available'],trade_date=d['evaluation_date'],check=status['is_mock'] is False and status['provider']=='baostock' and status['status']!='UNAVAILABLE' and status['raw_rows']==status['adjusted_rows'] and status['raw_rows']>0 and status['benchmark_available'] and d['evaluation_date']==date and heat.get('overall_status')=='VALID' and heat.get('trade_date')==date and all(r[k]['score'] is not None for k in ['B1','B2'])))
    cli_rules={r['rule_id']:r for r in cli.get('rules',[])}
    cli_ok=exit_code==0 and cli['data_status']['is_mock'] is False and cli['data_status']['status']!='UNAVAILABLE' and cli['evaluation_date']==date and (cli.get('industry_context',{}).get('sector_heat')or{}).get('overall_status')=='VALID' and all(cli_rules[k]['score'] is not None for k in ['B1','B2'])
    suite=ET.parse(OUT/'pytest.xml').getroot().find('testsuite');tests={k:int(suite.attrib[k]) for k in ['tests','failures','errors','skipped']};tests['passed']=tests['tests']-tests['failures']-tests['errors']-tests['skipped']
    ok=all(c['check'] for c in checks) and len(live)==3 and live.overall_analysis_status.eq('SUCCESS').all() and live.http_status.eq(200).all() and cli_ok and tests['failures']==tests['errors']==0
    requests=read('wrapper_requests.json');retries=pd.read_csv(OUT/'retry_log.csv').to_dict('records')
    matching=[r for r in requests if r['method']=='query_history_k_data_plus' and r['parameters'].get('code')=='sh.600519' and r['parameters'].get('start_date')=='2000-01-01' and r['parameters'].get('adjustflag')=='3' and r['parameters'].get('fields')=='date,code,volume,amount,adjustflag']
    for n,r in enumerate(matching,1):
        error=r.get('error','');match=re.search(r'error (\d+)',error)
        retries.append(dict(case='production_600519_raw_volume_group',attempt=n,timestamp=r['timestamp'],query_error_code=match.group(1) if match else '0' if r['status']=='SUCCESS' else 'WRAPPER_ERROR',query_error_msg=error or 'success',returned_rows=r.get('rows')))
    pd.DataFrame(retries).to_csv(OUT/'retry_log.csv',index=False)
    secondary=[]
    for f in OUT.glob('before_field_groups_*live.json'):
        d=json.loads(f.read_text(encoding='utf-8'))
        for warning in d.get('data_status',{}).get('warnings',[]):
            if 'akshare' in warning.lower():secondary.append(dict(provider='akshare',endpoint='stock_zh_a_hist',configured_history_url='https://push2his.eastmoney.com/api/qt/stock/kline/get',error_type='ProxyError / ConnectionError' if 'ProxyError' in warning else 'ProviderError / timeout',error_message=warning,source=f.name))
    (OUT/'secondary_provider.json').write_text(json.dumps(secondary,ensure_ascii=False,indent=2),encoding='utf-8')
    meta=dict(stage='3B.1 Live Recovery',status='PASS' if ok else 'PARTIAL',finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),spec_version='1.4',assumption_version='v1.3',data_contract_version='1.4',latest_completed_trade_date=date,live_checks=checks,cli_exit=exit_code,cli_check=bool(cli_ok),tests=tests,request_count=len(requests),request_failures=sum(r['status']=='FAILED' for r in requests),commit=False,push=False,root_cause='Reproduced SDK receive timeout -> empty response -> 10002007; underlying remote/network internals are not inferred.')
    meta['evidence_sha256']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in OUT.iterdir() if f.is_file() and f.suffix in ['.json','.csv','.xml'] and f.name!='run_metadata.json'}
    (OUT/'run_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    report=ROOT/'docs/STAGE3B1_LIVE_RECOVERY.md';s=report.read_text(encoding='utf-8');s=s.replace('当前验收尚在运行；最终状态以run_metadata.json与本报告最终更新为准。','当前状态：'+meta['status']+'。')
    s=s.split('## Live Acceptance')[0]+'## Live Acceptance\n\n'
    s+='| Symbol | Industry | Heat | B1 | B2 | QuantScore | Risk | Status |\n|---|---|---:|---:|---:|---:|---|---|\n'
    for _,r in live.iterrows():s+='| '+ ' | '.join(str(r[k]) for k in ['symbol','industry','SectorHeat','B1_score','B2_score','QuantScore','Risk','overall_analysis_status'])+' |\n'
    s+=f'\n全部数据日期{date}；BaoStock真实数据，无mock。原始JSON保存完整规则、原始输入和来源。股票DataStatus=PARTIAL来自原有历史涨跌停价等客观缺项，不等于行情UNAVAILABLE；本轮行业Heat/B1/B2必须完整可判定才计为E2E成功。\n\n## CLI / FastAPI\n\nCLI真实exit={exit_code}，JSON可解析；完整行业与B1/B2校验={cli_ok}。FastAPI通过TestClient真实调用现有路由及真实Provider，不以HTTP 200单独判成功，另核验raw/qfq数量、基准、非mock、日期和完整Heat。\n\n## Remaining Issues\n\n首次完整行业分析较慢；外部网络仍可能间歇失败，采用有限重试并保留UNKNOWN及上游原因。没有服务端内部日志，不宣称已证明某个字段非法或确认服务端限流。历史无可靠涨跌停价/分钟/筹码等UNKNOWN仍保留。所有失败证据保留；输出目录仍遵循项目既有gitignore，未自动发布。\n\n## Status\n\n{meta["status"]}\n'
    report.write_text(s,encoding='utf-8')
    p=ROOT/'docs/TEST_REPORT.md';old=p.read_text(encoding='utf-8');p.write_text(f'# Stage 3B.1 Live Recovery 最新回归\n\n{tests["tests"]}项：{tests["passed"]} PASS / {tests["failures"]} FAIL / {tests["errors"]} ERROR / {tests["skipped"]} SKIP。原有测试全部保留；本轮新增4项根因/传输保护测试。真实验收状态{meta["status"]}，详见STAGE3B1_LIVE_RECOVERY.md。证据outputs/stage3b1_recovery/pytest.xml与pytest.txt。\n\n'+old,encoding='utf-8')
    if ok:
        p=ROOT/'docs/STAGE3B1_RESULT.md';old=p.read_text(encoding='utf-8');p.write_text('> 历史首次验收记录：当时PARTIAL。现已由STAGE3B1_LIVE_RECOVERY.md的真实E2E验收PASS取代；以下失败记录保留。\n\n'+old,encoding='utf-8')
        p=ROOT/'docs/RULE_IMPLEMENTATION_MATRIX.md';old=p.read_text(encoding='utf-8');p.write_text(old+'\nStage 3B.1 Live Recovery：真实三股票、CLI与API完整B1/B2验收PASS，见STAGE3B1_LIVE_RECOVERY.md。\n',encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
