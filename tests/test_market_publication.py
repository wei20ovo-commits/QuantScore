"""Artificial offline publication contracts; never evidence of live prices."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from unittest.mock import Mock,patch

import pandas as pd
import pytest

from app.snapshot_publication import (BASE,load_published_context,publish_market_context,
                                     target_trade_date,validate_calendar)
from app.web_snapshots import WebContextSnapshots,SnapshotIndustryService,SnapshotUnavailable
from app.web_results import load_screening_snapshot
from app.web_market import published_index_snapshots
from app.market_update import daily_update
from app.screening.policy import ScreeningPolicy
from test_web_snapshots import published,DAY
from test_stage2_service import service
from test_web_product import publish

def promote(root,day=DAY):
    return publish_market_context(root,'outputs/current/screening_details.json',
        'data/published/market_context/manifest.json',expected_trade_date=day)

def pointer(root):return (root/BASE/'current.json').read_bytes()

def calendar():
    return dict(schema_version=1,source='OFFLINE_TEST_ONLY',is_mock=False,data_status='VALID',days=[
        dict(date='2026-10-09',is_trading_day=True),
        dict(date='2026-10-10',is_trading_day=False),
        dict(date='2026-10-11',is_trading_day=False),
        dict(date='2026-10-12',is_trading_day=True)])

@pytest.mark.parametrize('stamp,status,day',[
    ('2026-10-09T15:59:59+08:00','UNKNOWN',None),
    ('2026-10-09T16:00:00+08:00','READY','2026-10-09'),
    ('2026-10-10T17:00:00+08:00','NON_TRADING_DAY','2026-10-09'),
    ('2026-10-12T15:59:59+08:00','MARKET_NOT_CLOSED','2026-10-09'),
    ('2026-10-12T08:00:00+00:00','READY','2026-10-12'),
    ('2026-10-13T17:00:00+08:00','UNKNOWN',None)])
def test_explicit_calendar_and_cutoff(stamp,status,day):
    assert target_trade_date(calendar(),datetime.fromisoformat(stamp))==dict(status=status,target_trade_date=day)

@pytest.mark.parametrize('kind',['gap','duplicate','mock','flag','source','status','naive'])
def test_invalid_calendar_refused(kind):
    c=calendar();now=datetime.fromisoformat('2026-10-12T17:00:00+08:00')
    if kind=='gap':c['days'].pop(1)
    elif kind=='duplicate':c['days'][1]=c['days'][0]
    elif kind=='mock':c['is_mock']=True
    elif kind=='flag':c['days'][0]['is_trading_day']=1
    elif kind=='source':c['source']=''
    elif kind=='status':c['data_status']='DATA_STALE'
    else:now=now.replace(tzinfo=None)
    with pytest.raises(ValueError):target_trade_date(c,now)

def test_atomic_publication_pins_both_readers_and_idempotence(published):
    root,expected,_=published
    legacy=WebContextSnapshots(root)
    result=promote(root);first=pointer(root)
    assert promote(root).generation==result.generation and pointer(root)==first
    current=WebContextSnapshots(root)
    assert current.industry('600519.SH',DAY)==legacy.industry('600519.SH',DAY)
    pd.testing.assert_frame_equal(current.benchmark(DAY,'2000-01-01',DAY),legacy.benchmark(DAY,'2000-01-01',DAY))
    assert load_screening_snapshot(root).payload==expected
    assert result.generation.startswith(DAY+'-')
    assert published_index_snapshots(root)[0]['date']==DAY
    # A constructed request continues to use its own immutable generation,
    # even if a later same-day corrected publication changes the pointer.
    path=root/'data/published/market_context/benchmark.csv'
    frame=pd.read_csv(path);frame['close']=[10.1,11.1];frame.to_csv(path,index=False)
    manifest=json.loads((root/'data/published/market_context/manifest.json').read_text())
    manifest['sha256']=sha256(path.read_bytes()).hexdigest()
    (root/'data/published/market_context/manifest.json').write_text(json.dumps(manifest))
    corrected=promote(root)
    assert corrected.generation!=result.generation
    assert current.benchmark(DAY,'2000-01-01',DAY).close.tolist()==[10.,11.]
    assert WebContextSnapshots(root).benchmark(DAY,'2000-01-01',DAY).close.tolist()==[10.1,11.1]

@pytest.mark.parametrize('kind',['hash','date','version','mock','scope','incomplete','empty','privacy','nonfinite','rows','rule_date'])
def test_rejected_publication_keeps_last_good(published,kind):
    root,payload,manifest=published;promote(root);before=pointer(root)
    if kind=='hash':manifest['sha256']='0'*64
    elif kind=='date':manifest['trade_date']='2026-09-29'
    elif kind=='version':payload['spec_version']='1.3'
    elif kind=='mock':payload['is_mock']=True
    elif kind=='scope':payload['operational_limit_industries']=1
    elif kind=='incomplete':payload['complete']=False
    elif kind=='empty':payload.update(sectors=[],industry_universe_total=0)
    elif kind=='privacy':payload['errors']=[{'error':'D:/Users/PRIVATE_TEST/path'}]
    elif kind=='nonfinite':payload['sectors'][0]['sector_heat']=float('nan')
    elif kind=='rows':manifest['rows']=99
    elif kind=='rule_date':payload['sectors'][0]['context']['sector_heat']['s1']['source_date']='2026-09-29'
    publish(root,payload)
    (root/'data/published/market_context/manifest.json').write_text(json.dumps(manifest))
    with pytest.raises((ValueError,TypeError)):promote(root)
    assert pointer(root)==before
    assert load_published_context(root).trade_date==DAY

def test_failed_final_replace_keeps_pointer(published):
    root,_,_=published;promote(root);before=pointer(root)
    path=root/'outputs/current/screening_details.json';data=json.loads(path.read_text('utf-8'))
    data['generated_at']='2026-10-02T18:00:00+00:00';path.write_text(json.dumps(data))
    with patch('app.snapshot_publication.os.replace',side_effect=PermissionError('PRIVATE_TEST')),pytest.raises(PermissionError):promote(root)
    assert pointer(root)==before
    assert not (root/BASE/'.publish.lock').exists()
    assert not list((root/BASE).glob('.current-*'))

def test_publisher_lock_and_rollback(published):
    root,_,_=published;promote(root);before=pointer(root)
    (root/BASE/'.publish.lock').touch()
    with pytest.raises(FileExistsError):promote(root)
    assert pointer(root)==before
    assert (root/BASE/'.publish.lock').exists() # never remove someone else's lock
    (root/BASE/'.publish.lock').unlink()
    with pytest.raises(ValueError):promote(root,'2026-09-29')
    assert pointer(root)==before

@pytest.mark.parametrize('kind',['pointer','pointer_list','payload','missing','escape'])
def test_corrupt_pointer_never_falls_back_to_valid_legacy(published,kind):
    root,_,_=published;generation=promote(root)
    if kind=='pointer':(root/BASE/'current.json').write_text('{}')
    elif kind=='pointer_list':(root/BASE/'current.json').write_text('[]')
    elif kind=='payload':(generation.directory/'screening.json').write_text('{}')
    elif kind=='missing':(generation.directory/'benchmark.csv').unlink()
    else:
        p=json.loads(pointer(root));p['generation']='../../escape'
        (root/BASE/'current.json').write_text(json.dumps(p))
    assert load_screening_snapshot(root).status=='DATA_ERROR'
    snapshots=WebContextSnapshots(root)
    assert snapshots.industry('600519.SH',DAY)['data_status']=='DATA_ERROR'
    assert snapshots.published_benchmark_date is None
    with pytest.raises(SnapshotUnavailable):snapshots.benchmark(DAY,'2000-01-01',DAY)
    assert published_index_snapshots(root)==[]

def test_generation_stale_remains_stale(published):
    root,_,_=published;promote(root);snapshot=WebContextSnapshots(root)
    assert snapshot.industry('600519.SH','2026-10-14')['data_status']=='DATA_STALE'
    with pytest.raises(SnapshotUnavailable,match='STALE'):snapshot.benchmark('2026-10-14','2000-01-01','2026-10-14')

def test_41_rules_scores_risk_b1_b2_and_candidate_equivalent(published,service):
    root,payload,manifest=published
    data=service.provider_manager.fetch('000001');day=str(data.bars.date.iloc[-1].date())
    payload['trade_date']=day
    for row in payload['sectors']+payload['stocks']:row['trade_date']=day
    payload['stocks'][0]['symbol']='000001.SZ';payload['stocks'][0]['primary_industry']='C15'
    context=payload['sectors'][0]['context'];context['primary_industry'].update(symbol='000001.SZ',as_of=day)
    context['sector_heat']['trade_date']=day
    context['sector_heat']['s1']['source_date']=day
    dates=data.bars.tail(6).date.dt.strftime('%Y-%m-%d').tolist()
    context['returns'].update(trade_dates=dates,window_start=dates[0],window_end=day)
    path=root/manifest['file']
    bench=data.benchmark.rename(columns={k+'_raw':k for k in ('open','high','low','close')})
    bench=bench.assign(symbol='000001.SH')[['date','symbol','open','high','low','close']].copy()
    bench.to_csv(path,index=False)
    manifest.update(trade_date=day,rows=len(bench),sha256=sha256(path.read_bytes()).hexdigest())
    (root/'data/published/market_context/manifest.json').write_text(json.dumps(manifest))
    publish(root,payload)
    service.provider_manager.fetch('000001',as_of=day)
    service.industry_service=SnapshotIndustryService(WebContextSnapshots(root))
    before=service.analyze('000001',as_of=day).to_dict()
    promote(root,day)
    service.industry_service=SnapshotIndustryService(WebContextSnapshots(root))
    after=service.analyze('000001',as_of=day).to_dict()
    for key in ('rules','score','risk_level','final_quant_score','industry_context'):
        assert before[key]==after[key]
    assert len(after['rules'])==41
    policy=ScreeningPolicy.current()
    assert policy.stock(before,day,'C15')==policy.stock(after,day,'C15')

@pytest.mark.parametrize('mode',['plan','before_close','nontrading','failed','stale','incomplete','success'])
def test_update_state_machine_no_false_publish(published,mode):
    root,payload,manifest=published;promote(root);before=pointer(root)
    provider=Mock(name='OFFLINE_PROVIDER');provider.name='baostock'
    adapter=Mock();adapter.provider=provider
    day=DAY;now=datetime.fromisoformat(day+'T17:00:00+08:00')
    cal=dict(schema_version=1,source='OFFLINE_TEST_ONLY',is_mock=False,data_status='VALID',days=[
        {'date':'2026-09-29','is_trading_day':True},{'date':day,'is_trading_day':mode!='nontrading'}])
    if mode=='before_close':now=now.replace(hour=15)
    frame=pd.read_csv(root/manifest['file']);frame.attrs['last_updated']=100
    adapter.cache.get.return_value=frame
    result=deepcopy(payload);result['complete']=mode!='incomplete'
    if mode=='stale':result['trade_date']='2026-09-29'
    if mode=='failed':result['status']='DATA_ERROR'
    def finished_scan(**kwargs):
        from app.market_update import write_json
        write_json(kwargs['output_dir']/'screening_details.json',result)
        return result
    with patch('app.market_update.read_live_calendar',return_value=cal), \
         patch('app.market_update.ScreeningService.run',side_effect=finished_scan) as scan:
        actual=daily_update(root,execute=mode!='plan',now=now,adapter=adapter)
    assert adapter.close.called
    if mode in ('plan','before_close','nontrading'):scan.assert_not_called()
    else:scan.assert_called_once()
    if mode=='success':assert actual['published'] and actual['status']=='PUBLISHED'
    else:assert not actual['published'] and pointer(root)==before

def test_same_event_copies_are_not_double_counted_but_repeats_survive():
    from app.web_diagnostics import safe_event,emit
    from app.web_observability import run_observed_analysis
    def call(_):
        event=emit(safe_event('analysis','OK',seconds=1))
        return {'data_status':{'status':'AVAILABLE'},'web_diagnostics':{'events':[deepcopy(event),deepcopy(event)]}}
    _,diag=run_observed_analysis('600519',call)
    assert len(diag['events'])==2
