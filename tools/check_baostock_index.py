from app.data.provider_manager import ProviderManager
from app.services.stock_analysis_service import StockAnalysisService
if __name__=='__main__':
    import traceback
    try:
        manager=ProviderManager()
        d=manager.fetch('000001.SH')
        print('FETCH',len(d.bars),d.metadata['provider'])
        r=StockAnalysisService(manager).analyze('000001.SH')
        print('ANALYSIS',r.data_status.status,r.name)
    except Exception:traceback.print_exc()
