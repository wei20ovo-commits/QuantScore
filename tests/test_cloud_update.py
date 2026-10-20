"""Offline transport/control tests. No synthetic frame is live update evidence."""
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
from dataclasses import asdict

import pandas as pd
import pytest
import yaml

from app.cloud_state import pack_state, unpack_state, fingerprint
from app.cloud_update import publication_gate, finish_publication, run_slice
from app.data.cache import DataCache, CacheKey
from app.screening.checkpoint import CheckpointStore
from app.screening.policy import ScreeningPolicy
from app.screening.runtime import RuntimeLimits, RunControl
from app.screening.service import ScreeningService
from app.screening.replay import ArchivedScreeningAdapter
from app.snapshot_publication import BASE
from test_web_snapshots import published, DAY
from test_market_publication import promote, pointer
from test_stage2_service import service

CODE='a'*64


def seed(tmp_path):
    work=tmp_path/'seed'
    cache=DataCache(work/'cache/market.sqlite3',clock=lambda:1234)
    key=CacheKey('baostock','600519.SH','2026-09-01',DAY,'raw')
    frame=pd.DataFrame({'date':pd.to_datetime([DAY]),'close':[10.]})
    cache.put(key,frame)
    with sqlite3.connect(cache.path) as db:
        db.execute('CREATE TABLE score_snapshots (symbol TEXT,day TEXT,version TEXT,payload TEXT,PRIMARY KEY(symbol,day,version))')
        db.execute('INSERT INTO score_snapshots VALUES (?,?,?,?)',('600519.SH',DAY,'1.4','{"signal_close":10}'))
    bundle=tmp_path/'state.gz'
    return work,bundle,cache,key


def export(work,bundle):
    return pack_state(work,bundle,source_fingerprint=CODE,trade_date=DAY,producer='123')


def test_transport_keeps_cache_dates_ttl_and_r7_frozen_evidence(tmp_path):
    work,bundle,cache,key=seed(tmp_path)
    info=export(work,bundle)
    destination=tmp_path/'restored'
    header=unpack_state(bundle,destination,source_fingerprint=CODE)
    assert header['trade_date']==DAY and info['compressed_bytes']>0
    restored=DataCache(destination/'cache/market.sqlite3',clock=lambda:5000)
    assert restored.get(key) is None # transport must not freshen a stale TTL
    with sqlite3.connect(restored.path) as db:
        assert db.execute('SELECT last_updated FROM frames').fetchone()[0]==1234
        assert db.execute('SELECT payload FROM score_snapshots').fetchone()[0]=='{"signal_close":10}'
    assert cache.path.exists() # original evidence never replaced


def test_expired_query_pruning_never_removes_r7_or_relabels_old_data(tmp_path):
    work,bundle,cache,key=seed(tmp_path)
    info=pack_state(work,bundle,source_fingerprint=CODE,trade_date=DAY,producer='1',frame_cutoff_epoch=1235)
    unpack_state(bundle,tmp_path/'new',source_fingerprint=CODE)
    restored=DataCache(tmp_path/'new/cache/market.sqlite3')
    assert info['expired_frames_omitted']==1 and restored.get(key) is None
    with sqlite3.connect(restored.path) as db:
        assert db.execute('SELECT count(*) FROM score_snapshots').fetchone()[0]==1
    with sqlite3.connect(cache.path) as db:
        assert db.execute('SELECT count(*) FROM frames').fetchone()[0]==1


