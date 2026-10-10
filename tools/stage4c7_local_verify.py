"""Controlled local worker evidence only; no live market, AI or Cloud requests."""
import json
import logging
import os
import sys
from pathlib import Path
from time import perf_counter

from app.web_deployment import deployment_identity
from app.web_diagnostics import WebDataError, current_request, emit, safe_event
from app.web_observability import run_observed_analysis, mark_analysis_execution
from app.web_runtime import bounded_web_call

ROOT=Path(__file__).resolve().parents[1]


def controlled_success():
    events=[]
    for adjustment in ('raw','qfq'):
        events.append(emit(safe_event('fetch_group','START',adjustment=adjustment)))
        events.append(emit(safe_event('fetch_group','OK',adjustment=adjustment,seconds=.001)))
    events.append(emit(safe_event('rule_scoring','OK')))
    return {'observability_fixture':True,'data_status':{'status':'AVAILABLE'},
        'evaluation_date':'2026-10-09','web_diagnostics':{'request_id':current_request(),
        'events':events,'reason_code':'NONE','fetch_attempts_observed':True,'provider_requests_observed':True,
        'industry_snapshot_date':'2026-09-30','benchmark_snapshot_date':'2026-09-30',
        'industry_data_status':'DATA_STALE','provider_requests':0,'provider_timeouts':0}}


def controlled_failure():
    emit(safe_event('context','OK',industry_snapshot_date='2026-09-30',benchmark_snapshot_date='2026-09-30'))
    emit(safe_event('fetch_group','START',adjustment='raw'))
    emit(safe_event('provider_request','FAILED',provider='baostock',reason_code='PROVIDER_CONNECTION_ERROR'))
    raise ConnectionError('Controlled failure; not a real provider request')


def controlled_timeout():
    import time
    emit(safe_event('context','OK',industry_snapshot_date='2026-09-30',benchmark_snapshot_date='2026-09-30'))
    emit(safe_event('fetch_group','START',adjustment='qfq'))
    time.sleep(30)


class Capture(logging.Handler):
    def __init__(self):super().__init__(logging.WARNING);self.events=[]
    def emit(self,record):
        text=record.getMessage()
        if text.startswith('QUANTSCORE_WEB_DIAGNOSTIC '):
            self.events.append(json.loads(text.split(' ',1)[1]))


def main():
    out=ROOT/'outputs/stage4c7';out.mkdir(parents=True,exist_ok=True)
    temporary=ROOT/'outputs/tmp/stage4c7-local';temporary.mkdir(parents=True,exist_ok=True)
    os.environ.update({k:str(temporary) for k in ('TMP','TEMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(temporary)
    logger=logging.getLogger('app.web_diagnostics');capture=Capture();logger.addHandler(capture)
    identity=deployment_identity(ROOT);runs=[]
    try:
        for name,target in [('success',controlled_success),('failure',controlled_failure),('timeout',controlled_timeout)]:
            def loader(_):
                mark_analysis_execution()
                return bounded_web_call(target,(),root=ROOT,seconds=8 if name=='timeout' else 20)
            started=perf_counter()
            try:
                _,summary=run_observed_analysis('600519',loader,deployment=identity)
            except WebDataError as exc:summary=exc.diagnostics
            runs.append({'path':name,'observability_fixture':True,'wall_seconds':round(perf_counter()-started,4),
                         'diagnostics':summary})
        result={'acceptance_scope':'LOCAL_CONTROLLED_WORKERS_NOT_REAL_MARKET_OR_PUBLIC_ACCEPTANCE',
            'public_requests':0,'api_calls':0,'deployment':identity,'logger_effective_level':logger.getEffectiveLevel(),
            'runs':runs,'parent_log_events':capture.events}
        filename='local_smoke_final.json' if '--final' in sys.argv else 'local_smoke.json'
        (out/filename).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        assert [r['diagnostics']['outcome'] for r in runs]==['SUCCESS','FAILURE','TIMEOUT']
        assert all(any(e.get('request_id')==r['diagnostics']['request_id'] and e.get('layer')=='WEB'
                       for e in capture.events) for r in runs)
        print(json.dumps({'local_controlled_smoke':'PASS','outcomes':[r['diagnostics']['outcome'] for r in runs]}))
    finally:logger.removeHandler(capture)


if __name__=='__main__':main()
