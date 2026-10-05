"""Stage4C.2 replay/equivalence and genuine controlled cold/warm diagnostics.

Replay uses archived real cache frames, explicitly disables networking and never
claims to be live. Live uses an empty diagnostic cache and actual BaoStock.
No API credentials or AI calls are needed. No commit/push/deployment performed.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'outputs/stage4c2'
SOURCE=ROOT/'outputs/stage4c1/completion/local/fresh-15e72ba073e648b48e300fe7f1f6c3e4.sqlite3'


def save(name,value):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')


def without_acquisition(value):
    # Only acquisition evidence differs. No values, conditions, reasons, dates,
    # statuses, scores, penalties or explanation strings are normalized.
    if isinstance(value,dict):
        return {k:without_acquisition(v) for k,v in value.items()
                if k not in ('data_provenance','provenance','primary_industry_provenance')}
    if isinstance(value,list):return [without_acquisition(v) for v in value]
    return value


def differences(a,b,path=''):
    if type(a)!=type(b):return [path+':type']
    if isinstance(a,dict):
        result=[]
        for k in sorted(set(a)|set(b)):
            if k not in a or k not in b:result.append(path+'.'+k+':missing')
            else:result.extend(differences(a[k],b[k],path+'.'+k))
        return result
    if isinstance(a,list):
        if len(a)!=len(b):return [path+':length']
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in differences(x,y,f'{path}[{i}]')]
    return [] if a==b else [path]


def clone(source,target):
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:src.backup(dst)


def replay():
    from app.data.baostock_provider import BaoStockProvider
    from app.data.cache import DataCache
    from app.data.provider_manager import ProviderManager
    from app.sector.industry_context import PrimaryIndustryService
    from app.services.stock_analysis_service import StockAnalysisService
    from app.web_backend import create_web_service,_analyze_inprocess
    from unittest.mock import patch
    OUT.mkdir(parents=True,exist_ok=True)
    before=sha256(SOURCE.read_bytes()).hexdigest()
    original_path=OUT/'replay_original.sqlite3';optimized_path=OUT/'replay_optimized.sqlite3'
    clone(SOURCE,original_path);clone(SOURCE,optimized_path)
    # Archived cache is intentionally replayed without production TTL. This
    # clock is diagnostic-only and is never installed in the Web application.
    oldcache=DataCache(original_path,ttl=float('inf'),clock=lambda:0)
    newcache=DataCache(optimized_path,ttl=float('inf'),clock=lambda:0)
    with patch.object(BaoStockProvider,'_call',side_effect=AssertionError('REPLAY_MUST_NOT_NETWORK')):
        t=perf_counter()
        original=StockAnalysisService(ProviderManager(cache=oldcache)).analyze('600519').to_dict()
        oldseconds=perf_counter()-t
        t=perf_counter();service=create_web_service(ROOT,newcache)
        optimized=_analyze_inprocess('600519',service=service)
        newseconds=perf_counter()-t
    paths={}
    for field in ('final_quant_score','risk_level','positive_score','risk_penalty','price','indicators','market',
                  'positive_coverage','risk_coverage','score_status','industry_context','rules','score'):
        paths[field]=differences(without_acquisition(original[field]),without_acquisition(optimized[field]),field)
    rules={r['rule_id']:not paths['rules'] or without_acquisition(r)==without_acquisition(optimized['rules'][i])
           for i,r in enumerate(original['rules'])}
    record=dict(status='PASS' if not any(paths.values()) and len(rules)==41 else 'FAIL',
        scope='OFFLINE REPLAY OF ARCHIVED REAL FRAMES; NOT LIVE',trade_date=original['evaluation_date'],
        source=SOURCE.relative_to(ROOT).as_posix(),source_hash_before=before,
        source_hash_after=sha256(SOURCE.read_bytes()).hexdigest(),
        baseline_seconds=round(oldseconds,4),optimized_seconds=round(newseconds,4),
        quant_score=optimized['final_quant_score'],risk=optimized['risk_level'],
        sector_heat=optimized['industry_context'].get('sector_heat',{}).get('total_score'),
        rules_equal=rules,differences=paths,
        exclusions=['data_provenance','provenance','primary_industry_provenance'],
        equivalence='Only source acquisition evidence is excluded; all business fields and explanations must match exactly')
    save('equivalence.json',record);save('replay_original.json',original);save('replay_optimized.json',optimized)
    print(json.dumps({k:record[k] for k in ('status','baseline_seconds','optimized_seconds','quant_score','risk','sector_heat','differences')},ensure_ascii=True),flush=True)
    return record


def live():
    from app.data.cache import DataCache
    from app.web_backend import _analyze_inprocess
    from app.web_runtime import bounded_web_call
    from app.web_visuals import candle_chart
    import uuid
    cache=OUT/('live-'+uuid.uuid4().hex+'.sqlite3')
    record=dict(scope='LOCAL genuine 600519; controlled empty cache then same persistent cache; NOT PUBLIC',
                started_at=datetime.now(timezone.utc).isoformat(),is_mock=False,api_calls=0,runs={})
    for label in ('cold','warm'):
        t=perf_counter()
        # Construct DataCache inside the spawned worker so no unpicklable object
        # or open database/network handle crosses the process boundary.
        try:
            output=bounded_web_call(live_worker,('600519',cache.as_posix()),root=ROOT)
            figure_started=perf_counter();figure=candle_chart(output.get('chart',[]))
            figure_seconds=perf_counter()-figure_started
            item=dict(total_seconds=round(perf_counter()-t,4),chart_figure_seconds=round(figure_seconds,4),
                symbol=output['symbol'],name=output['name'],trade_date=output['evaluation_date'],
                data_status=output['data_status']['status'],provider=output['data_status']['provider'],
                is_mock=output['data_status']['is_mock'],quant_score=output['final_quant_score'],risk=output['risk_level'],
                sector_heat=output['industry_context'].get('sector_heat',{}).get('total_score'),
                rule_count=len(output['rules']),chart_points=len(output.get('chart',[])),
                **output.get('web_latency',{}))
            record['runs'][label]=item;save('live_'+label+'.json',output)
            if item['data_status']=='UNAVAILABLE' or item['is_mock'] or item['chart_points']!=120:
                raise RuntimeError('GENUINE_STOCK_ANALYSIS_UNAVAILABLE')
            print(json.dumps({'run':label,**item},ensure_ascii=True),flush=True)
        except Exception as exc:
            record['runs'][label]={'status':'FAILED','error_type':type(exc).__name__,'total_seconds':round(perf_counter()-t,4)}
            record['status']='PARTIAL';save('local_latency.json',record);return record
        save('local_latency.json',record)
    record['status']='PASS';record['completed_at']=datetime.now(timezone.utc).isoformat()
    save('local_latency.json',record)
    return record


def live_worker(code,cache):
    from app.data.cache import DataCache
    from app.web_backend import _analyze_inprocess
    return _analyze_inprocess(code,ROOT,DataCache(cache))


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    temp=ROOT/'outputs/tmp/stage4c2';temp.mkdir(parents=True,exist_ok=True)
    os.environ.update({k:str(temp) for k in ('TMP','TEMP','TMPDIR')})
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['replay','live'])
    result=replay() if parser.parse_args().mode=='replay' else live()
    sys.exit(0 if result['status']=='PASS' else 1)
