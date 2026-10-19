"""Artificial credential sentinels only; no real credentials or market claims."""
from copy import deepcopy
import json
import os
import sqlite3

import pytest

from app.cloud_state import safe_bytes, pack_state, unpack_state
from test_cloud_update import CODE, DAY, seed, export, rewrite
from test_web_snapshots import published

SENTINEL = 'SYNTHETIC_AUDIT_VALUE_NOT_A_REAL_SECRET'
KEYS = ['api_key', 'API-KEY', 'ApiKey', 'authorization', 'AUTHORIZATION',
        'proxy_authorization', 'token', 'access-token', 'refresh_token',
        'secret', 'client_secret', 'password', 'Pass-Word', 'passwd', 'pwd',
        'private_key', 'secret_access_key', 'access_key_id', 'credentials',
        'secret_key', 'client-secret-key', 'api_key_id', 'password_hash', 'Token_Value']


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('container', ['object', 'array', 'json_string'])
def test_structured_sensitive_keys_rejected_not_removed(key, container):
    value = {key: SENTINEL}
    if container == 'array':
        value = {'nested': [{'record': value}]}
    if container == 'json_string':
        value = {'payload': json.dumps({'nested': [value]})}
    with pytest.raises(ValueError, match='^STATE_PRIVATE_CONTENT_REJECTED$'):
        safe_bytes(json.dumps(value).encode())


@pytest.mark.parametrize('encoded', [
    b'{"\\u0061pi_key":"SYNTHETIC"}',
    b'{"Api\\u005fKey":"SYNTHETIC"}',
    b'{"\\u0061uthorization":"SYNTHETIC"}',
    b'{"data":[{"pass\\u002dword":"SYNTHETIC"}]}',
    json.dumps({'payload': '{"\\u0074oken":"SYNTHETIC"}'}).encode(),
    json.dumps({'payload': json.dumps('{"api_key":"SYNTHETIC"}')}).encode(),
    json.dumps({'value': 'Bearer SYNTHETIC_AUDIT_SENTINEL'}).encode(),
    json.dumps({'value': 'AKIA' + 'Z' * 16}).encode(),
])
def test_escapes_and_embedded_json_cannot_hide_sensitive_content(encoded):
    with pytest.raises(ValueError, match='^STATE_PRIVATE_CONTENT_REJECTED$'):
        safe_bytes(encoded)


@pytest.mark.parametrize('storage', ['calendar', 'frame', 'history', 'score'])
@pytest.mark.parametrize('key', ['api_key', 'authorization', 'access-token', 'password'])
def test_export_injection_keeps_last_good_bundle_and_original_state(tmp_path, storage, key):
    work, bundle, cache, _ = seed(tmp_path)
    export(work, bundle)
    previous = bundle.read_bytes()
    unsafe = json.dumps({'nested': [{key: SENTINEL}]})
    if storage == 'calendar':
        (work/'run').mkdir()
        (work/'run/calendar.json').write_text(unsafe, 'utf-8')
        original = (work/'run/calendar.json').read_bytes()
    elif storage == 'frame':
        with sqlite3.connect(cache.path) as db:
            db.execute('UPDATE frames SET payload=?', (unsafe,))
    else:
        from app.cloud_state import TABLES
        database, tables = TABLES['history' if storage == 'history' else 'scores']
        table, (definition, _) = next(iter(tables.items()))
        with sqlite3.connect(work/'cache'/database) as db:
            db.execute('CREATE TABLE '+table+' ('+definition+')')
            values = ('key', unsafe, '{"data":[]}') if storage == 'history' else ('key', unsafe)
            db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values)+')', values)
    with pytest.raises(ValueError, match='^STATE_PRIVATE_CONTENT_REJECTED$'):
        export(work, bundle)
    assert bundle.read_bytes() == previous
    assert not list(tmp_path.glob('*.partial'))
    assert cache.path.exists()
    if storage == 'calendar':
        assert (work/'run/calendar.json').read_bytes() == original


@pytest.mark.parametrize('storage', ['calendar', 'frame', 'history', 'score', 'header'])
@pytest.mark.parametrize('key', ['api_key', 'authorization', 'token', 'secret'])
def test_import_rejects_signed_unsafe_stream_without_partial_install(tmp_path, storage, key):
    work, bundle, _, _ = seed(tmp_path)
    (work/'run').mkdir()
    (work/'run/calendar.json').write_text('{"data_status":"VALID"}', 'utf-8')
    export(work, bundle)
    original = (work/'cache/market.sqlite3').read_bytes()
    unsafe = json.dumps({'nested': [{key: SENTINEL}]})
    def inject(records):
        if storage == 'header':
            records[0][key] = SENTINEL
        elif storage == 'calendar':
            records[-2]['payload'] = json.loads(unsafe)
        elif storage == 'frame':
            records[1]['values'][1] = unsafe
        else:
            database, table, values = ('history', 'history_v1', ['k', unsafe, '{}']) if storage == 'history' else ('scores', 'score_memo_v1', ['k', unsafe])
            records.insert(-1, dict(kind='row', database=database, table=table, values=values))
    rewrite(bundle, inject)  # Recompute digest: integrity alone is NOT privacy.
    with pytest.raises(ValueError, match='^STATE_PRIVATE_CONTENT_REJECTED$'):
        unpack_state(bundle, tmp_path/'new', source_fingerprint=CODE)
    assert not (tmp_path/'new').exists()
    assert not list(tmp_path.glob('new.import-*'))
    assert (work/'cache/market.sqlite3').read_bytes() == original


