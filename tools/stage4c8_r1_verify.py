"""Controlled offline request evidence; zero Cloud/market/LLM requests."""
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def main():
    from app.data.models import DataError
    from app.data.cache import DataCache
    from app.web_backend import analyze_stock,create_web_service,normalize_stock_code
    from app.web_diagnostics import WebDataError
    from app.web_observability import run_observed_analysis,mark_analysis_execution
    from app.web_runtime import bounded_web_call
    from tools.stage4c8_r1_workers import offline_result
    sys.path.insert(0,str(ROOT/'tests'))
    from test_stage2_service import service
    out=ROOT/'outputs/stage4c8_r1';temporary=ROOT/'outputs/tmp/stage4c8-r1/smoke'
    temporary.mkdir(parents=True,exist_ok=True)
    os.environ.update({k:str(temporary) for k in ('TMP','TEMP','TMPDIR')})
    rows=[];logged=[]
    class Capture(logging.Handler):
        def emit(self,record):
            message=record.getMessage()
            if message.startswith('QUANTSCORE_WEB_DIAGNOSTIC '):
                logged.append(json.loads(message.split(' ',1)[1]))
    logger=logging.getLogger('app.web_diagnostics');capture=Capture();logger.addHandler(capture)
    def loader(code):mark_analysis_execution();return analyze_stock(code)
    def run(label,call):
        try:value,diag=call()
        except WebDataError as exc:value=None;diag=exc.diagnostics
        rows.append(dict(path=label,OFFLINE_CONTROLLED=True,diagnostics=diag))
        return value
    try:
        run('web_preprocess_failure',lambda:run_observed_analysis('bad',loader,preprocess=normalize_stock_code))
        with patch('app.web_backend.create_web_service',side_effect=DataError('OFFLINE_PRIVATE_SENTINEL')):
            run('pre_worker_service_failure',lambda:run_observed_analysis('600519',loader))
        prototype=SimpleNamespace(provider_manager=SimpleNamespace(provider=SimpleNamespace(is_mock=True)))
        with patch('app.web_backend.create_web_service',return_value=prototype):
            run('provider_policy_rejected',lambda:run_observed_analysis('600519',loader))
        def initialize():return create_web_service(ROOT,DataCache(temporary/'init.sqlite'))
        with patch('app.web_backend.create_web_service',side_effect=initialize), \
             patch('app.data.provider_manager.ProviderManager',side_effect=ValueError('OFFLINE_PRIVATE_SENTINEL')):
            run('provider_config_rejected',lambda:run_observed_analysis('600519',loader))
        def worker_loader(_):
            mark_analysis_execution();return bounded_web_call(offline_result,('never-read.json',),root=temporary)
        with patch('multiprocessing.context.SpawnProcess.start',side_effect=PermissionError('OFFLINE_PRIVATE_SENTINEL')):
            run('worker_start_failed',lambda:run_observed_analysis('600519',worker_loader))
        engine=service.__wrapped__(temporary)
        baseline=engine.analyze('000001').to_dict()
        for status in ('AVAILABLE','UNAVAILABLE'):
            value=deepcopy(baseline);value['data_status']['status']=status
            payload=temporary/(status+'.json');payload.write_text(json.dumps(value),'utf-8')
            def completed(_):
                mark_analysis_execution();return bounded_web_call(offline_result,(str(payload),),root=temporary,seconds=20)
            result=run('worker_'+status.lower(),lambda:run_observed_analysis('000001',completed))
            assert result['rules']==baseline['rules'] and len(result['rules'])==41
        (out/'local_boundary_smoke.json').write_text(json.dumps(dict(scope='LOCAL_OFFLINE_ONLY',
            public_requests=0,market_requests=0,api_calls=0,runs=rows,logs=logged),indent=2),'utf-8')
        assert len(rows)==7 and all(any(e.get('event_type')=='REQUEST_COMPLETE' and e['request_id']==r['diagnostics']['request_id']
                                      for e in logged) for r in rows)
        print(json.dumps(dict(local_smoke='PASS',paths=len(rows),public_requests=0,api_calls=0)))
    finally:logger.removeHandler(capture)


if __name__=='__main__':main()
