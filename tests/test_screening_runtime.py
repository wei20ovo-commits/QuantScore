"""Offline operational tests; synthetic frames are never live evidence."""
from copy import deepcopy
import json
import sqlite3
import time
import pandas as pd
import pytest
from app.data.cache import CacheKey,DataCache
from app.screening.history_cache import HistoryCache
from app.screening.service import RequestCache,ScreeningService
from app.screening.runtime import RuntimeLimits,RunControl,RuntimeDeadline
from app.screening.score_cache import ScoreMemo
from app.rules.base import Context
from app.engine.score_engine import ScoreEngine
from tests.test_screening import Adapter,DAY,analysis


def bars(start='2026-09-01',end=DAY,price=10):
    dates=pd.bdate_range(start,end).astype('datetime64[ns]')
    return pd.DataFrame(dict(date=dates,open=float(price),high=float(price)+1,
        low=float(price)-1,close=float(price),volume=1000.,amount=10000.,symbol='600519.SH'))

def source(calls,price=10):
    def fetch(a,b):
        calls.append((pd.Timestamp(a),pd.Timestamp(b)))
        return bars(a,b,price)
    return fetch


def test_persistent_history_reuse_and_symbol_metadata(tmp_path):
    calls=[];path=tmp_path/'history.sqlite3'
    c=HistoryCache(path)
    first=c.fetch('baostock','600519.SH','raw','2026-09-01',DAY,source(calls))
    second=HistoryCache(path).fetch('baostock','600519.SH','raw','2026-09-15',DAY,source(calls))
    assert len(calls)==1 and second.attrs['cache_hit']
    assert second.attrs['data_status']=='VALID' and second.attrs['symbol']=='600519.SH'
    pd.testing.assert_frame_equal(first.loc[first.date.ge('2026-09-15')].reset_index(drop=True),second)


@pytest.mark.parametrize('mode',['raw','qfq'])
def test_incremental_only_fetches_overlap_and_new_dates(tmp_path,mode):
    calls=[];p=tmp_path/'h.sqlite3'
    c=HistoryCache(p)
    c.fetch('baostock','600519.SH',mode,'2020-01-01','2026-09-29',source(calls))
    c=HistoryCache(p)
    updated=c.fetch('baostock','600519.SH',mode,'2020-01-01',DAY,source(calls))
    assert calls[-1][0]>pd.Timestamp('2026-09-01') and len(calls)==2
    assert updated.date.max()==pd.Timestamp(DAY) and not updated.date.duplicated().any()
    pd.testing.assert_frame_equal(updated,bars('2020-01-01',DAY))


def test_qfq_anchor_change_forces_full_refresh(tmp_path):
    c=HistoryCache(tmp_path/'h.sqlite3');calls=[]
    c.fetch('baostock','600519.SH','qfq','2020-01-01','2026-09-29',source(calls))
    updated=c.fetch('baostock','600519.SH','qfq','2020-01-01',DAY,source(calls,price=9))
    assert c.metrics['anchor_refreshes']==1 and len(calls)==3
    assert calls[-1][0]==pd.Timestamp('2020-01-01')
    assert updated.close.eq(9).all()


def test_failed_increment_does_not_advance_valid_coverage(tmp_path):
    path=tmp_path/'h.sqlite3';c=HistoryCache(path);calls=[]
    c.fetch('baostock','600519.SH','raw','2026-09-01','2026-09-29',source(calls))
    def failed(a,b):raise RuntimeError('fixture provider error')
    with pytest.raises(RuntimeError):c.fetch('baostock','600519.SH','raw','2026-09-01',DAY,failed)
    with sqlite3.connect(path) as db:meta=json.loads(db.execute('SELECT metadata FROM history_v1').fetchone()[0])
    assert meta['end_date']=='2026-09-29'


def test_invalid_ohlc_never_stored(tmp_path):
    c=HistoryCache(tmp_path/'h.sqlite3')
    def bad(a,b):return bars(a,b).assign(close=0.)
    with pytest.raises(ValueError):c.fetch('baostock','600519.SH','raw','2026-09-01',DAY,bad)
    with sqlite3.connect(c.path) as db:assert db.execute('SELECT count(*) FROM history_v1').fetchone()[0]==0


