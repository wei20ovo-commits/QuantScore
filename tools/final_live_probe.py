"""Two local real-stock calls at most; cache layers and dates stay explicit."""
from pathlib import Path
import json
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def worker(cache_file):
    from app.web_backend import _analyze_inprocess
    from app.data.cache import DataCache
    return _analyze_inprocess('600519',ROOT,DataCache(cache_file))

def main():
    from app.web_runtime import bounded_web_call
    from app.web_observability import run_observed_analysis,mark_analysis_execution
    from app.web_diagnostics import WebDataError
    out=ROOT/'outputs/final_engineering/local_live';out.mkdir(parents=True,exist_ok=True)
    cache=out/'real_market.sqlite3'
    if cache.exists():raise RuntimeError('Preserve previous evidence; no automatic real retry')
    runs=[]
    for label in ('cold_data_cache','warm_data_cache'):
        def load(_):
            mark_analysis_execution()
            return bounded_web_call(worker,(str(cache),),root=ROOT)
        started=perf_counter()
        try:
            result,diag=run_observed_analysis('600519',load)
            success=result['data_status']['status']!='UNAVAILABLE' and result['data_status']['is_mock'] is False
            row=dict(label=label,success=success,diagnostics=diag,
                symbol=result.get('symbol'),name=result.get('name'),trade_date=result.get('evaluation_date'),
                QuantScore=result.get('final_quant_score'),Risk=result.get('risk_level'),
                industry_context=result.get('industry_context'),rules=result['rules'],chart_rows=len(result.get('chart',[])))
        except WebDataError as exc:
            success=False;row=dict(label=label,success=False,diagnostics=exc.diagnostics)
        row['elapsed_seconds']=round(perf_counter()-started,4);runs.append(row)
        (out/'verification.json').write_text(json.dumps(dict(scope='REAL_LOCAL_PROVIDER',public_requests=0,ai_calls=0,runs=runs),
            ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
        if not success:break
    print(json.dumps(dict(local_live=[dict(label=r['label'],success=r['success'],seconds=r['elapsed_seconds']) for r in runs])))

if __name__=='__main__':main()
