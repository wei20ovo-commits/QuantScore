"""Lightweight offline spawn fixtures; no UI, pytest or service imports."""
import json
from pathlib import Path
import time


def context_from_file(snapshot):
    from app.web_diagnostics import emit, safe_event
    values = json.loads(Path(snapshot).read_text('utf-8'))
    emit(safe_event('context', 'OK', **values))


def success_worker_target(snapshot):
    from app.web_diagnostics import emit, safe_event
    emit(safe_event('fetch_group', 'START', adjustment='raw'))
    emit(safe_event('fetch_group', 'OK', adjustment='raw', seconds=.2))
    context_from_file(snapshot)
    return {'data_status': {'status': 'AVAILABLE'}, 'final_quant_score': 80, 'risk_level': 'LOW',
            'web_diagnostics': {'events': [safe_event('rule_scoring', 'OK')], 'reason_code': 'NONE'}}


def failure_worker_target(snapshot):
    from app.web_diagnostics import emit, safe_event
    from app.data.models import ProviderError
    context_from_file(snapshot)
    emit(safe_event('fetch_group', 'START', adjustment='raw'))
    emit(safe_event('provider_request', 'FAILED', provider='baostock', reason_code='PROVIDER_TIMEOUT'))
    raise ProviderError('PRIVATE_CREDENTIAL_TEST_SENTINEL')


def timeout_worker_target(snapshot):
    from app.web_diagnostics import emit, safe_event
    context_from_file(snapshot)
    emit(safe_event('rule_scoring', 'OK'))
    emit(safe_event('fetch_group', 'START', adjustment='qfq'))
    time.sleep(30)


def before_snapshot_worker_target(snapshot):
    # A ready marker proves entry into the target, but is NOT snapshot evidence.
    Path(snapshot).with_suffix('.ready').write_text('TARGET_ENTERED', 'utf-8')
    time.sleep(30)
    context_from_file(snapshot)