def test_force_refresh_bypasses_disk_but_reuses_run_memory(tmp_path):
    path=tmp_path/'h.sqlite3';calls=[]
    HistoryCache(path).fetch('baostock','600519.SH','raw','2026-09-01',DAY,source(calls))
    c=HistoryCache(path)
    for _ in range(2):c.fetch('baostock','600519.SH','raw','2026-09-01',DAY,source(calls),refresh=True)
    assert len(calls)==2


def test_expired_same_date_revalidates_not_full_history(tmp_path):
    path=tmp_path/'h.sqlite3';calls=[]
    HistoryCache(path,clock=lambda:0).fetch('baostock','600519.SH','raw','2020-01-01',DAY,source(calls))
    HistoryCache(path,clock=lambda:4000).fetch('baostock','600519.SH','raw','2020-01-01',DAY,source(calls))
    assert len(calls)==2 and calls[-1][0]>pd.Timestamp('2026-09-01')


def test_superset_aliases_and_calendar_union(tmp_path):
    c=RequestCache(DataCache(tmp_path/'c.sqlite3'))
    c.put(CacheKey('baostock','600519.SH','2026-09-01',DAY,'raw'),bars())
    assert c.get(CacheKey('baostock','600519.SH','2026-09-15',DAY,'industry_context:raw')) is not None
    assert c.get(CacheKey('baostock','600519.SH','2026-09-15',DAY,'qfq')) is None
    for a,b in [('2026-09-01','2026-09-15'),('2026-09-16',DAY)]:
        cal=pd.DataFrame(dict(calendar_date=pd.date_range(a,b),is_trading_day=1))
        c.put(CacheKey('baostock','calendar',a,b,'industry_context:calendar'),cal)
    assert len(c.get(CacheKey('baostock','calendar','2026-09-03','2026-09-22','industry_context:calendar')))==20
    assert c.get(CacheKey('baostock','calendar','2026-08-31',DAY,'industry_context:calendar')) is None


class Interrupt(Adapter):
    def stock(self,symbol,day,refresh=False):
        if symbol=='600519.SH':raise KeyboardInterrupt('simulated interruption')
        return super().stock(symbol,day,refresh=refresh)


def test_checkpoint_resume_skips_completed_objects_and_preserves_results(tmp_path):
    with pytest.raises(KeyboardInterrupt):ScreeningService(Interrupt()).run(output_dir=tmp_path)
    a=Adapter();resumed=ScreeningService(a).run(output_dir=tmp_path,resume=True)
    baseline=ScreeningService(Adapter()).run()
    assert not a.sector_calls and a.stock_calls==['600519.SH']
    assert resumed['stats']==baseline['stats']
    for r in resumed['stocks']:r.pop('analysis_file',None)
    assert resumed['stocks']==baseline['stocks']
    assert resumed['complete']


@pytest.mark.parametrize('field,value',[('trade_date','2026-09-29'),('spec_version','1.3'),('data_contract_version','1.3'),('assumption_version','v1.2')])
def test_wrong_checkpoint_versions_or_date_rejected(tmp_path,field,value):
    ScreeningService(Adapter()).run(output_dir=tmp_path)
    p=tmp_path/'checkpoint.json';d=json.loads(p.read_text('utf-8'));d['result'][field]=value;p.write_text(json.dumps(d),encoding='utf-8')
    with pytest.raises(ValueError,match='CHECKPOINT_INCOMPATIBLE'):ScreeningService(Adapter()).run(output_dir=tmp_path,resume=True)


def test_checkpoint_corruption_rejected(tmp_path):
    ScreeningService(Adapter()).run(output_dir=tmp_path)
    p=tmp_path/'checkpoint_objects/sectors/C15.json';p.write_text('{}')
    with pytest.raises(ValueError,match='digest'):ScreeningService(Adapter()).run(output_dir=tmp_path,resume=True)


def test_object_timeout_marks_error_continues_batch(tmp_path):
    class Slow(Adapter):
        def sector(self,sid,symbol,day,refresh=False):
            if sid=='C15':time.sleep(.02)
            return super().sector(sid,symbol,day,refresh=refresh)
    a=Slow();r=ScreeningService(a).run(runtime_limits=RuntimeLimits(sector_seconds=.01),output_dir=tmp_path)
    assert len(r['sectors'])==3
    row=next(s for s in r['sectors'] if s['sector_id']=='C15')
    assert row['data_status']=='DATA_ERROR' and row['candidate_status']=='NOT_EVALUABLE' and row['sector_heat'] is None


