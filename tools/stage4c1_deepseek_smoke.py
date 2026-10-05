"""At most two real explanation requests; credentials only from env/st.secrets.

Never serialize config, request/response bodies, headers, keys or exceptions.
Input is an archived genuine 600519 engine result, NOT a fresh market request.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
import streamlit as st
from app.explanation import (BUCKETS, DISCLAIMER, DeepSeekExplanationProvider,
                             ExplanationConfig, ExplanationService, build_context, forbidden)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-real-api', action='store_true')
    args = parser.parse_args()
    config = ExplanationConfig.from_sources(secrets=st.secrets)
    source = ROOT / 'outputs/stage3c/full_market/stock_details/600519.SH.json'
    data = json.loads(source.read_text('utf-8'))
    assert data['symbol'] == '600519.SH' and data['data_status']['is_mock'] is False
    before = deepcopy(data)
    context = build_context(data)
    assert 'chart' not in context and 'bars' not in context and 'candidate_status' not in context
    record = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'input_source': source.relative_to(ROOT).as_posix(),
              'input_type': 'ARCHIVED_REAL_ENGINE_RESULT_NOT_LIVE_MARKET',
              'trade_date': data['evaluation_date'], 'real_api_calls': 0,
              'config_valid': config.valid, 'deepseek_selected': config.provider == 'deepseek',
              'real_api_status': 'REAL_API_CONFIGURATION_REQUIRED', 'attempts': []}
    # Forced error is strictly offline, deliberately labeled, not paid/live evidence.
    fixture = ExplanationConfig.from_sources({'DEEPSEEK_API_KEY': 'offline-smoke-fixture'}, {})
    failed = ExplanationService(fixture, DeepSeekExplanationProvider(fixture,
        httpx.MockTransport(lambda _: httpx.Response(503)))).explain(data, 'Auto')
    assert failed.reason_code == 'PROVIDER_ERROR' and failed.source == 'Standard Rules'
    no_key = ExplanationService(ExplanationConfig()).explain(data, 'Auto')
    assert no_key.reason_code == 'NO_CONFIGURATION'
    record['fallback'] = {'status': 'PASS', 'provider_error_is_offline_fixture': True,
                          'provider_error_reason': failed.reason_code, 'no_key_reason': no_key.reason_code}
    if config.valid and config.provider == 'deepseek':
        record['real_api_status'] = 'NOT_RUN_WITHOUT_ALLOW_REAL_API'
        if args.allow_real_api:
            provider = DeepSeekExplanationProvider(config)
            service = ExplanationService(config, provider)
            for mode in ('AI Explanation', 'Auto'):
                result = service.explain(data, mode, triggered=mode == 'AI Explanation')
                record['real_api_calls'] += 1
                assert data == before and result.disclaimer == DISCLAIMER
                assert not any(forbidden(line) for _, lines in result.sections for line in lines)
                record['attempts'].append({'mode': mode, 'requested_model': config.model,
                    'http_status': provider.last_http_status, 'elapsed_seconds': provider.last_elapsed_seconds,
                    'status': result.status, 'source': result.source, 'reason_code': result.reason_code})
                if result.source != 'AI Explanation':
                    break  # No extra paid attempts after a failed first call.
            record['real_api_status'] = ('PASS' if len(record['attempts']) == 2 and
                all(a['source'] == 'AI Explanation' and a['http_status'] == 200 for a in record['attempts'])
                else 'REAL_API_VERIFICATION_FAILED')
    record['original_analysis_unchanged'] = data == before
    record['raw_chart_sent'] = False
    record['status'] = 'PASS' if record['real_api_status'] == 'PASS' else 'PARTIAL'
    output = ROOT / 'outputs/stage4c1'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'deepseek_smoke.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'status': record['status'], 'real_api_status': record['real_api_status'],
                      'real_api_calls': record['real_api_calls'], 'fallback': 'PASS'}))


if __name__ == '__main__':
    main()
