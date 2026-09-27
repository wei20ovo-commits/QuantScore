"""Offline UI tests use labeled fixtures, never evidence for live acceptance."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from app.data.models import DataError
from app.web_backend import coverage_text, normalize_stock_code, analyze_stock
from test_stage2_service import service

WEB = Path(__file__).resolve().parents[1]/'app/web.py'

@pytest.fixture(autouse=True)
def clear_web_cache():
    st.cache_data.clear()
    # Homepage market data is separately live-verified; unit tests stay offline.
    with patch('app.web_market.load_index_snapshots',return_value=[]):
        yield
    st.cache_data.clear()

@pytest.fixture
def output(service):
    return service.analyze('000001').to_dict()

def test_initial_page_has_disclaimer_and_no_automatic_analysis():
    with patch('app.web_backend.analyze_stock') as call:
        app=AppTest.from_file(str(WEB)).run()
    assert not app.exception and not call.called
    assert app.title[0].value=='QuantScore'
    assert any('不构成投资建议' in x.value for x in app.info)
    assert app.button(key='analyze_submit').label=='开始分析'

@pytest.mark.parametrize('value', ['', 'abc', '600519;test', '000001.SH', 'SH000001'])
def test_invalid_or_index_input(value):
    with pytest.raises(DataError):normalize_stock_code(value)

@pytest.mark.parametrize('value,expected', [(' 600519 ','600519'),('000001.sz','000001.SZ'),('sh600519','SH600519')])
def test_valid_input(value,expected):
    assert normalize_stock_code(value)==expected

def test_coverage_ratio_is_presented_as_percentage():
    assert coverage_text(.59)=='59.0%'
    assert coverage_text(None)=='暂不可计算'

def test_backend_rejects_mock_provider(service):
    with patch('app.web_backend.StockAnalysisService',return_value=service):
        with pytest.raises(DataError,match='真实行情'):analyze_stock('000001')

def test_render_metrics_and_expandable_rule_details(output):
    # Presentation-only fixture. Production adapter's mock guard tested separately.
    data=deepcopy(output);data['data_status']['is_mock']=False
    with patch('app.web_backend.analyze_stock',return_value=data) as call:
        app=AppTest.from_file(str(WEB)).run()
        app.text_input[0].set_value('000001')
        app.button(key='analyze_submit').click().run(timeout=20)
    assert not app.exception
    call.assert_called_once_with('000001')
    assert {m.label for m in app.metric}=={'QuantScore','Risk Level','Positive Score','Risk Penalty'}
    assert any('全部规则明细' in x.label for x in app.expander)
    assert len(app.json)==len(data['rules'])
    text='\n'.join(x.value for x in app.markdown)
    assert '正向覆盖率' in text and '风险覆盖率' in text
    assert all(rule['rule_id'] in text and rule['name_cn'] in text for rule in data['rules'])

@pytest.mark.parametrize('failure', ['unavailable','exception','mock'])
def test_failed_request_does_not_show_score(output,failure):
    data=deepcopy(output);data['data_status']['is_mock']=failure=='mock'
    if failure=='unavailable':data['data_status']['status']='UNAVAILABLE'
    with patch('app.web_backend.analyze_stock',side_effect=RuntimeError('secret fixture') if failure=='exception' else None,return_value=data):
        app=AppTest.from_file(str(WEB)).run()
        app.button(key='analyze_submit').click().run(timeout=20)
    assert not app.exception and app.error and not app.metric
    assert 'secret fixture' not in app.error[0].value

def test_invalid_new_request_clears_previous_result(output):
    output['data_status']['is_mock']=False
    with patch('app.web_backend.analyze_stock',return_value=output):
        app=AppTest.from_file(str(WEB)).run()
        app.button(key='analyze_submit').click().run(timeout=20)
        assert app.metric
        app.text_input[0].set_value('bad')
        app.button(key='analyze_submit').click().run()
        assert app.error and not app.metric
