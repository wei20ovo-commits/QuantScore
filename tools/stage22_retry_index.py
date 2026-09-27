"""Repeat the failed live index acceptance, retaining prior attempt evidence."""
import json
from datetime import datetime,timezone
from pathlib import Path
from app.data.provider_manager import ProviderManager
from app.services.stock_analysis_service import StockAnalysisService
from tools.stage22_smoke import verify_averages

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    path=root/'outputs/smoke/stage2_smoke_report.json'
    report=json.loads(path.read_text('utf-8'))
    manager=ProviderManager(retries=2)
    result=StockAnalysisService(manager).analyze('000001.SH',refresh=True)
    data=manager.fetch('000001.SH')
    previous=report['cases'][2]
    case=dict(previous)
    case['previous_attempts']=[previous]
    case['retry_at']=datetime.now(timezone.utc).isoformat()
    case['analysis']=result.to_dict()
    case['actual_provider']=data.metadata['provider']
    case['ma_verification']=verify_averages(data.bars)
    case['benchmark_last_date']=str(data.benchmark.date.iloc[-1].date()) if data.benchmark is not None else None
    row=data.bars.iloc[-1]
    case['latest_values']={k:None if __import__('pandas').isna(row[k]) else float(row[k]) for k in ['close_raw','close_adj','volume','turnover_rate']}
    case['status']='PASS' if result.data_status.status!='UNAVAILABLE' and result.data_status.benchmark_available and data.metadata['provider']=='baostock' and case['ma_verification']['status']=='PASS' else 'PARTIAL'
    data.bars.to_csv(root/'outputs/smoke/000001.SH_baostock_bars.csv',index=False)
    report['cases'][2]=case
    report['status']='PASS' if all(c['status']=='PASS' for c in report['cases']) and all(c.get('exit_code')==0 for c in report['cli']) and report['api']['/api/analyze/600519']['http_status']==200 and report['api']['/api/analyze/600519']['data_status'] in ['PARTIAL','AVAILABLE'] else 'PARTIAL'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':report['status'],'index_rows':len(data.bars),'index_status':case['status'],'ma_status':case['ma_verification']['status']},ensure_ascii=False))
