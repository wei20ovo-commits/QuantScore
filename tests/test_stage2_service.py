"""全链路使用人工 mock 夹具，不请求在线行情。"""
import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.cli import main
from app.data.base import MockProvider
from app.data.cache import DataCache
from app.data.models import ProviderError
from app.data.provider_manager import ProviderManager
from app.engine.score_engine import ScoreEngine
from app.services.stock_analysis_service import StockAnalysisService


@pytest.fixture
def service(tmp_path):
    close = np.linspace(10, 12, 150)
    bars = pd.DataFrame({'date': pd.bdate_range('2024-01-01', periods=150),
                         'open': close, 'high': close + .2, 'low': close - .2,
                         'close': close, 'volume': 100., 'amount': 1000., 'turnover_rate': 5.})
    provider = MockProvider([{'canonical_symbol': '000001.SZ', 'name': '测试深股'}],
                            bars, bars, bars)
    manager = ProviderManager(provider, cache=DataCache(tmp_path / 'cache.sqlite'))
    return StockAnalysisService(manager)


def test_analysis_reuses_engines_and_benchmark(service):
    # 两次比较使用同一缓存快照，避免缓存 JSON 精度影响逐字段精确相等。
    service.provider_manager.fetch('000001')
    output = service.analyze('000001')
    assert output.symbol == '000001.SZ'
    assert output.benchmark_symbol == '000001.SH'
    assert output.market_context['symbol'] == '000001.SH'
    assert output.data_status.is_mock
    data = service.provider_manager.fetch('000001')
    expected = ScoreEngine(service.rule_engine).evaluate(data.to_context())
    assert output.score.model_dump() == expected
    encoded = json.dumps(output.to_dict(), allow_nan=False)
    assert 'NaN' not in encoded
    assert ('benchmark', '000001.SH') in service.provider_manager.provider.calls


@pytest.mark.parametrize('rid', ['D2', 'F1-X', 'F2', 'R3', 'R5'])
def test_stage2_unimplemented_rules_remain_unknown(service, rid):
    data = service.provider_manager.fetch('000001')
    result = next(r for r in service.rule_engine.evaluate_all(data.to_context()) if r.rule_id == rid)
    assert service.rule_engine.registry[rid]['code_status'] == 'IMPLEMENTED'
    assert result.reason_code != 'NOT_IMPLEMENTED'
    if result.status == 'UNKNOWN':
        assert result.score is None and result.penalty is None


def test_v14_contract_preserves_v13_scoring(service):
    client = TestClient(create_app(service))
    health = client.get('/api/health').json()
    assert health['spec_version'] == '1.4'
    assert health['benchmark_symbol'] == '000001.SH'
    assert health['benchmark_name'] == '上证指数'
    rules = client.get('/api/rules').json()
    assert rules['spec_version'] == '1.4'
    assert {r['spec_version'] for r in rules['rules']} == {'1.4'}
    data = service.provider_manager.fetch('000001')
    assert data.benchmark_symbol == '000001.SH'
    assert data.benchmark_name == '上证指数'


def test_feature_builder_injected(service):
    original = service.feature_builder.build
    calls = []
    def build(bars, as_of=None):
        calls.append(len(bars))
        return original(bars, as_of)
    service.feature_builder.build = build
    service.analyze('000001')
    assert calls == [150, 150]


def test_missing_benchmark_keeps_stock_rules(service):
    service.provider_manager.provider.benchmark = None
    output = service.analyze('000001')
    rules = {r['rule_id']: r for r in output.score.rules}
    assert output.data_status.status == 'PARTIAL'
    assert output.market_context['status'] == 'UNKNOWN'
    assert all(rules[r]['status'] == 'UNKNOWN' for r in ('A1', 'A2', 'A3'))
    assert rules['C1']['status'] != 'UNKNOWN'
    assert rules['F1-N']['score'] is None


@pytest.mark.parametrize('kind', ['missing', 'empty', 'invalid'])
def test_unavailable_data(service, kind):
    provider = service.provider_manager.provider
    if kind == 'missing':
        provider.raw = None
    elif kind == 'empty':
        provider.raw = provider.raw.iloc[:0]
        provider.qfq = provider.qfq.iloc[:0]
    else:
        provider.raw.loc[0, 'high'] = 0
    output = service.analyze('000001')
    assert output.data_status.status == 'UNAVAILABLE'
    assert output.score.score_status == 'INSUFFICIENT'
    assert output.evaluation_date is None
    assert all(r['status'] == 'UNKNOWN' and r['score'] is None and r['penalty'] is None
               for r in output.score.rules)
    output.to_dict()


