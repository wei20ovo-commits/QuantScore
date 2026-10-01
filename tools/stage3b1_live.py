"""Three real stocks and actual FastAPI route acceptance, with original JSON evidence."""
from pathlib import Path
import sys,json
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from fastapi.testclient import TestClient
from app.services.stock_analysis_service import StockAnalysisService
from app.api import create_app
from app.engine.score_engine import ScoreEngine

def main():
    out=ROOT/'outputs/stage3b1';out.mkdir(exist_ok=True)
    service=StockAnalysisService();client=TestClient(create_app(service));rows=[]
    for symbol in ['600688','600258','600519']:
        print('Analyzing',symbol,flush=True)
        response=client.get('/api/analyze/'+symbol);data=response.json()
        (out/(symbol+'_analysis.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if response.status_code!=200:
            rows.append(dict(symbol=symbol,api_status=response.status_code,error=data))
            pd.DataFrame(rows).to_csv(out/'live_smoke.csv',index=False)
            print(rows[-1],flush=True)
            continue
        rules={r['rule_id']:r for r in data['rules']};industry=data.get('industry_context',{});heat=industry.get('sector_heat') or {}
        row=dict(symbol=data['symbol'],name=data['name'],provider=data['data_status']['provider'],is_mock=data['data_status']['is_mock'],trade_date=data['evaluation_date'],
            primary_industry=(industry.get('primary_industry') or {}).get('name'),sector_heat_status=heat.get('overall_status'),sector_heat_score=heat.get('total_score'),
            B1_score=rules['B1']['score'],B1_status=rules['B1']['status'],B1_reason=rules['B1']['reason_code'],B2_score=rules['B2']['score'],B2_status=rules['B2']['status'],B2_reason=rules['B2']['reason_code'],
            quant_score=data['final_quant_score'],api_status=response.status_code,retrieved_at=datetime.now(timezone.utc).isoformat())
        # Same underlying stock snapshot; adding industry must not alter any other evaluator.
        loaded,status=service._load(symbol) if data.get('evaluation_date') else (None,None)
        if loaded:
            loaded[1].metadata['score_snapshots']=service.provider_manager.cache.score_snapshots(status.symbol)
            baseline=service.score_engine.evaluate(loaded[1]);old={r['rule_id']:r for r in baseline['rules']}
            compared=[rid for rid in old if rid not in ('B1','B2')]
            row['other_rule_scores_unchanged']=all((old[rid]['score'],old[rid]['penalty'],old[rid]['status'])==(rules[rid]['score'],rules[rid]['penalty'],rules[rid]['status']) for rid in compared)
            row['baseline_without_B1_B2']=baseline['quant_score']
        rows.append(row);pd.DataFrame(rows).to_csv(out/'live_smoke.csv',index=False)
        print(row,flush=True)
    assert len(rows)==3 and all(r.get('is_mock') is False and r.get('provider')=='baostock' and r.get('primary_industry') for r in rows)
    assert all(r['B2_score'] is not None for r in rows)
    assert any(r['sector_heat_status']=='VALID' and r['B1_score'] is not None for r in rows)
    small=next(r for r in rows if r['symbol']=='600258.SH')
    assert small['sector_heat_status']=='DATA_INCOMPLETE' and small['B1_score'] is None
    assert all(r['other_rule_scores_unchanged'] for r in rows)

if __name__=='__main__':main()