def test_whole_deadline_checkpoint_resumes(tmp_path):
    class Slow(Adapter):
        def sector(self,*a,**kw):time.sleep(.02);return super().sector(*a,**kw)
    first=ScreeningService(Slow()).run(runtime_limits=RuntimeLimits(run_seconds=.01),output_dir=tmp_path)
    assert first['status']=='STOPPED' and not first['complete']
    resumed=ScreeningService(Adapter()).run(output_dir=tmp_path,resume=True)
    assert resumed['complete'] and len(resumed['sectors'])==3


def test_control_rejects_expired_deadline_before_retry():
    clock=[0.];c=RunControl(RuntimeLimits(),clock=lambda:clock[0]);clock[0]=999999
    with pytest.raises(RuntimeDeadline):c.check()


def test_score_memo_input_fingerprint_invalidates_business_changes(tmp_path):
    memo=ScoreMemo(tmp_path/'m.sqlite3');e=ScoreEngine()
    context=Context(bars(),metadata=dict(industry_context={'sector_heat':{'total_score':70}},score_snapshots=[]))
    key=memo.key(context,e)
    same=deepcopy(context);same.metadata['data_provenance']=[dict(cache_hit=True,last_updated=123)]
    assert memo.key(same,e)==key
    for change in ('bar','heat','snapshot','weight'):
        changed=deepcopy(context);engine=ScoreEngine()
        if change=='bar':changed.bars.loc[0,'close']=11
        if change=='heat':changed.metadata['industry_context']['sector_heat']['total_score']=69
        if change=='snapshot':changed.metadata['score_snapshots']=[dict(signal_date=DAY,quant_score=80)]
        if change=='weight':engine.rule_engine.parameters['SYSTEM']['positive_cap']=99
        assert memo.key(changed,engine)!=key


def test_score_memo_exact_result_and_provenance_refresh(tmp_path):
    e=ScoreEngine();calls=[];expected={'rules':[{'rule_id':'X','score':3,'data_provenance':[]}],'final_score':3}
    def evaluate(c):calls.append(True);return deepcopy(expected)
    e.evaluate=evaluate;m=ScoreMemo(tmp_path/'m.sqlite3');m.bind(e)
    c=Context(bars());one=e.evaluate(c);c.metadata['data_provenance']=[{'provider':'real-test-identity'}];two=e.evaluate(c)
    assert len(calls)==1 and m.hits==1
    assert one['final_score']==two['final_score']
    assert two['rules'][0]['data_provenance']==c.metadata['data_provenance']


def test_partial_provider_message_cannot_hold_parent_past_timeout(tmp_path,monkeypatch):
    # Unit isolation of the timeout branch; this is not live network evidence.
    from app.screening.batch_provider import BatchBaoStockProvider
    from app.data.models import ProviderError
    class Pipe:
        def send(self,v):pass
        def poll(self,t):time.sleep(min(t,.01));return False
        def close(self):pass
    class Process:
        def is_alive(self):return True
        def join(self,t):assert t<=2
        def terminate(self):pass
        def kill(self):pass
    p=BatchBaoStockProvider(timeout=.01);p._pipe=Pipe();p._process=Process()
    start=time.monotonic()
    with pytest.raises(ProviderError,match='deadline'):p._call_once('offline')
    assert time.monotonic()-start<.5 and p.timeout_count==1 and p._process is None


def stalled_process(pipe):
    pipe.recv()
    time.sleep(30)


def test_real_worker_process_is_terminated_on_deadline():
    import multiprocessing as mp
    from app.screening.batch_provider import BatchBaoStockProvider
    from app.data.models import ProviderError
    context=mp.get_context('spawn');parent,child=context.Pipe()
    process=context.Process(target=stalled_process,args=(child,),daemon=True)
    process.start();child.close()
    p=BatchBaoStockProvider(timeout=.05);p._process=process;p._pipe=parent
    start=time.monotonic()
    with pytest.raises(ProviderError,match='deadline'):p._call_once('stall')
    assert time.monotonic()-start<4 and not process.is_alive()


def test_stock_timeout_does_not_cancel_next_stock(tmp_path):
    class Slow(Adapter):
        def stock(self,symbol,day,refresh=False):
            if symbol=='600000.SH':time.sleep(.02);return analysis(symbol)
            return super().stock(symbol,day,refresh=refresh)
    result=ScreeningService(Slow()).run(output_dir=tmp_path,runtime_limits=RuntimeLimits(stock_seconds=.01))
    rows={r['symbol']:r for r in result['stocks']}
    assert rows['600000.SH']['candidate_status']=='NOT_EVALUABLE' and rows['600000.SH']['QuantScore'] is None
    assert rows['600519.SH']['candidate_status']=='MATCHED'


