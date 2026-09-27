from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request
from app.data.models import BENCHMARK_SYMBOL, DataError
from app.models.schemas import AnalysisResult, DataStatus
from app.services.stock_analysis_service import StockAnalysisService


def get_service(request: Request):
    # 延迟初始化，健康检查和模块导入不访问行情源或创建缓存。
    service = request.app.state.analysis_service
    if service is None:
        service = StockAnalysisService()
        request.app.state.analysis_service = service
    return service


def create_app(service=None):
    application = FastAPI(title='QuantScore', version='1.4.0')
    application.state.analysis_service = service

    @application.get('/api/health')
    def health():
        from pathlib import Path
        import yaml
        order = yaml.safe_load((Path(__file__).resolve().parents[1]/'config/data_providers.yaml').read_text('utf-8'))['provider_order']
        return {'status': 'ok', 'spec_version': '1.4', 'assumption_version':'v1.3', 'data_contract_version':'1.4', 'benchmark_symbol': BENCHMARK_SYMBOL, 'benchmark_name': '上证指数',
                'benchmark': {'symbol':BENCHMARK_SYMBOL,'name':'上证指数'},
                'provider_status': {'provider':service.provider_manager.provider.name if service else order[0], 'configured_order':order, 'status':'NOT_PROBED'}}

    @application.get('/api/rules')
    def rules():
        from app.engine.rule_engine import RuleEngine
        engine = service.rule_engine if service is not None else RuleEngine()
        return {'spec_version': '1.4', 'assumption_version':'v1.3', 'data_contract_version':'1.4', 'rules': list(engine.registry.values())}

    @application.get('/api/analyze/{symbol}', response_model=AnalysisResult)
    # V1.4：symbol 为个股输入；000001.SH/benchmark alias 才表示上证指数。
    def analyze(symbol: str, as_of: date | None = None, refresh: bool = False,
                analysis_service=Depends(get_service)):
        try:
            return analysis_service.analyze(symbol, as_of=as_of.isoformat() if as_of else None, refresh=refresh)
        except DataError as exc:
            raise HTTPException(status_code=422, detail={'code': exc.code, 'message': str(exc)}) from exc

    @application.get('/api/data/status/{symbol}', response_model=DataStatus)
    def data_status(symbol: str, as_of: date | None = None, refresh: bool = False,
                    analysis_service=Depends(get_service)):
        try:
            return analysis_service.data_status(symbol, as_of=as_of.isoformat() if as_of else None, refresh=refresh)
        except DataError as exc:
            raise HTTPException(status_code=422, detail={'code': exc.code, 'message': str(exc)}) from exc

    return application


app = create_app()
