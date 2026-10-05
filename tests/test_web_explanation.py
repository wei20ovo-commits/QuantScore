"""OFFLINE Streamlit AppTest fixtures, not proof of a real AI API call."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.explanation import ExplanationConfig, OpenAICompatibleExplanationProvider, DeepSeekExplanationProvider
from app.web_results import ScreeningSnapshot
from test_stage2_service import service

WEB = Path(__file__).resolve().parents[1] / 'app/web.py'


@pytest.fixture
def data(service):
    data = service.analyze('000001').to_dict()
    # Presentation-only fixture follows existing offline Web test convention.
    data['data_status']['is_mock'] = False
    return data


@pytest.fixture(autouse=True)
def offline():
    st.cache_data.clear()
    with patch('app.web_results.load_screening_snapshot', return_value=ScreeningSnapshot('UNKNOWN', 'OFFLINE TEST')):
        yield
    st.cache_data.clear()


def analyzed_app(data):
    app = AppTest.from_file(str(WEB)).run()
    app.button(key='analyze_submit').click().run(timeout=20)
    assert not app.exception and app.metric
    return app


def empty_plan(_context):
    return dict(positive_rule_ids=[], risk_rule_ids=[], unmet_rule_ids=[])


def test_standard_does_not_read_secrets_or_call_provider(data):
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch('app.web_explanation.explanation_config', side_effect=AssertionError('must not read credentials')), \
         patch.object(OpenAICompatibleExplanationProvider, 'explain') as provider:
        app = analyzed_app(data)
        app.run()
    assert not app.exception and not provider.called
    assert app.selectbox(key='explanation_mode').value == 'Standard Rules'
    assert any('既有规则结果的解释' in c.value for c in app.caption)
    assert len(app.json) == len(data['rules'])


def test_ai_only_explicit_trigger_and_reruns_do_not_repeat(data):
    before = deepcopy(data)
    config = ExplanationConfig('offline-only-key', 'https://example.test/v1', 'offline-model')
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch('app.web_explanation.explanation_config', return_value=config), \
         patch.object(OpenAICompatibleExplanationProvider, 'explain', side_effect=empty_plan) as provider:
        app = analyzed_app(data)
        app.selectbox(key='explanation_mode').select('AI Explanation').run()
        assert not provider.called
        app.button(key='generate_ai_explanation').click().run()
        assert provider.call_count == 1
        app.run()
        app.button(key='theme_toggle').click().run()
        assert provider.call_count == 1 and not app.exception
        assert app.session_state['explanation_result'].source == 'AI Explanation'
        app.selectbox(key='explanation_mode').select('Standard Rules').run()
        assert app.session_state['explanation_result'].source == 'Standard Rules'
        assert provider.call_count == 1
    assert data == before


@pytest.mark.parametrize('failure', [False, True])
def test_auto_valid_configuration_once_and_failure_keeps_page(data, failure):
    config = ExplanationConfig('offline-only-key', 'https://example.test/v1', 'offline-model')
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch('app.web_explanation.explanation_config', return_value=config), \
         patch.object(OpenAICompatibleExplanationProvider, 'explain',
                      side_effect=RuntimeError('secret-token-not-for-ui') if failure else empty_plan) as provider:
        app = analyzed_app(data)
        metrics = [m.value for m in app.metric]
        app.selectbox(key='explanation_mode').select('Auto').run()
        app.run()
        assert provider.call_count == 1 and not app.exception
        assert [m.value for m in app.metric] == metrics
        result = app.session_state['explanation_result']
        assert result.source == ('Standard Rules' if failure else 'AI Explanation')
        assert 'secret-token-not-for-ui' not in repr(result)


@pytest.mark.parametrize('mode', ['Auto', 'AI Explanation'])
def test_missing_configuration_falls_back_and_button_disabled(data, mode):
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch('app.web_explanation.explanation_config', return_value=ExplanationConfig()), \
         patch.object(OpenAICompatibleExplanationProvider, 'explain') as provider:
        app = analyzed_app(data)
        app.selectbox(key='explanation_mode').select(mode).run()
        assert not app.exception and app.metric and not provider.called
        assert app.session_state['explanation_result'].source == 'Standard Rules'
        if mode == 'AI Explanation':
            assert app.button(key='generate_ai_explanation').disabled


def test_same_symbol_new_result_does_not_reuse_old_explanation(data):
    config = ExplanationConfig('offline-only-key', 'https://example.test/v1', 'offline-model')
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch('app.web_explanation.explanation_config', return_value=config), \
         patch.object(OpenAICompatibleExplanationProvider, 'explain', side_effect=empty_plan) as provider:
        app = analyzed_app(data)
        app.selectbox(key='explanation_mode').select('Auto').run()
        previous = app.session_state['explanation_result'].context_fingerprint
        updated = deepcopy(data)
        updated['final_quant_score'] = 42
        app.session_state['analysis'] = updated
        app.run()
        assert provider.call_count == 2 and not app.exception
        assert app.session_state['explanation_result'].context_fingerprint != previous


def test_invalid_ai_output_fallback_does_not_crash(data):
    config = ExplanationConfig('offline-only-key', 'https://example.test/v1', 'offline-model')
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch('app.web_explanation.explanation_config', return_value=config), \
         patch.object(OpenAICompatibleExplanationProvider, 'explain', return_value={'text': '建议建仓'}):
        app = analyzed_app(data)
        app.selectbox(key='explanation_mode').select('Auto').run()
        assert not app.exception and app.metric
        assert app.session_state['explanation_result'].reason_code == 'INVALID_RESPONSE'
        assert all('建议建仓' not in x.value for x in app.text)


@pytest.mark.parametrize('failure', [False, True])
def test_deepseek_config_reaches_web_and_fails_safely(data, failure, monkeypatch):
    # Env fixture is synthetic. No real key or network access in AppTest.
    monkeypatch.delenv('QUANTSCORE_EXPLANATION_API_KEY', raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'offline-web-fixture')
    before = deepcopy(data)
    with patch('app.web_backend.analyze_stock', return_value=data), \
         patch.object(DeepSeekExplanationProvider, 'explain',
                      side_effect=RuntimeError('private-fixture') if failure else empty_plan) as provider:
        app = analyzed_app(data)
        app.selectbox(key='explanation_mode').select('Auto').run()
        app.run()
        assert provider.call_count == 1 and not app.exception
        assert app.session_state['explanation_result'].source == ('Standard Rules' if failure else 'AI Explanation')
        assert 'offline-web-fixture' not in repr(app.session_state['explanation_result'])
    assert data == before
