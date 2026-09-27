"""Offline regression checks; these do not claim real market connectivity."""
import os
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
import requests
import yaml
from fastapi.testclient import TestClient
from app.api import create_app
from app.data.proxy import call_with_proxy_fallback, ignore_inherited_proxies
from app.data.models import ProviderError
from test_stage2_service import service

VERSIONS = dict(spec_version='1.4', assumption_version='v1.3', data_contract_version='1.4')
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('failure', [False, True])
def test_proxy_fallback_restores_every_lookup_and_environment(failure):
    sessions_lookup = requests.sessions.get_environ_proxies
    utility_lookup = requests.utils.get_environ_proxies
    environment = dict(os.environ)
    attempts = []
    def call():
        attempts.append(1)
        if len(attempts) == 1:
            raise requests.exceptions.ProxyError('offline proxy failure')
        assert requests.sessions.get_environ_proxies('https://example.test') == {}
        assert requests.utils.get_environ_proxies('https://example.test') == {}
        assert requests.Session().trust_env is True
        if failure:
            raise requests.exceptions.ConnectionError('offline direct failure')
        return 'ok'
    if failure:
        with pytest.raises(ProviderError) as caught:
            call_with_proxy_fallback(call)
        assert caught.value.retryable is False
        assert isinstance(caught.value.__cause__, requests.exceptions.ConnectionError)
    else:
        value, metadata = call_with_proxy_fallback(call)
        assert value == 'ok'
        assert metadata == dict(network_mode='direct_after_proxy_error', network_attempts=2)
    assert len(attempts) == 2
    assert requests.sessions.get_environ_proxies is sessions_lookup
    assert requests.utils.get_environ_proxies is utility_lookup
    assert dict(os.environ) == environment

@pytest.mark.parametrize('error', [requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError])
def test_non_proxy_failure_does_not_trigger_direct_fallback(error):
    attempts = []
    def call():
        attempts.append(1)
        raise error('offline fixture')
    with pytest.raises(error):
        call_with_proxy_fallback(call)
    assert len(attempts) == 1

def test_success_keeps_normal_network_path():
    assert call_with_proxy_fallback(lambda: 42) == (42, dict(network_mode='normal', network_attempts=1))

def test_direct_mode_preserves_tls_environment(monkeypatch):
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', '/fixture/ca.pem')
    with ignore_inherited_proxies():
        settings = requests.Session().merge_environment_settings('https://example.test', {}, None, None, None)
        assert settings['verify'] == '/fixture/ca.pem'
        assert settings['proxies'] == {}

@pytest.mark.parametrize('route', ['/api/health', '/api/rules', '/api/analyze/000001', '/api/data/status/000001'])
def test_new_api_results_have_version_triple(service, route):
    data = TestClient(create_app(service)).get(route).json()
    assert {k: data[k] for k in VERSIONS} == VERSIONS
    for rule in data.get('rules', []):
        assert {k: rule[k] for k in VERSIONS} == VERSIONS
    for key in ('score', 'data_status'):
        if key in data:
            assert {k: data[key][k] for k in VERSIONS} == VERSIONS

@pytest.mark.parametrize('filename', ['scoring_rules.yaml', 'parameters.yaml'])
def test_config_version_triple(filename):
    config = yaml.safe_load((ROOT/'config'/filename).read_text('utf-8'))
    assert {k: config[k] for k in VERSIONS} == VERSIONS
    for rule in config.get('rules', []):
        assert {k: rule[k] for k in VERSIONS} == VERSIONS

def test_word_active_acceptance_uses_frozen_semantics():
    with ZipFile(next((ROOT/'docs').glob('*V1.4*.docx'))) as archive:
        xml = ET.fromstring(archive.read('word/document.xml'))
    ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in xml.findall('.//w:p', ns)]
    active = '\n'.join(paragraphs[paragraphs.index('第三部分 Active Acceptance Tests 与用户决策结案'):])
    assert 'T02_NEW' in active and 'INVALIDATED' in active
    assert '80' in active and 'HIGH' in active and '1.03' in active
    assert 'max_close_return<=0扣10' in active and '0<max_close_return<3%扣6' in active
    assert any('HISTORICAL / SUPERSEDED 历史验收' in p for p in paragraphs)
