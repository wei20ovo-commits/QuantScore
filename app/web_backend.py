"""Thin public Web adapter: no score calculations and no synthetic data."""
import re
from app.data.models import DataError
from app.services.stock_analysis_service import StockAnalysisService


def normalize_stock_code(value):
    code = str(value).strip().upper()
    if not re.fullmatch(r'(?:\d{6}(?:\.(?:SH|SZ|BJ))?|(?:SH|SZ|BJ)\d{6})', code):
        raise DataError('请输入6位股票代码，例如600519或000001，也可使用600519.SH。')
    if code in ('000001.SH', 'SH000001'):
        raise DataError('当前页面只分析股票；平安银行请输入000001或000001.SZ。')
    return code


def analyze_stock(code):
    # Each request owns its mutable resolver/service; existing core cache is reused.
    service = StockAnalysisService()
    output = service.analyze(normalize_stock_code(code)).to_dict()
    if output['data_status']['is_mock']:
        raise DataError('当前数据源不是可用于公开展示的真实行情。')
    if output['data_status']['status'] != 'UNAVAILABLE':
        try:
            import json
            from app.features.technical import build_features
            # Reuse the same provider/cache and evaluation date as the analysis.
            market = service.provider_manager.fetch(output['symbol'])
            if market.metadata['is_mock']:
                raise DataError('图表数据不是可用于公开展示的真实行情。')
            bars = build_features(market.bars, as_of=output['evaluation_date'])
            fields = ['date','open_adj','high_adj','low_adj','close_adj','volume','M5','M30','M60']
            output['chart'] = json.loads(bars.tail(120)[fields].to_json(orient='records', date_format='iso'))
            row = bars.iloc[-1]
            import math
            reference = row.get('preclose')
            if reference is not None and math.isfinite(float(reference)) and float(reference)>0:
                change = float(row.close_raw) - float(reference)
                output['quote_change'] = {'amount':change, 'percent':change/float(reference)*100, 'basis':'BaoStock preclose'}
            output['chart_provider'] = market.metadata['provider']
        except Exception:
            output['chart'] = []
            output['chart_warning'] = '行情图数据暂不可用，已有规则分析结果保持不变。'
    return output


def coverage_text(value):
    return '暂不可计算' if value is None else f'{value * 100:.1f}%'


def number_text(value):
    return '—' if value is None else f'{value:g}'