def test_resume_rejects_changed_universe_without_shrinking_scope(tmp_path):
    ScreeningService(Adapter()).run(output_dir=tmp_path)
    class Changed(Adapter):
        def prepare(self,refresh=False):
            day,universe,exclusions=super().prepare(refresh=refresh)
            universe['C15']['symbols'].append('600001.SH')
            return day,universe,exclusions
    with pytest.raises(ValueError,match='CHECKPOINT_INCOMPATIBLE'):
        ScreeningService(Changed()).run(output_dir=tmp_path,resume=True)


def test_cache_parallel_get_put_preserves_consistent_index(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    c=RequestCache(DataCache(tmp_path/'c.sqlite3'))
    def operation(i):
        symbol=f'{600000+i:06}.SH';frame=bars().assign(symbol=symbol)
        c.put(CacheKey('baostock',symbol,'2026-09-01',DAY,'raw'),frame)
        for _ in range(3):
            value=c.get(CacheKey('baostock',symbol,'2026-09-15',DAY,'industry_context:raw'))
            assert value.symbol.eq(symbol).all()
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(operation,range(32)))
    assert c.hits==96 and len(c.range_index)==32


def test_bounded_score_worker_preserves_full_engine_results():
    from app.screening.runtime import bounded_score
    from app.features.technical import build_features
    raw=bars('2026-01-01',DAY)
    # A monotonic price path checks identical engine execution without turning
    # every flat candle into a combinatorial local-peak stress workload.
    price=pd.Series([10+i*.01 for i in range(len(raw))])
    raw['open']=raw['close']=price
    raw['high']=price+.05
    raw['low']=price-.05
    for suffix in ('raw','adj'):
        for field in ('open','high','low','close'):raw[field+'_'+suffix]=raw[field]
    raw=build_features(raw)
    context=Context(raw,as_of=DAY)
    engine=ScoreEngine();expected=engine.evaluate(context)
    actual=bounded_score(context,engine,RunControl(RuntimeLimits(run_seconds=60)))
    # Tuple/list differences are JSON presentation only.
    assert json.dumps(actual,sort_keys=True)==json.dumps(expected,sort_keys=True)


def test_bounded_score_expired_deadline_does_not_cache_partial_result(tmp_path):
    memo=ScoreMemo(tmp_path/'m.sqlite3',control=RunControl(RuntimeLimits(run_seconds=.01)))
    engine=ScoreEngine();memo.bind(engine);time.sleep(.02)
    with pytest.raises(RuntimeDeadline):engine.evaluate(Context(bars()))
    with sqlite3.connect(memo.path) as db:
        assert db.execute('SELECT count(*) FROM score_memo_v1').fetchone()[0]==0


def test_request_limit_is_separate_from_sector_and_run_limits(monkeypatch):
    from app.screening.batch_provider import BatchBaoStockProvider
    from app.data.models import ProviderError
    polled=[]
    class Pipe:
        def send(self,value):pass
        def poll(self,seconds):polled.append(seconds);return False
    class Process:
        def is_alive(self):return True
    provider=BatchBaoStockProvider(timeout=150)
    provider.control=RunControl(RuntimeLimits(request_seconds=.025))
    provider._pipe=Pipe();provider._process=Process()
    monkeypatch.setattr(provider,'close',lambda:None)
    with pytest.raises(ProviderError):provider._call_once('offline')
    assert polled==[.025]


def test_reused_adapter_refresh_starts_new_memo_lifetime(tmp_path):
    from app.screening.live import LiveScreeningAdapter
    from app.data.baostock_provider import BaoStockProvider
    class Source(BaoStockProvider):
        def __init__(self):super().__init__();self.calls=0
        def fetch_stock_daily(self,symbol,a,b,adjustment='raw'):
            self.calls+=1;return bars(a,b)
    provider=Source();history=HistoryCache(tmp_path/'h.sqlite3')
    adapter=LiveScreeningAdapter(provider,DataCache(tmp_path/'c.sqlite3'),history_cache=history)
    for _ in range(2):
        adapter.begin_run()
        history.bind(provider,refresh=True)
        provider.fetch_stock_daily('600519.SH','2026-09-01',DAY)
        provider.fetch_stock_daily('600519.SH','2026-09-01',DAY)
    assert provider.calls==2