def test_transport_history_and_score_fingerprints_exact(tmp_path):
    from app.screening.history_cache import HistoryCache
    from app.screening.score_cache import ScoreMemo
    work,bundle,_,_=seed(tmp_path)
    h=HistoryCache(work/'cache/screening_history.sqlite3')
    s=ScoreMemo(work/'cache/screening_scores.sqlite3')
    for path,table,values in [(h.path,'history_v1',('k','{"fetched_at":1234}','{"data":[]}')),
                              (s.path,'score_memo_v1',('source-and-input-digest','{"rules":[]}'))]:
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values)+')',values)
    export(work,bundle);unpack_state(bundle,tmp_path/'new',source_fingerprint=CODE)
    for original in (h.path,s.path):
        restored=tmp_path/'new/cache'/original.name
        with sqlite3.connect(original) as a,sqlite3.connect(restored) as b:
            table='history_v1' if original==h.path else 'score_memo_v1'
            assert a.execute('SELECT * FROM '+table).fetchall()==b.execute('SELECT * FROM '+table).fetchall()


def rewrite(bundle,change):
    records=[json.loads(line) for line in gzip.decompress(bundle.read_bytes()).splitlines()]
    change(records)
    lines=[json.dumps(r,ensure_ascii=False,separators=(',',':')).encode()+b'\n' for r in records[:-1]]
    records[-1]=dict(kind='end',records=len(lines),sha256=hashlib.sha256(b''.join(lines)).hexdigest())
    bundle.write_bytes(gzip.compress(b''.join(lines)+json.dumps(records[-1]).encode()+b'\n'))


@pytest.mark.parametrize('kind',['fingerprint','truncated','digest','trailing','unknown_table','private','traversal','duplicate','date'])
def test_corrupt_handoff_never_installs_partial_state(tmp_path,kind):
    work,bundle,_,_=seed(tmp_path)
    (work/'run').mkdir();(work/'run/calendar.json').write_text('{"data_status":"VALID"}')
    export(work,bundle)
    if kind=='fingerprint':rewrite(bundle,lambda rs:rs[0].update(fingerprint='b'*64))
    elif kind=='truncated':bundle.write_bytes(bundle.read_bytes()[:-10])
    elif kind=='digest':
        records=gzip.decompress(bundle.read_bytes()).replace(b'1234',b'1235')
        bundle.write_bytes(gzip.compress(records))
    elif kind=='trailing':bundle.write_bytes(gzip.compress(gzip.decompress(bundle.read_bytes())+b'{}\n'))
    elif kind=='unknown_table':rewrite(bundle,lambda rs:rs[1].update(table='arbitrary_sql'))
    elif kind=='private':rewrite(bundle,lambda rs:rs[-2].update(payload={'value':'sk-'+('x'*24)}))
    elif kind=='traversal':rewrite(bundle,lambda rs:rs[-2].update(path='run/../../escape.json'))
    elif kind=='duplicate':rewrite(bundle,lambda rs:rs.insert(-1,deepcopy(rs[-2])))
    elif kind=='date':rewrite(bundle,lambda rs:rs[0].update(trade_date='not-a-date'))
    with pytest.raises((ValueError,KeyError,EOFError,OSError,sqlite3.Error)):
        unpack_state(bundle,tmp_path/'destination',source_fingerprint=CODE)
    assert not (tmp_path/'destination').exists()
    assert not list(tmp_path.glob('destination.import-*'))
    assert (work/'cache/market.sqlite3').exists()


@pytest.mark.parametrize('limit',['MAX_COMPRESSED','MAX_EXPANDED','MAX_RECORD','MAX_RECORDS'])
def test_state_budget_failure_preserves_last_bundle(tmp_path,monkeypatch,limit):
    work,bundle,_,_=seed(tmp_path);export(work,bundle);before=bundle.read_bytes()
    monkeypatch.setattr('app.cloud_state.'+limit,1)
    with pytest.raises(ValueError):export(work,bundle)
    assert bundle.read_bytes()==before and not list(tmp_path.glob('*.partial'))


def test_private_export_is_rejected_without_leaving_partial(tmp_path):
    work,bundle,_,_=seed(tmp_path)
    (work/'run').mkdir();(work/'run/calendar.json').write_text(json.dumps({'path':'Z:'+chr(92)+'private'}))
    with pytest.raises(ValueError,match='PRIVATE'):export(work,bundle)
    assert not bundle.exists()


