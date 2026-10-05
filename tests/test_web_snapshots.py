"""Offline contract tests: artificial data is not evidence of live market success."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time
from unittest.mock import patch

import pandas as pd
import pytest

from app.data.cache import CacheKey,DataCache
from app.data.models import DataError
from app.engine.rule_engine import RuleEngine
from app.rules.base import Context
from app.web_backend import create_web_service
from app.web_runtime import bounded_web_call
from app.web_snapshots import WebContextSnapshots,WebMarketCache,SnapshotUnavailable,SnapshotIndustryService
from test_web_product import fixture_payload,publish,settings
from test_stage2_service import service

DAY='2026-09-30'


@pytest.fixture
def published(tmp_path):
    settings(tmp_path,['outputs/current/screening_details.json'])
    payload=fixture_payload()
    payload.update(spec_version='1.4',assumption_version='v1.3',data_contract_version='1.4')
    payload['stocks'][0]['primary_industry']='C15'
    payload['sectors'][0]['context'].update(data_status='VALID',
        primary_industry=dict(symbol='000568.SZ',sector_id='C15',name='TEST INDUSTRY',as_of=DAY),
        returns=dict(data_status='VALID',sector_return_5d=.01,adjustment_type='qfq',
                     window_start='2026-09-22',window_end=DAY,
                     trade_dates=['2026-09-22','2026-09-23','2026-09-24','2026-09-28','2026-09-29',DAY]))
    payload['sectors'][0]['context']['sector_heat'].update(
        total_score=70,max_score=100,score_coverage=1,overall_status='VALID',sector_id='C15',trade_date=DAY)
    publish(tmp_path,payload)
    directory=tmp_path/'data/published/market_context';directory.mkdir(parents=True)
    path=directory/'benchmark.csv'
    pd.DataFrame(dict(date=['2026-09-29',DAY],symbol=['000001.SH']*2,
                      open=[10.,11.],high=[11.,12.],low=[9.,10.],close=[10.,11.])).to_csv(path,index=False)
    manifest=dict(provider='baostock',symbol='000001.SH',adjustment_type='NONE',is_mock=False,
                  data_status='VALID',trade_date=DAY,file='data/published/market_context/benchmark.csv',
                  rows=2,sha256=sha256(path.read_bytes()).hexdigest(),retrieved_at_epoch=100)
    (directory/'manifest.json').write_text(json.dumps(manifest),'utf-8')
    return tmp_path,payload,manifest


def change_benchmark(root,manifest):
    (root/'data/published/market_context/manifest.json').write_text(json.dumps(manifest),'utf-8')


def test_same_day_industry_consumes_existing_context_without_mutation(published):
    root,payload,_=published; before=deepcopy(payload)
    adapter=WebContextSnapshots(root)
    actual=adapter.industry('600519.SH',DAY)
    assert actual['primary_industry']['symbol']=='600519.SH'
    expected=deepcopy(payload['sectors'][0]['context']);expected['primary_industry']['symbol']='600519.SH'
    assert actual==expected and payload==before
    actual['returns']['sector_return_5d']=999
    assert adapter.industry('600519.SH',DAY)['returns']['sector_return_5d']==.01


@pytest.mark.parametrize('status',['DATA_ERROR','DATA_STALE','DATA_INCONSISTENT','DATA_INCOMPLETE'])
def test_invalid_industry_preserves_data_status(published,status):
    root,payload,_=published
    payload['sectors'][0]['context']['data_status']=status;publish(root,payload)
    result=WebContextSnapshots(root).industry('600519.SH',DAY)
    assert result['data_status']==status


@pytest.mark.parametrize('kind,status',[
    ('missing','DATA_ERROR'),('date','DATA_STALE'),('membership','DATA_ERROR'),
    ('version','DATA_INCONSISTENT'),('primary_date','DATA_STALE'),('primary_id','DATA_INCONSISTENT'),
    ('corrupt_membership','DATA_INCONSISTENT')])
def test_missing_stale_inconsistent_industry_does_not_become_zero(published,kind,status):
    root,payload,_=published;day=DAY;symbol='600519.SH'
    if kind=='missing':(root/'outputs/current/screening_details.json').unlink()
    elif kind=='date':day='2026-10-08'
    elif kind=='membership':symbol='600000.SH'
    elif kind=='version':payload['spec_version']='1.3';publish(root,payload)
    elif kind=='primary_date':payload['sectors'][0]['context']['primary_industry']['as_of']='2026-09-29';publish(root,payload)
    elif kind=='primary_id':payload['sectors'][0]['context']['primary_industry']['sector_id']='C16';publish(root,payload)
    elif kind=='corrupt_membership':payload['sectors'][0]['context']['sector_heat']['s4']={'raw_inputs':{'limit_details':None}};publish(root,payload)
    context=WebContextSnapshots(root).industry(symbol,day)
    assert context['data_status']==status
    engine=RuleEngine();bars=pd.DataFrame({'date':pd.to_datetime([day])})
    for rid in ['B1','B2']:
        result=engine.evaluate(rid,Context(bars,metadata={'industry_context':context,'symbol':symbol}))
        assert result.status=='UNKNOWN' and result.score is None


def test_heat_incomplete_does_not_cancel_valid_independent_b2(published):
    root,payload,_=published
    context=payload['sectors'][0]['context'];context['sector_heat'].update(overall_status='DATA_INCOMPLETE',total_score=None)
    publish(root,payload);context=WebContextSnapshots(root).industry('600519.SH',DAY)
    bars=pd.DataFrame({'date':pd.to_datetime(context['returns']['trade_dates']),'close_adj':[10,10,10,10,10,11]})
    ctx=Context(bars,metadata={'symbol':'600519.SH','industry_context':context,'adjustment_type':'qfq'})
    engine=RuleEngine();b1=engine.evaluate('B1',ctx);b2=engine.evaluate('B2',ctx)
    assert b1.status=='UNKNOWN' and b1.score is None
    assert b2.score is not None and b2.raw_values['data_status']=='VALID'


def test_constituents_not_in_scanned_stock_list_use_s4_expected_list(published):
    root,payload,_=published
    payload['sectors'][0]['context']['sector_heat']['s4']={'raw_inputs':{'limit_details':[{'symbol':'600000.SH','closed_at_limit_up':False}]}}
    publish(root,payload)
    assert WebContextSnapshots(root).industry('600000.SH',DAY)['data_status']=='VALID'


def test_benchmark_uses_verified_same_date_and_actual_prices(published):
    root,_,_=published
    adapter=WebContextSnapshots(root);frame=adapter.benchmark(DAY,'2000-01-01',DAY)
    assert frame.close.tolist()==[10.,11.] and frame.attrs['cache_hit']
    assert adapter.benchmark_evidence['status']=='VALID'


@pytest.mark.parametrize('kind,reason',[
    ('missing','DATA_ERROR'),('date','DATA_STALE'),('hash','DATA_INCONSISTENT'),
    ('symbol','DATA_INCONSISTENT'),('provider','DATA_INCONSISTENT'),('rows','DATA_INCONSISTENT'),
    ('escape','DATA_ERROR'),('mock','DATA_ERROR'),('status','DATA_ERROR'),('invalid_ohlc','DATA_ERROR')])
def test_benchmark_invalid_evidence_cannot_trigger_live_fetch(published,kind,reason):
    root,_,manifest=published
    if kind=='missing':(root/'data/published/market_context/manifest.json').unlink()
    else:
        if kind=='date':manifest['trade_date']='2026-09-29'
        elif kind=='hash':manifest['sha256']='0'*64
        elif kind=='symbol':manifest['symbol']='000300.SH'
        elif kind=='provider':manifest['provider']='unverified'
        elif kind=='rows':manifest['rows']=3
        elif kind=='escape':manifest['file']='../escape.csv'
        elif kind=='mock':manifest['is_mock']=True
        elif kind=='status':manifest['data_status']='DATA_ERROR'
        elif kind=='invalid_ohlc':
            p=root/manifest['file'];p.write_text('date,symbol,open,high,low,close\n2026-09-30,000001.SH,10,9,8,11\n','utf-8')
            manifest['sha256']=sha256(p.read_bytes()).hexdigest()
        change_benchmark(root,manifest)
    with pytest.raises(SnapshotUnavailable,match=reason):
        WebContextSnapshots(root).benchmark(DAY,'2000-01-01',DAY)


def test_benchmark_rejects_cached_old_date_even_with_valid_persistent_ttl(published):
    root,_,manifest=published;manifest['trade_date']='2026-09-29';change_benchmark(root,manifest)
    persistent=DataCache(root/'cache.sqlite');key=CacheKey('baostock','000001.SH','2000-01-01',DAY,'NONE')
    persistent.put(key,pd.DataFrame({'date':pd.to_datetime(['2026-09-29'])}))
    memo=WebMarketCache(persistent,WebContextSnapshots(root));memo.stock_day=DAY
    with pytest.raises(SnapshotUnavailable,match='DATA_STALE'):memo.get(key)


def test_factory_never_instantiates_live_industry_and_disables_network_benchmark(published):
    root,_,_=published
    with patch('app.sector.industry_context.PrimaryIndustryService',side_effect=AssertionError('No live industry')):
        service=create_web_service(root,DataCache(root/'cache.sqlite'))
    for provider in service.provider_manager.providers:
        with pytest.raises(SnapshotUnavailable):provider.fetch_benchmark('2000-01-01',DAY)
    assert service.industry_service.build('600519.SH',DAY)['data_status']=='VALID'


def test_all_41_results_identical_for_same_inputs_and_snapshots(published,service):
    # Small artificial offline fixture exercises both acquisition interfaces,
    # same cached stock, benchmark, frozen R7 state, and the real unchanged engines.
    from unittest.mock import Mock
    root,payload,_=published
    manager=service.provider_manager
    data=manager.fetch('000001');day=str(data.bars.date.iloc[-1].date())
    payload['trade_date']=day
    for row in payload['sectors']+payload['stocks']:row['trade_date']=day
    stock=payload['stocks'][0];stock['symbol']='000001.SZ'
    context=payload['sectors'][0]['context'];context['primary_industry'].update(symbol='000001.SZ',as_of=day)
    context['sector_heat']['trade_date']=day
    dates=data.bars.tail(6).date.dt.strftime('%Y-%m-%d').tolist()
    context['returns'].update(trade_dates=dates,window_start=dates[0],window_end=day)
    publish(root,payload)
    manager.fetch('000001',as_of=day)  # Prime identical data acquisition provenance.
    service.industry_service=Mock();service.industry_service.build.return_value=deepcopy(context)
    original=service.analyze('000001',as_of=day).to_dict()
    service.industry_service=SnapshotIndustryService(WebContextSnapshots(root))
    optimized=service.analyze('000001',as_of=day).to_dict()
    assert len(original['rules'])==41
    assert original['rules']==optimized['rules']
    assert original['score']==optimized['score']
    assert original['industry_context']==optimized['industry_context']
    assert original['risk_level']==optimized['risk_level']
    assert original['final_quant_score']==optimized['final_quant_score']


# Top-level functions are picklable under Windows spawn; these are runtime-only
# fixtures, never market data or evidence of successful real analysis.
def successful_target():return {'fixture':True}
def failed_target():raise RuntimeError('private error must never leave worker')
def hanging_target():time.sleep(20)


def test_runtime_success_and_owned_directory_cleanup(tmp_path):
    value=bounded_web_call(successful_target,(),root=tmp_path,seconds=15)
    assert value['fixture'] and value['web_latency']['total_backend_seconds']<15
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


def test_runtime_failure_sanitizes_provider_exception(tmp_path):
    with pytest.raises(DataError) as exc:bounded_web_call(failed_target,(),root=tmp_path,seconds=15)
    assert 'private error' not in str(exc.value)
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


def test_runtime_enforces_deadline_and_cleans_worker(tmp_path):
    started=time.monotonic()
    with pytest.raises(DataError,match='运行时限'):bounded_web_call(hanging_target,(),root=tmp_path,seconds=2)
    assert time.monotonic()-started<7
    assert not list((tmp_path/'outputs/runtime/web-jobs').iterdir())


@pytest.mark.parametrize('seconds',[0,-1,241])
def test_runtime_cannot_silently_extend_deadline(tmp_path,seconds):
    with pytest.raises(ValueError):bounded_web_call(successful_target,(),root=tmp_path,seconds=seconds)
