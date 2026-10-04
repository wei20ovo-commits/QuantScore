"""Real archived-input interruption/resume proof; not a live market scan."""
import json
from copy import deepcopy
from unittest.mock import patch
import pandas as pd
from tools.stage3c1_benchmark import RecordedTransport,ROOT,SECTORS
from app.data.cache import DataCache
from app.screening.history_cache import HistoryCache
from app.screening.score_cache import ScoreMemo
from app.screening.live import LiveScreeningAdapter
from app.screening.service import ScreeningService


class Observed(LiveScreeningAdapter):
    def __init__(self,interrupt=False):
        out=ROOT/'outputs/stage3c1'
        super().__init__(RecordedTransport(ROOT/'data/cache/market.sqlite3'),
            DataCache(out/'optimized_cache.sqlite3',ttl=86400),
            history_cache=HistoryCache(out/'optimized_history.sqlite3',ttl=86400),
            score_memo=ScoreMemo(out/'optimized_scores.sqlite3'))
        self.mode='real-archive-checkpoint-resume'
        self.interrupt=interrupt;self.sector_calls=[];self.stock_calls=[]

    def sector(self,sid,*a,**kw):
        self.sector_calls.append(sid);return super().sector(sid,*a,**kw)

    def stock(self,symbol,*a,**kw):
        if self.interrupt and self.stock_calls:
            raise KeyboardInterrupt('Controlled interruption after first completed real stock')
        self.stock_calls.append(symbol);return super().stock(symbol,*a,**kw)


def main():
    out=ROOT/'outputs/stage3c1';directory=out/'resume_real'
    with patch.object(pd.Timestamp,'now',return_value=pd.Timestamp('2026-10-02 18:00',tz='Asia/Shanghai')):
        before=Observed(True)
        try:ScreeningService(before).run(industry_ids=SECTORS,output_dir=directory)
        except KeyboardInterrupt:pass
        manifest=json.loads((directory/'checkpoint.json').read_text('utf-8'))
        after=Observed()
        result=ScreeningService(after).run(industry_ids=SECTORS,output_dir=directory,resume=True)
    fields=('symbol','sector_heat','B1','B2','QuantScore','Risk','candidate_status','data_status')
    business=lambda result:{r['symbol']:{k:r.get(k) for k in fields} for r in result['stocks']}
    baseline=json.loads((out/'baseline/screening_details.json').read_text('utf-8'))
    report=dict(mode='real-archive-replay',is_live_network=False,
                completed_before_interrupt=dict(sectors=len(manifest['objects']['sectors']),stocks=len(manifest['objects']['stocks'])),
                resumed_sector_calls=after.sector_calls,resumed_stock_calls=after.stock_calls,
                final_stats=result['stats'],result_equivalent=business(result)==business(baseline),
                date=result['trade_date'],versions={k:result[k] for k in ('spec_version','assumption_version','data_contract_version')})
    report['status']='PASS' if not after.sector_calls and len(after.stock_calls)==46 and report['result_equivalent'] else 'FAIL'
    (out/'checkpoint_resume_test.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['status'],report['completed_before_interrupt'],len(after.stock_calls))

if __name__=='__main__':main()