def archived():
    return ArchivedScreeningAdapter(archive_directory=Path(__file__).parent/'fixtures/screening_real',stage35_loader=lambda _:[])


def test_checkpoint_pause_transport_resume_matches_archive_and_candidate(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket,'connect',lambda *args:pytest.fail('offline replay attempted network'))
    baseline=ScreeningService(archived()).run(output_dir=tmp_path/'baseline')
    work=tmp_path/'one';directory=work/'run'
    pauses=0
    for index in range(4):
        clock=[0.]
        limits=RuntimeLimits(run_seconds=100,sector_seconds=60,stock_seconds=10)
        control=RunControl(limits,clock=lambda:clock[0])
        a=archived();original=a.sector
        def sector(*args,**kwargs):
            value=original(*args,**kwargs);clock[0]+=40;return value
        a.sector=sector
        final=ScreeningService(a)._run(None,None,False,directory,a,control=control,
                resume=index>0,boundary_reserve_seconds=2)
        if final['complete']:break
        assert final['status']=='STOPPED'
        assert all(row['data_status']!='DATA_ERROR' for row in final['sectors'])
        pauses+=1
        bundle=tmp_path/f'slice-{index}.gz'
        export(work,bundle)
        work=tmp_path/f'work-{index}'
        unpack_state(bundle,work,source_fingerprint=CODE)
        directory=work/'run'
    assert pauses>0 and final['complete']
    assert final['stocks']==baseline['stocks']
    assert final['candidates']==baseline['candidates']
    assert final['stats']==baseline['stats']
    # Universe/date/policy drift is refused by the existing checkpoint contract.
    d=json.loads((directory/'checkpoint.json').read_text('utf-8'))
    with pytest.raises(ValueError,match='INCOMPATIBLE'):
        CheckpointStore(directory).load(day='2026-10-01',policy=ScreeningPolicy.current(),
                                      universe=d['universe'],selected=d['selected'])


def test_same_input_all_41_rule_results_after_cache_transport(service,tmp_path):
    # Artificial offline stock data; this is a semantic regression, not a real
    # market update. Freeze the original JSON round trip before both scores.
    service.provider_manager.fetch('000001')
    service.analyze('000001') # establish the immutable R7 signal before BOTH inputs
    before=service.analyze('000001').to_dict()
    work=tmp_path/'work'
    (work/'cache').mkdir(parents=True)
    import shutil
    shutil.copyfile(service.provider_manager.cache.path,work/'cache/market.sqlite3')
    bundle=tmp_path/'score-state.gz'
    export(work,bundle);unpack_state(bundle,tmp_path/'after',source_fingerprint=CODE)
    service.provider_manager.cache=DataCache(tmp_path/'after/cache/market.sqlite3')
    after=service.analyze('000001').to_dict()
    assert len(after['rules'])==41
    for key in ('rules','score','risk_level','final_quant_score','industry_context'):
        assert before[key]==after[key]
    day=before['evaluation_date']
    assert ScreeningPolicy.current().stock(before,day,'C15')==ScreeningPolicy.current().stock(after,day,'C15')


@pytest.mark.parametrize('kind',['partial','day','mock','mode','limit','sector_error','stock_error','stale','inconsistent','universe_error'])
def test_failed_batches_do_not_update_formal_pointer(published,kind):
    root,result,_=published;promote(root);before=pointer(root)
    value=deepcopy(result)
    value.update(complete=True,is_mock=False,mode='live',status='COMPLETE')
    if kind=='partial':value['complete']=False
    elif kind=='day':value['trade_date']='2026-09-29'
    elif kind=='mock':value['is_mock']=True
    elif kind=='mode':value['mode']='archived-real-subset-replay'
    elif kind=='limit':value['operational_limit_industries']=1
    elif kind=='sector_error':value['sectors'][0]['error']='NETWORK_FAILURE'
    elif kind=='stock_error':value['stocks'][0]['data_status']='DATA_ERROR'
    elif kind=='stale':value['sectors'][0]['data_status']='DATA_STALE'
    elif kind=='inconsistent':value['sectors'][0]['data_status']='DATA_INCONSISTENT'
    elif kind=='universe_error':value['errors']=[dict(error='UNIVERSE_UNAVAILABLE')]
    with pytest.raises(ValueError):finish_publication(root,root/'outputs/current',Mock(),value,DAY)
    assert pointer(root)==before