def test_existing_destination_cannot_be_overwritten_by_rejected_import(tmp_path):
    work, bundle, _, _ = seed(tmp_path)
    export(work, bundle)
    unpack_state(bundle, tmp_path/'new', source_fingerprint=CODE)
    before = (tmp_path/'new/cache/market.sqlite3').read_bytes()
    rewrite(bundle, lambda records: records[0].update(authorization=SENTINEL))
    with pytest.raises(ValueError):
        unpack_state(bundle, tmp_path/'new', source_fingerprint=CODE)
    assert (tmp_path/'new/cache/market.sqlite3').read_bytes() == before


def test_legitimate_market_fields_and_explanations_are_preserved():
    value = {'sector_id': 'C15', 'trade_date': DAY, 'raw_inputs': {
        'volume': 123, 'amount': 456.78, 'turnover_rate': 3.2,
        'preclose': 10, 'isST': False, 'tokenization_not_used': False},
        'explanation': '条件不足保持UNKNOWN，不构成投资建议。',
        'payload': json.dumps({'schema': {'primaryKey': ['date']}, 'data': []})}
    before = deepcopy(value)
    assert safe_bytes(json.dumps(value, ensure_ascii=False).encode()) == value == before


@pytest.mark.parametrize('bad', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_ambiguous_or_nonfinite_json_rejected(bad):
    with pytest.raises(ValueError):
        safe_bytes(bad)


def test_nested_json_budget_rejects_instead_of_bypassing_checks():
    text = '"plain"'
    for _ in range(65):
        text = '{"nested":' + text + '}'
    with pytest.raises(ValueError, match='STATE_STRUCTURE_BUDGET_EXCEEDED'):
        safe_bytes(text.encode())


@pytest.mark.parametrize('link', ['cache_parent', 'calendar', 'destination', 'source'])
def test_linked_state_is_rejected_without_touching_target(tmp_path, link):
    work, bundle, cache, _ = seed(tmp_path)
    export(work, bundle)
    previous = bundle.read_bytes()
    outside = tmp_path/'outside'
    outside.mkdir()
    sentinel = outside/'calendar.json'
    sentinel.write_text('{"data_status":"VALID"}', 'utf-8')
    def directory_link(alias, target):
        if os.name == 'nt':
            # Junction creation needs no symlink privilege/Developer Mode.
            import _winapi
            _winapi.CreateJunction(str(target), str(alias))
        else:
            alias.symlink_to(target, target_is_directory=True)
    if link == 'cache_parent':
        linked = tmp_path/'linked'
        linked.mkdir()
        directory_link(linked/'cache', work/'cache')
        operation = lambda: export(linked, bundle)
    elif link == 'calendar':
        directory_link(work/'run', outside)
        operation = lambda: export(work, bundle)
    elif link == 'destination':
        linked = tmp_path/'destination'
        directory_link(linked, outside)
        operation = lambda: export(work, linked/'state.gz')
    else:
        (outside/'state.gz').write_bytes(previous)
        linked = tmp_path/'source'
        directory_link(linked, outside)
        operation = lambda: unpack_state(linked/'state.gz', tmp_path/'new', source_fingerprint=CODE)
    with pytest.raises(ValueError, match='STATE_FILE_INVALID'):
        operation()
    assert bundle.read_bytes() == previous
    assert sentinel.read_text('utf-8') == '{"data_status":"VALID"}'
    assert cache.path.exists() and not (tmp_path/'new').exists()


@pytest.mark.parametrize('key', ['api_key', 'authorization', 'token'])
def test_public_status_injection_blocks_publication_and_leaves_good_bundle(published, monkeypatch, key):
    from app.cloud_update import run_slice
    from test_cloud_update import slice_fixture
    from test_market_publication import promote, pointer
    root, _, _, factory = slice_fixture(monkeypatch, published)
    promote(root)
    previous = pointer(root)
    bundle = root/'outputs/runtime/cloud-update/transfer/state.jsonl.gz'
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b'previous-good-artifact-sentinel')
    def injected(cache, control):
        adapter = factory(cache, control)
        adapter.metrics = lambda: {'history_cache': {'nested': [{key: SENTINEL}]}}
        return adapter
    report = run_slice(root, slice_index=1, producer='1', adapter_factory=injected)
    assert report['status'] == 'BLOCKED' and not report['published']
    assert report['reason_code'] == 'STATE_PRIVATE_OR_INVALID_REPORT_REJECTED'
    assert pointer(root) == previous
    assert bundle.read_bytes() == b'previous-good-artifact-sentinel'
    for path in [root/'outputs/runtime/cloud-update/status.json',
                 root/'outputs/runtime/market-update/latest_attempt.json']:
        assert SENTINEL not in path.read_text('utf-8')
        safe_bytes(path.read_bytes())


