"""Explicit artificial offline contracts; never substituted into live acceptance."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.web_results import (ROOT, STATUS_HELP, ScreeningSnapshot, active_rules, candidate_rows,
                             display_score, load_screening_snapshot, sector_rows)

WEB = ROOT / 'app/web.py'


def fixture_payload(matched=False):
    # Small transport-only fixture marked live to exercise the reader validation;
    # all UI use here is offline, not proof of any actual market result.
    rule = dict(rule_id='S1', rule_name='板块1日相对强度', score=16, max_score=20,
                status='PARTIAL', data_status='VALID', source_date='2026-09-30',
                explanation='OFFLINE TEST：真实页面不会使用此数据。', raw_inputs={'fixture': True})
    sector = dict(sector_id='C15', sector_name='C15测试行业', trade_date='2026-09-30',
                  sector_heat=70, data_status='VALID', candidate_status='ELIGIBLE', constituent_count=47,
                  context={'sector_heat': {'s1': rule}, 'provenance': {'provider': 'offline-test'}})
    stock = dict(symbol='600519.SH', stock_name='测试名称', industry_name='测试行业',
                 sector_heat=70, B1=5, B2=None, QuantScore=80, Risk='LOW', trade_date='2026-09-30',
                 data_status='VALID', candidate_status='MATCHED' if matched else 'NOT_MATCHED')
    return dict(is_mock=False, mode='live', scope='SH_SZ_PRIMARY_INDUSTRIES', status='PARTIAL',
                trade_date='2026-09-30', end_time='2026-10-02T17:02:30+00:00', industry_universe_total=1,
                operational_limit_industries=None, sectors=[sector], stocks=[stock],
                candidates=[deepcopy(stock)] if matched else [],
                stats=dict(industry_total=1, industry_scoreable=1, industry_candidate=1, industry_invalid=0,
                           stock_expected=1, stock_analyzed=1, stock_error=0, stock_incomplete=0,
                           strategy_match_candidates=int(matched)))


@pytest.fixture
def snapshot():
    return ScreeningSnapshot('VALID', source='outputs/test-only/screening_details.json', payload=fixture_payload())


@pytest.fixture(autouse=True)
def offline_ui():
    st.cache_data.clear()
    with patch('app.web_market.load_index_snapshots', return_value=[]):
        yield
    st.cache_data.clear()


def publish(root, payload, relative='outputs/current/screening_details.json'):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), 'utf-8')
    return path


def settings(root, paths):
    (root / 'config').mkdir(exist_ok=True)
    (root / 'config/web.yaml').write_text('screening_results:\n' + ''.join(f'  - {p}\n' for p in paths), 'utf-8')


def test_dashboard_reads_backend_stats(snapshot):
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot):
        app = AppTest.from_file(str(WEB)).run()
    assert not app.exception
    captions = '\n'.join(x.value for x in app.caption)
    assert '2026-09-30' in captions and '2026-10-02T17:02:30+00:00' in captions
    assert 'offline-test' in captions and 'PARTIAL' in captions


def test_missing_files_is_read_only_and_not_zero_score(tmp_path):
    settings(tmp_path, ['outputs/current/screening_details.json'])
    with patch.object(Path, 'mkdir', side_effect=AssertionError('reader must not write')):
        result = load_screening_snapshot(tmp_path)
    assert result.status == 'UNKNOWN' and not result.available
    assert '暂无最新筛选结果' in result.message
    assert not (tmp_path / 'outputs').exists()


def test_latest_by_date_and_generation_not_file_mtime(tmp_path):
    settings(tmp_path, ['outputs/older/screening_details.json', 'outputs/newer/screening_details.json'])
    older = fixture_payload()
    newer = deepcopy(older)
    newer['end_time'] = '2026-10-03T12:00:00+00:00'
    publish(tmp_path, newer, 'outputs/newer/screening_details.json')
    publish(tmp_path, older, 'outputs/older/screening_details.json')
    result = load_screening_snapshot(tmp_path)
    assert result.source == 'outputs/newer/screening_details.json'
    assert result.payload == newer


@pytest.mark.parametrize('mutation', [
    {'is_mock': True}, {'mode': 'archive'}, {'status': 'RUNNING'}, {'status': 'STOPPED'},
    {'complete': False}, {'operational_limit_industries': 3}, {'industry_universe_total': 2},
    {'end_time': None}, {'end_time': '2026-09-30T12:00:00'}, {'trade_date': 'invalid'},
    {'stocks': []}, {'candidates': [{}]}, {'stats': {}},
])
def test_reject_invalid_unfinished_or_benchmark_as_official(tmp_path, mutation):
    settings(tmp_path, ['outputs/current/screening_details.json'])
    payload = fixture_payload()
    payload.update(mutation)
    publish(tmp_path, payload)
    result = load_screening_snapshot(tmp_path)
    assert result.status == 'DATA_ERROR' and not result.available


@pytest.mark.parametrize('value', ['../outside.json', 'D:/private.json', '/private.json', 'outputs\\test.json'])
def test_paths_cannot_escape_or_depend_on_windows(tmp_path, value):
    settings(tmp_path, [value])
    assert load_screening_snapshot(tmp_path).status == 'DATA_ERROR'


def test_corrupt_file_no_silent_substitution(tmp_path):
    settings(tmp_path, ['outputs/current/screening_details.json'])
    path = publish(tmp_path, fixture_payload())
    path.write_text('not JSON', 'utf-8')
    assert load_screening_snapshot(tmp_path).status == 'DATA_ERROR'


@pytest.mark.parametrize('status', list(STATUS_HELP))
def test_invalid_data_never_presented_as_zero(status, snapshot):
    snapshot.payload['sectors'][0]['data_status'] = status
    snapshot.payload['sectors'][0]['sector_heat'] = 0
    snapshot.payload['sectors'][0]['context']['sector_heat']['s1']['data_status'] = status
    snapshot.payload['sectors'][0]['context']['sector_heat']['s1']['score'] = 0
    row = sector_rows(snapshot)[0]
    assert row['SectorHeat'] == (0 if status == 'VALID' else None)
    assert row['S1'] == (0 if status == 'VALID' else None)


def test_sector_search_sort_missing_last(snapshot):
    valid = deepcopy(snapshot.payload['sectors'][0])
    valid.update(sector_id='C16', sector_name='C16另一个行业', sector_heat=20)
    invalid = deepcopy(valid)
    invalid.update(sector_id='C17', sector_name='C17缺项', sector_heat=None, data_status='DATA_ERROR')
    snapshot.payload['sectors'].extend([invalid, valid])
    assert [r['行业代码'] for r in sector_rows(snapshot)] == ['C15', 'C16', 'C17']
    assert [r['行业代码'] for r in sector_rows(snapshot, descending=False)] == ['C16', 'C15', 'C17']
    assert sector_rows(snapshot, '测试')[0]['行业代码'] == 'C15'


def test_candidates_use_backend_membership_without_adding_gates(snapshot):
    assert candidate_rows(snapshot) == []
    snapshot.payload = fixture_payload(True)
    rows = candidate_rows(snapshot)
    assert len(rows) == 1 and rows[0]['QuantScore'] == 80 and rows[0]['B2'] is None
    # Reader is presentation, not another candidate classifier.
    snapshot.payload['candidates'][0]['QuantScore'] = 79
    assert candidate_rows(snapshot)[0]['QuantScore'] == 79


def test_active_registry_uses_audited_sector_implementation_and_freeze():
    rules = active_rules()
    assert len(rules) == 48 and {r['category'] for r in rules} == set('ABCDEFRS')
    assert sum(r['code_status'] == 'IMPLEMENTED' for r in rules) == 44
    assert all(r['spec_version'] == '1.4' for r in rules)
    sector = {r['rule_id']: r for r in rules if r['category'] == 'S'}
    assert 'expected分母' in sector['S7']['purpose']
    assert '真实涨停价' in sector['S4']['purpose']
    assert all('STAGE3B_RULE_FREEZE' in r['active_source'] for r in sector.values())


@pytest.mark.parametrize('view', ['sectors', 'candidates', 'rules'])
def test_navigation_no_scan_or_auto_analysis(view, snapshot):
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot), \
         patch('app.screening.service.ScreeningService.run', side_effect=AssertionError('No full scan')) as scan, \
         patch('app.web_backend.analyze_stock', side_effect=AssertionError('No automatic analysis')) as stock:
        app = AppTest.from_file(str(WEB)).run()
        app.button(key='nav_' + view).click().run()
        assert not app.exception
        if view == 'rules':
            assert len(app.expander) == 49  # 48 ACTIVE rules plus shared status legend
        elif view == 'sectors':
            assert len(app.dataframe[0].value) == 1
        else:
            assert not app.dataframe  # 0 real/backend candidates
        scan.assert_not_called()
        stock.assert_not_called()


def test_nonempty_candidate_page(snapshot):
    snapshot.payload = fixture_payload(True)
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot):
        app = AppTest.from_file(str(WEB)).run()
        app.button(key='nav_candidates').click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]['symbol'] == '600519.SH'
    assert set(app.dataframe[0].value.columns) == {'symbol', 'stock_name', 'industry', 'SectorHeat', 'B1', 'B2', 'QuantScore', 'Risk', 'trade_date', 'data_status'}


@pytest.mark.parametrize('view,expected', [('sectors', 1), ('rules', 48)])
def test_dark_native_table_preserves_underlying_results(view, expected, snapshot):
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot):
        app = AppTest.from_file(str(WEB)).run()
        app.button(key='theme_toggle').click().run()
        app.button(key='nav_' + view).click().run()
    assert not app.exception and app.session_state['theme'] == 'dark'
    assert len(app.dataframe[0].value) == expected


def test_data_error_sector_page_has_missing_score_and_explicit_status(snapshot):
    sector = snapshot.payload['sectors'][0]
    sector.update(data_status='DATA_ERROR', sector_heat=None, candidate_status='NOT_EVALUABLE')
    sector['context'] = {'data_status': 'DATA_ERROR', 'reason_code': 'OFFLINE_TEST_ERROR'}
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot):
        app = AppTest.from_file(str(WEB)).run()
        app.button(key='nav_sectors').click().run()
    assert not app.exception
    row = app.dataframe[0].value.iloc[0]
    assert row['SectorHeat'] is None and row['数据状态'] == 'DATA_ERROR'
    assert any('不能以零分填充' in x.value for x in app.info)


def test_formal_reader_rejects_missing_display_identity(tmp_path):
    settings(tmp_path, ['outputs/current/screening_details.json'])
    payload = fixture_payload()
    del payload['sectors'][0]['sector_name']
    publish(tmp_path, payload)
    assert load_screening_snapshot(tmp_path).status == 'DATA_ERROR'


def test_formal_reader_rejects_drifted_candidate_scores(tmp_path):
    settings(tmp_path, ['outputs/current/screening_details.json'])
    payload = fixture_payload(True)
    payload['candidates'][0]['QuantScore'] = 90
    publish(tmp_path, payload)
    assert load_screening_snapshot(tmp_path).status == 'DATA_ERROR'


@pytest.mark.parametrize('status', ['UNKNOWN', 'DATA_ERROR'])
@pytest.mark.parametrize('view', ['home', 'sectors', 'candidates'])
def test_missing_or_bad_snapshot_ui_graceful(status, view):
    snapshot = ScreeningSnapshot(status, '暂无最新筛选结果' if status == 'UNKNOWN' else '正式结果无法读取')
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot):
        app = AppTest.from_file(str(WEB)).run()
        app.button(key='nav_' + view).click().run()
    assert not app.exception and not app.dataframe
    assert (app.error if status == 'DATA_ERROR' else app.info)


def test_rules_page_independent_of_prior_stock_session(snapshot):
    with patch('app.web_results.load_screening_snapshot', return_value=snapshot):
        app = AppTest.from_file(str(WEB)).run()
        app.session_state['analysis'] = {'not_a_rules_registry': True}
        app.button(key='nav_rules').click().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 48


def test_web_presentation_does_not_import_scanner_or_sector_scoring():
    import ast
    for name in ['web.py', 'web_results.py', 'web_pages.py', 'web_visuals.py']:
        tree = ast.parse((ROOT / 'app' / name).read_text('utf-8'))
        imported = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imported.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        assert not any(name.startswith(('app.screening', 'app.sector.scoring')) for name in imported)


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), True])
def test_nonfinite_and_missing_scores_display_unavailable(value):
    assert display_score(value) is None
