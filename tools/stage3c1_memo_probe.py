"""Check a retained input fingerprint without recomputing a score."""
from pathlib import Path
import json,sqlite3
from unittest.mock import patch
from copy import deepcopy
import pandas as pd
import time
import argparse
from tools.stage3c1_benchmark import RecordedTransport,ROOT,DAY
from app.data.cache import DataCache
from app.screening.live import LiveScreeningAdapter
from app.screening.score_cache import ScoreMemo

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--score-proof',action='store_true');args=parser.parse_args()
    out=ROOT/'outputs/stage3c1'
    memo=ScoreMemo(out/'optimized_scores.sqlite3')
    a=LiveScreeningAdapter(RecordedTransport(ROOT/'data/cache/market.sqlite3'),
                          DataCache(out/'optimized_cache.sqlite3',ttl=86400),score_memo=memo)
    with patch.object(pd.Timestamp,'now',return_value=pd.Timestamp('2026-10-02 18:00',tz='Asia/Shanghai')):
        a.prepare()
        row=json.loads((out/'optimized/checkpoint_objects/sectors/C15.json').read_text('utf-8'))
        symbol='000568.SZ'
        loaded,status=a.analysis_service._load(symbol,DAY,False)
        context=loaded[1]
        context.metadata['industry_context']=deepcopy(row['context'])
        context.metadata['industry_context']['primary_industry']['symbol']=symbol
        context.metadata['symbol']=symbol
        key=memo.key(context,a.analysis_service.score_engine)
        with sqlite3.connect(memo.path) as db:
            found=db.execute('SELECT count(*) FROM score_memo_v1 WHERE key=?',(key,)).fetchone()[0]
        print('memo probe:',symbol,bool(found),key)
        if args.score_proof:
            from app.screening.runtime import RunControl,RuntimeLimits,bounded_score
            start=time.monotonic()
            actual=bounded_score(context,a.analysis_service.score_engine,RunControl(RuntimeLimits(run_seconds=300)))
            baseline=json.loads((out/'baseline/stock_details'/f'{symbol}.json').read_text('utf-8'))
            rules=lambda rs:{r['rule_id']:{k:r.get(k) for k in ('status','score','penalty','conditions')} for r in rs}
            equal=(actual['final_score']==baseline['final_quant_score'] and actual['risk_level']==baseline['risk_level']
                   and rules(actual['rules'])==rules(baseline['rules']))
            report=dict(mode='real-archive-pure-score-worker',symbol=symbol,seconds=time.monotonic()-start,
                        result_equivalent=equal,score=actual['final_score'],risk=actual['risk_level'],
                        rules_compared=len(actual['rules']),deadline_seconds=300,status='PASS' if equal else 'FAIL')
            (out/'bounded_score_real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(report)

if __name__=='__main__':main()