def test_legal_unknown_not_replaced_with_zero_or_extra_coverage_gate():
    value=dict(trade_date=DAY,complete=True,status='PARTIAL',is_mock=False,mode='live',
               sectors=[dict(data_status='DATA_INCOMPLETE',sector_heat=None)],stocks=[],
               errors=[dict(error='SLICE_BOUNDARY_PAUSE')])
    publication_gate(value,DAY)
    assert value['sectors'][0]['sector_heat'] is None


def test_clean_pause_history_does_not_turn_complete_data_into_partial(tmp_path):
    class Offline:
        is_mock=True
        def prepare(self,refresh=False):
            return DAY,{sid:dict(name='OFFLINE ONLY',symbols=['600519.SH']) for sid in ('C15','C18')},[]
        def sector(self,sid,*args,**kwargs):
            clock[0]+=40
            return dict(data_status='VALID',primary_industry=dict(sector_id=sid),
                        sector_heat=dict(overall_status='VALID',trade_date=DAY,total_score=0))
        def metrics(self):return {}
    clock=[0.]
    a=Offline();s=ScreeningService(a)
    limits=RuntimeLimits(run_seconds=100,sector_seconds=60,stock_seconds=10)
    first=s._run(None,None,False,tmp_path,a,control=RunControl(limits,clock=lambda:clock[0]),boundary_reserve_seconds=2)
    assert first['status']=='STOPPED' and not first['errors']
    clock[0]=0
    final=s._run(None,None,False,tmp_path,a,control=RunControl(limits,clock=lambda:clock[0]),resume=True,boundary_reserve_seconds=2)
    assert final['status']=='COMPLETE' and final['complete'] and not final['errors']
    assert final['operational_pauses'][0]['reason_code']=='SLICE_BOUNDARY_PAUSE'


def test_source_fingerprint_is_computed_not_faked(tmp_path):
    (tmp_path/'app').mkdir();p=tmp_path/'app/source.py';p.write_text('one')
    first=fingerprint(tmp_path);p.write_text('two')
    assert fingerprint(tmp_path)!=first


def test_slice_missing_handoff_is_bounded_and_private(tmp_path):
    report=run_slice(tmp_path,slice_index=2,producer='1')
    assert report['status']=='BLOCKED' and report['reason_code']=='CLOUD_PREVIOUS_SLICE_MISSING'
    assert not report['published']
    text=(tmp_path/'outputs/runtime/cloud-update/status.json').read_text()
    assert str(tmp_path) not in text


def slice_fixture(monkeypatch,published):
    """Artificial orchestration fixture; real publisher and state transport."""
    root,payload,manifest=published
    result=deepcopy(payload)
    result.update(complete=True,status='COMPLETE',policy=asdict(ScreeningPolicy.current()),errors=[],
                  performance={},exclusions=[])
    universe={'C15':dict(name=result['sectors'][0]['sector_name'],symbols=[r['symbol'] for r in result['stocks']])}
    raw=pd.read_csv(root/manifest['file'],parse_dates=['date'])
    def factory(cache,control):
        cache.put(CacheKey('baostock','000001.SH','2000-01-01',DAY,'NONE'),raw.copy())
        return SimpleNamespace(provider=SimpleNamespace(name='baostock'),cache=cache,close=Mock(),metrics=lambda:{})
    monkeypatch.setattr('app.cloud_update.read_live_calendar',lambda *args:{'fixture':'OFFLINE ONLY'})
    monkeypatch.setattr('app.cloud_update.target_trade_date',lambda *args:dict(status='READY',target_trade_date=DAY))
    def scan(self,**kwargs):
        from app.screening.service import write_evidence
        directory=kwargs['output_dir']
        value=deepcopy(result)
        write_evidence(value,directory)
        CheckpointStore(directory).save(value,universe,['C15'])
        return value
    monkeypatch.setattr(ScreeningService,'run',scan)
    return root,result,universe,factory