def test_missing_optional_fields(service):
    provider = service.provider_manager.provider
    provider.raw = provider.raw.drop(columns=['volume', 'amount', 'turnover_rate'])
    output = service.analyze('000001')
    assert output.data_status.status == 'PARTIAL'
    rules = {r['rule_id']: r for r in output.score.rules}
    assert rules['D1']['status'] == 'UNKNOWN'
    assert rules['C1']['status'] != 'UNKNOWN'
    output.to_dict()


def test_short_history(service):
    provider = service.provider_manager.provider
    provider.raw = provider.raw.iloc[:3]
    provider.qfq = provider.qfq.iloc[:3]
    output = service.analyze('000001')
    assert output.score.score_status == 'INSUFFICIENT'
    assert output.data_status.rows == 3
    output.to_dict()


def test_securities_provider_outage(service):
    def unavailable():
        raise ProviderError('测试数据源故障')
    service.provider_manager.provider.list_securities = unavailable
    output = service.analyze('000001')
    assert output.symbol is None
    assert output.data_status.error_code == 'PROVIDER_UNAVAILABLE'


def test_asof_and_status_do_not_score(service):
    service.score_engine.evaluate = lambda context: pytest.fail('状态接口不应执行评分')
    status = service.data_status('000001', as_of='2024-04-30')
    assert status.evaluation_date == '2024-04-30'
    assert status.rows < 150


def test_api_routes(service):
    with TestClient(create_app(service)) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        assert not service.provider_manager.provider.calls
        rules = client.get('/api/rules').json()['rules']
        assert len(rules) == len(service.rule_engine.registry)
        assert not service.provider_manager.provider.calls
        response = client.get('/api/analyze/000001')
        assert response.status_code == 200
        assert response.json()['symbol'] == '000001.SZ'
        assert response.json()['data_status']['is_mock'] is True
        status = client.get('/api/data/status/000001').json()
        assert status['benchmark_symbol'] == '000001.SH'
        assert status['rows'] == 150
        assert client.get('/api/analyze/invalid').status_code == 422
        assert client.get('/api/data/status/999999').status_code == 422
        assert client.get('/api/analyze/000001?as_of=bad').status_code == 422
        assert client.get('/api/analyze/000001?as_of=2024-04-30').json()['evaluation_date'] == '2024-04-30'


def test_api_unavailable_is_structured(service):
    service.provider_manager.provider.raw = None
    with TestClient(create_app(service)) as client:
        response = client.get('/api/analyze/000001')
        assert response.status_code == 200
        assert response.json()['data_status']['status'] == 'UNAVAILABLE'
        assert response.json()['score']['score_status'] == 'INSUFFICIENT'


@pytest.mark.parametrize('argv', [['analyze', '000001', '--json'], ['--json', 'analyze', '000001']])
def test_cli_json(service, capsys, argv):
    assert main(argv, service=service) == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output['symbol'] == '000001.SZ'
    assert output['data_status']['is_mock']
    assert not captured.err


def test_cli_text_and_errors(service, capsys):
    assert main(['analyze', '000001'], service=service) == 0
    text = capsys.readouterr().out
    assert '000001.SH' in text
    assert 'Coverage：' in text
    assert 'Top Positive Rules：' in text
    assert 'Top Risk Rules：' in text
    assert 'Unknown Rules：' in text
    assert main(['analyze', 'bad', '--json'], service=service) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)['error']['code'] == 'DATA_INVALID'
    service.provider_manager.provider.raw = None
    assert main(['analyze', '000001', '--json', '--refresh'], service=service) == 1
    assert json.loads(capsys.readouterr().out)['data_status']['status'] == 'UNAVAILABLE'


def test_cli_module_help():
    completed = subprocess.run([sys.executable, '-m', 'app.cli', '--help'], capture_output=True)
    assert completed.returncode == 0
    assert b'analyze' in completed.stdout
