"""OFFLINE DeepSeek contracts. Mock HTTP success is not real API acceptance."""
from copy import deepcopy
import json

import httpx
import pytest

from app.explanation import (BUCKETS, DeepSeekExplanationProvider, ExplanationConfig,
                             ExplanationService)
from test_explanation import analysis, all_text, response


def settings(**extra):
    return ExplanationConfig.from_sources({'DEEPSEEK_API_KEY': 'offline-deepseek-fixture', **extra}, {})


def test_deepseek_environment_defaults_and_hidden_key():
    config = settings()
    assert config.valid and config.provider == 'deepseek'
    assert config.base_url == 'https://api.deepseek.com' and config.model == 'deepseek-flash'
    assert 'offline-deepseek-fixture' not in repr(config)


def test_deepseek_secrets_and_environment_precedence():
    cfg = ExplanationConfig.from_sources({'DEEPSEEK_BASE_URL': 'https://api.deepseek.com/v1',
        'DEEPSEEK_MODEL': 'deepseek-v4-pro'}, {'DEEPSEEK_API_KEY': 'offline-secret-fixture',
        'DEEPSEEK_MODEL': 'ignored-model'})
    assert cfg.valid and cfg.model == 'deepseek-v4-pro' and cfg.api_key == 'offline-secret-fixture'
    cfg = ExplanationConfig.from_sources({'DEEPSEEK_API_KEY': 'offline-env-fixture'},
        {'DEEPSEEK_API_KEY': 'offline-secret-fixture'})
    assert cfg.api_key == 'offline-env-fixture'


def test_configuration_families_never_mix_keys_and_endpoints():
    cfg = ExplanationConfig.from_sources({'QUANTSCORE_EXPLANATION_API_KEY': 'offline-generic-fixture',
        'QUANTSCORE_EXPLANATION_MODEL': 'offline-model', 'DEEPSEEK_API_KEY': 'offline-deepseek-fixture',
        'DEEPSEEK_BASE_URL': 'https://api.deepseek.com'}, {})
    assert cfg.provider == 'openai-compatible' and cfg.base_url == 'https://api.openai.com/v1'
    cfg = settings(QUANTSCORE_EXPLANATION_BASE_URL='https://other.test/v1')
    assert cfg.base_url == 'https://api.deepseek.com'


@pytest.mark.parametrize('base', ['http://api.deepseek.com', 'https://other.test',
    'https://api.deepseek.com.evil.test', 'https://api.deepseek.com?key=fixture',
    'https://fixture@api.deepseek.com', 'https://api.deepseek.com:444',
    'https://api.deepseek.com/anthropic'])
def test_deepseek_key_cannot_go_to_wrong_endpoint(base):
    assert not settings(DEEPSEEK_BASE_URL=base).valid


def test_generic_official_deepseek_endpoint_uses_deepseek_contract():
    cfg = ExplanationConfig.from_sources({'QUANTSCORE_EXPLANATION_API_KEY': 'offline-fixture',
        'QUANTSCORE_EXPLANATION_BASE_URL': 'https://api.deepseek.com/v1'}, {})
    assert cfg.valid and cfg.provider == 'deepseek'


def test_deepseek_base_without_key_does_not_enable_api():
    cfg = ExplanationConfig.from_sources({'DEEPSEEK_BASE_URL': 'https://api.deepseek.com'}, {})
    assert not cfg.valid


@pytest.mark.parametrize('mode', ['AI Explanation', 'Auto'])
def test_deepseek_json_contract_and_immutable_analysis(analysis, mode):
    before = deepcopy(analysis)
    seen = []
    def handler(request):
        seen.append(request)
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        payload = json.loads(request.content)
        assert payload['response_format'] == {'type': 'json_object'}
        assert payload['thinking'] == {'type': 'disabled'} and payload['max_tokens'] == 1200
        assert 'max_completion_tokens' not in payload and 'store' not in payload
        assert 'JSON' in payload['messages'][0]['content']
        assert 'chart' not in payload['messages'][1]['content']
        assert 'candidate_status' not in payload['messages'][1]['content']
        return response(json.dumps(dict(zip(BUCKETS, [['C1'], [], ['B2']]))))
    cfg = settings()
    provider = DeepSeekExplanationProvider(cfg, httpx.MockTransport(handler))
    result = ExplanationService(cfg, provider).explain(analysis, mode, triggered=True)
    assert result.source == 'AI Explanation' and len(seen) == 1 and analysis == before
    assert 'QuantScore：80' in all_text(result) and 'UNKNOWN' in all_text(result)
    assert provider.last_http_status == 200 and provider.last_elapsed_seconds >= 0


@pytest.mark.parametrize('content', ['', '{}', '{"score":100}',
    '{"summary":"推荐买入"}', '{"positive_rule_ids":["B2"],"risk_rule_ids":[],"unmet_rule_ids":[]}'])
def test_json_mode_never_bypasses_local_schema_and_fact_checks(analysis, content):
    cfg = settings()
    provider = DeepSeekExplanationProvider(cfg, httpx.MockTransport(lambda _: response(content)))
    result = ExplanationService(cfg, provider).explain(analysis, 'Auto')
    assert result.source == 'Standard Rules' and result.status == 'FALLBACK'


@pytest.mark.parametrize('status,reason', [(401, 'PROVIDER_ERROR'), (429, 'RATE_LIMIT'),
    (503, 'PROVIDER_ERROR'), (302, 'PROVIDER_ERROR')])
def test_deepseek_failures_are_safe_and_single_attempt(analysis, status, reason):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='private-provider-body', headers={'location': 'https://other.test'})
    cfg = settings()
    provider = DeepSeekExplanationProvider(cfg, httpx.MockTransport(handler))
    result = ExplanationService(cfg, provider).explain(analysis, 'Auto')
    assert result.reason_code == reason and len(calls) == 1
    assert provider.last_http_status == status and 'private-provider-body' not in repr(result)


def test_service_selects_deepseek_provider_without_decision_changes(analysis, monkeypatch):
    calls = []
    def explain(self, context):
        calls.append(context)
        return dict(zip(BUCKETS, [[], [], []]))
    monkeypatch.setattr(DeepSeekExplanationProvider, 'explain', explain)
    before = deepcopy(analysis)
    assert ExplanationService(settings()).explain(analysis, 'Auto').source == 'AI Explanation'
    assert len(calls) == 1 and analysis == before