def test_complete_slice_is_independently_validated_before_atomic_publication(published,monkeypatch):
    root,_,_,factory=slice_fixture(monkeypatch,published)
    report=run_slice(root,slice_index=1,producer='1',adapter_factory=factory)
    assert report['status']=='PUBLISHED_LOCALLY' and report['published']
    assert json.loads(pointer(root))['generation']==report['generation']
    assert (root/'outputs/runtime/cloud-update/transfer/state.jsonl.gz').exists()
    assert report['cloud_verified'] is False # offline test never claims cloud


def test_failed_state_export_cannot_switch_snapshot_pointer(published,monkeypatch):
    root,_,_,factory=slice_fixture(monkeypatch,published)
    promote(root);before=pointer(root)
    def fail(*args,**kwargs):raise ValueError('STATE_STORAGE_BUDGET_EXCEEDED')
    monkeypatch.setattr('app.cloud_update.pack_state',fail)
    report=run_slice(root,slice_index=1,producer='1',adapter_factory=factory)
    assert report['status']=='BLOCKED' and not report['published']
    assert pointer(root)==before


@pytest.mark.parametrize('calendar_status',['MARKET_NOT_CLOSED','NON_TRADING_DAY'])
def test_previous_closed_day_checkpoint_can_continue_overnight_without_relabelling(published,monkeypatch,calendar_status):
    root,result,universe,factory=slice_fixture(monkeypatch,published)
    saved=deepcopy(result);saved.update(status='STOPPED',complete=False)
    work=root/'seed'
    CheckpointStore(work/'run').save(saved,universe,['C15'])
    bundle=root/'seed.gz'
    pack_state(work,bundle,source_fingerprint=fingerprint(root),trade_date=DAY,producer='1')
    monkeypatch.setattr('app.cloud_update.target_trade_date',lambda *args:dict(status=calendar_status,target_trade_date=DAY))
    report=run_slice(root,slice_index=2,producer='1',bundle=bundle,adapter_factory=factory)
    assert report['status']=='PUBLISHED_LOCALLY' and report['target_trade_date']==DAY
    assert report['calendar_state']==calendar_status


def test_crossed_next_trade_date_does_not_resume_or_publish_old_checkpoint(published,monkeypatch):
    root,result,universe,factory=slice_fixture(monkeypatch,published)
    promote(root);before=pointer(root)
    work=root/'seed';CheckpointStore(work/'run').save(result,universe,['C15'])
    bundle=root/'seed.gz'
    pack_state(work,bundle,source_fingerprint=fingerprint(root),trade_date=DAY,producer='1')
    monkeypatch.setattr('app.cloud_update.target_trade_date',lambda *args:dict(status='READY',target_trade_date='2026-10-08'))
    report=run_slice(root,slice_index=2,producer='1',bundle=bundle,adapter_factory=factory)
    assert report['reason_code']=='CLOUD_SLICE_CROSSED_TRADE_DATE' and not report['published']
    assert pointer(root)==before


def test_no_new_scan_before_market_close(published,monkeypatch):
    root,_,_,factory=slice_fixture(monkeypatch,published)
    monkeypatch.setattr('app.cloud_update.target_trade_date',lambda *args:dict(status='MARKET_NOT_CLOSED',target_trade_date=DAY))
    monkeypatch.setattr(ScreeningService,'run',lambda *args,**kw:pytest.fail('should not start a scan'))
    report=run_slice(root,slice_index=1,producer='1',adapter_factory=factory)
    assert report['status']=='MARKET_NOT_CLOSED' and not report['published']


