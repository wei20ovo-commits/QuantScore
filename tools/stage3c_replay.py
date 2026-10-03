"""Run deterministic real archived screening without network access."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.screening.replay import ArchivedScreeningAdapter
from app.screening.service import ScreeningService

def main():
    adapter=ArchivedScreeningAdapter(ROOT)
    out=ROOT/'outputs/stage3c/replay'
    result=ScreeningService(adapter).run(output_dir=out)
    rows=[]
    for symbol,analysis in adapter.analyses.items():
        primary=analysis['industry_context']['primary_industry']
        state,quality,explanation=ScreeningService(adapter).policy.stock(analysis,result['trade_date'],primary['sector_id'])
        rows.append(dict(symbol=symbol,sector_id=primary['sector_id'],candidate_status=state,
                         data_status=quality,QuantScore=analysis['final_quant_score'],explanation=explanation,
                         source='archived-real-stock-diagnostic-not-production-scan'))
    pd.DataFrame(rows).to_csv(ROOT/'outputs/stage3c/replay_screening.csv',index=False)
    assert adapter.stage35['H61']['total_score'] is None
    assert not result['candidates']
    print(result['status'],result['stats'])

if __name__=='__main__':main()
