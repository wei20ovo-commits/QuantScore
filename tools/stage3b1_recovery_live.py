"""Real FastAPI E2E with transparent request tracing, no substituted data."""
from pathlib import Path
import sys,json,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
from app.services.stock_analysis_service import StockAnalysisService
from app.api import create_app
from fastapi.testclient import TestClient
OUT=ROOT/'outputs/stage3b1_recovery'
def main():
    requests=[];original=BaoStockProvider._call_once
    def traced(self,method,**kwargs):
        row=dict(method=method,parameters=kwargs,timestamp=pd.Timestamp.now(tz='UTC').isoformat())
        try:
            data=original(self,method,**kwargs);row.update(status='SUCCESS',rows=len(data));return data
        except Exception as exc:row.update(status='FAILED',error=str(exc));raise
        finally:
            requests.append(row);(OUT/'wrapper_requests.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding='utf-8')
    BaoStockProvider._call_once=traced
    client=TestClient(create_app(StockAnalysisService()));rows=[]
    for code in ['600519','600688','600107']:
        print('Analyzing',code,flush=True)
        try:
            response=client.get('/api/analyze/'+code,params={'refresh':True});d=response.json()
            (OUT/(code+'_live.json')).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            if code=='600519':(OUT/'api_600519.json').write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            rules={r['rule_id']:r for r in d.get('rules',[])};i=d.get('industry_context',{});h=i.get('sector_heat')or{};b1=rules.get('B1',{});b2=rules.get('B2',{});raw=b2.get('raw_values',{})
            status=d.get('data_status',{});ok=response.status_code==200 and status.get('status')!='UNAVAILABLE' and status.get('is_mock') is False and h.get('overall_status')=='VALID' and b1.get('score') is not None and b2.get('score') is not None
            row=dict(symbol=d.get('symbol',code),stock_name=d.get('name'),industry=(i.get('primary_industry')or{}).get('name'),stock_data_status=status.get('status'),sector_data_status=h.get('overall_status'),SectorHeat=h.get('total_score'),B1_status=b1.get('status'),B1_score=b1.get('score'),B2_status=b2.get('status'),B2_score=b2.get('score'),stock_return_5d=raw.get('stock_return_5d'),industry_return_5d=raw.get('sector_return_5d'),relative_return_5d=raw.get('relative_return_5d'),QuantScore=d.get('final_quant_score'),Risk=d.get('risk_level'),provider=status.get('provider'),latest_trade_date=d.get('evaluation_date'),overall_analysis_status='SUCCESS' if ok else 'INCOMPLETE',http_status=response.status_code)
        except Exception as exc:row=dict(symbol=code,overall_analysis_status='ERROR',error=str(exc));traceback.print_exc()
        rows.append(row);pd.DataFrame(rows).to_csv(OUT/'live_smoke.csv',index=False);print(row,flush=True)
    assert len(rows)==3 and all(r['overall_analysis_status']=='SUCCESS' for r in rows)
if __name__=='__main__':main()
