"""Read-only adapter for Stage 3A evidence; does not fetch or modify archives."""
from pathlib import Path
import json
import pandas as pd
from .models import SectorRuleInput
from .scoring import SectorHeatEngine

def records(frame):
    return json.loads(frame.to_json(orient='records',force_ascii=False,double_precision=15))

def load_archive(directory):
    path=Path(directory)
    tables={f'S{i}':pd.read_csv(path/f's{i}_inputs.csv') for i in range(1,8)}
    limits=pd.read_csv(path/'s4_constituent_details.csv')
    amount=pd.read_csv(path/'s5_daily_amounts.csv')
    daily=pd.read_csv(path/'s6_daily_comparisons.csv')
    results=[]
    for sector in tables['S1'].industry:
        inputs={}
        for rid,table in tables.items():
            subset=table[table.industry.eq(sector)]
            if len(subset)!=1:raise ValueError('Missing/duplicate industry row')
            raw=records(subset)[0];day=raw['trade_date']
            if rid=='S4':raw['limit_details']=records(limits[limits.industry.eq(sector)])
            if rid=='S5':raw['daily_amounts']=records(amount[amount.industry.eq(sector)].sort_values('date'))
            if rid=='S6':
                raw['daily_comparisons']=records(daily[daily.industry.eq(sector)].sort_values('date'))
                raw['expected_trade_dates']=[r['date'] for r in raw['daily_comparisons']]
                raw['win_days']=raw['win_count']
            inputs[rid]=SectorRuleInput(raw,day,raw['status'])
        results.append((sector[:3],sector,inputs['S1'].source_date,inputs))
    return results

def replay(directory,provenance=None):
    engine=SectorHeatEngine()
    return [engine.evaluate(sid,name,day,inputs,provenance or {'provider':'baostock','source':'Stage35 archived real data','network_used':False})
            for sid,name,day,inputs in load_archive(directory)]

def write_results(results,directory):
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    details=[r.to_dict() for r in results]
    (path/'sector_heat_details.json').write_text(json.dumps(details,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    rows=[]
    for r in results:
        rows.append(dict(sector=r.sector_name,trade_date=r.trade_date,**{f's{i}_score':getattr(r,f's{i}').score for i in range(1,8)},
             total_score=r.total_score,max_score=r.max_score,available_score=r.available_score,available_max_score=r.available_max_score,score_coverage=r.score_coverage,status=r.overall_status))
    pd.DataFrame(rows).to_csv(path/'sector_heat_results.csv',index=False)