@pytest.mark.parametrize('seconds',[0,2399,14401])
def test_hosted_compute_budget_cannot_grow_unbounded(tmp_path,seconds):
    with pytest.raises(ValueError):run_slice(tmp_path,slice_index=1,producer='1',run_seconds=seconds)


def test_cloud_templates_are_dormant_serial_and_separately_gated():
    root=Path(__file__).resolve().parents[1]
    files=list((root/'deployment/github-hosted').glob('*.yml.example'))
    assert len(files)==3
    values={p.name:yaml.load(p.read_text(),Loader=yaml.BaseLoader) for p in files}
    flow=values['market-update.yml.example']
    assert flow['jobs']['second']['needs']=='first'
    assert flow['jobs']['third']['needs']=='second'
    assert flow['jobs']['fourth']['needs']=='third'
    assert flow['concurrency']['group']=='market-context-publication'
    worker=values['market-slice.yml.example']['jobs']['slice']
    assert int(worker['timeout-minutes'])<360
    assert worker['runs-on']=='ubuntu-24.04'
    assert 'PILOT_VERIFIED' in worker['if']
    # Main now contains the explicitly authorized manual probe, not a daily scan.
    hosted=list((root/'.github/workflows').glob('hosted-*.yml'))
    assert [p.name for p in hosted]==['hosted-provider-probe.yml']
    probe=yaml.load(hosted[0].read_text(),Loader=yaml.BaseLoader)
    assert set(probe['on'])=={'workflow_dispatch'}
    assert probe['permissions']=={'contents':'read'}


@pytest.mark.parametrize('fail',[False,True])
def test_probe_uses_existing_sdk_contract_and_stops_on_first_error(tmp_path,monkeypatch,fail):
    """Synthetic SDK responses only; never overwrite the real probe evidence."""
    from app.data.baostock_provider import BaoStockProvider
    from app.data.models import ProviderError
    from tools import cloud_provider_probe as probe
    class FixedTime:
        @staticmethod
        def now(tz):return datetime.fromisoformat('2026-09-30T10:00:00+00:00')
    class Offline(BaoStockProvider):
        def __init__(self,timeout):pass
        def close(self):pass
        def _call(self,method,**kw):
            if fail:raise ProviderError('synthetic unavailable')
            if method=='query_trade_dates':
                dates=pd.date_range(kw['start_date'],kw['end_date'])
                return pd.DataFrame({'calendar_date':dates.strftime('%Y-%m-%d'),'is_trading_day':(dates.weekday<5).astype(int)})
            if method=='query_stock_industry':
                return pd.DataFrame({'code':['sh.600519'],'industry':['TEST ONLY'],'industryClassification':['TEST ONLY']})
            assert method=='query_history_k_data_plus'
            values=dict(date='2026-09-30',code=kw['code'],open='10',high='11',low='9',close='10',
                        preclose='10',pctChg='0',volume='100',amount='1000',adjustflag=kw['adjustflag'],
                        turn='1',tradestatus='1',isST='0')
            return pd.DataFrame({k:[values[k]] for k in kw['fields'].split(',')})
    monkeypatch.setattr('app.screening.batch_provider.BatchBaoStockProvider',Offline)
    monkeypatch.setattr(probe,'ROOT',tmp_path)
    monkeypatch.setattr(probe,'datetime',FixedTime)
    assert probe.main()==(1 if fail else 0)
    report=json.loads((tmp_path/'outputs/free_cloud/provider_probe.json').read_text('utf-8'))
    assert report['actual_sdk_calls']==(1 if fail else 5)
    assert report['budget']['retries']==0
    assert report['status']==('FAILURE' if fail else 'PASS')