def test_failed_run_exit_and_workflow_guard_reject_previous_bundle_upload(tmp_path, monkeypatch, capsys):
    from tools import cloud_market_update as cli
    from pathlib import Path
    import sys
    import yaml
    monkeypatch.setattr(sys, 'argv', ['cloud_market_update', '--slice', '1'])
    monkeypatch.setattr('app.cloud_update.run_slice', lambda *a, **k: {
        'status': 'BLOCKED', 'reason_code': 'STATE_PRIVATE_CONTENT_REJECTED'})
    assert cli.main() == 1
    assert 'BLOCKED' in capsys.readouterr().out
    flow = yaml.load((Path(__file__).resolve().parents[1]/'deployment/github-hosted/market-slice.yml.example').read_text('utf-8'), Loader=yaml.BaseLoader)
    transfers = [s for s in flow['jobs']['slice']['steps']
                 if s.get('uses', '').startswith(('actions/cache/save', 'actions/upload-artifact'))
                 and 'status.json' not in s.get('with', {}).get('path', '')]
    assert len(transfers) == 2
    for step in transfers:
        assert 'success()' in step['if']
        assert "== 'PAUSED'" in step['if'] and "== 'PUBLISHED_LOCALLY'" in step['if']


def test_unexpected_sqlite_secret_column_cannot_be_exported_as_unnamed_value(tmp_path):
    work, bundle, cache, _ = seed(tmp_path)
    export(work, bundle)
    previous = bundle.read_bytes()
    with sqlite3.connect(cache.path) as db:
        db.execute('ALTER TABLE frames ADD COLUMN authorization TEXT')
        db.execute('UPDATE frames SET authorization=?', (SENTINEL,))
    with pytest.raises(ValueError, match='STATE_DATABASE_SCHEMA_INVALID'):
        export(work, bundle)
    assert bundle.read_bytes() == previous


def test_concatenated_gzip_member_does_not_escape_stream_manifest(tmp_path):
    import gzip
    work, bundle, _, _ = seed(tmp_path)
    export(work, bundle)
    bundle.write_bytes(bundle.read_bytes() + gzip.compress(b'{"kind":"file","path":"run/calendar.json","payload":{}}\n'))
    with pytest.raises(ValueError, match='STATE_EXPANSION_OR_TRAILING_DATA'):
        unpack_state(bundle, tmp_path/'new', source_fingerprint=CODE)
    assert not (tmp_path/'new').exists() and not list(tmp_path.glob('new.import-*'))


@pytest.mark.parametrize('failures,expected', [(0, 'LOCAL_PASS'), (1, 'BLOCKED')])
def test_acceptance_cli_selects_junit_output_and_honors_failed_gate(tmp_path, monkeypatch, capsys, failures, expected):
    """Synthetic JUnit unit fixture, never presented as the real full gate."""
    from tools import cloud_update_acceptance as acceptance
    import hashlib
    import sys
    inventory = tmp_path/'outputs/free_cloud/initial_integrity.json'
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps(dict(protected={}, frozen={}, HEAD='synthetic',
        index=hashlib.sha256(b'').hexdigest())), 'utf-8')
    junit = tmp_path/'chosen.xml'
    junit.write_text(f'<testsuites><testsuite tests="3" failures="{failures}" errors="0" skipped="1"/></testsuites>', 'utf-8')
    monkeypatch.setattr(acceptance, 'ROOT', tmp_path)
    monkeypatch.setattr(acceptance, 'DELIVERY', [])
    monkeypatch.setattr(acceptance, 'git', lambda *args: b'synthetic' if args == ('rev-parse', 'HEAD') else b'')
    monkeypatch.setattr(sys, 'argv', ['acceptance', '--junit', 'chosen.xml', '--output', 'chosen-result.json'])
    assert acceptance.main() == (0 if failures == 0 else 1)
    value = json.loads((tmp_path/'chosen-result.json').read_text('utf-8'))
    assert value['status'] == expected and value['tests']['failures'] == failures
    assert not (tmp_path/'outputs/free_cloud/acceptance.json').exists()
    assert expected in capsys.readouterr().out
