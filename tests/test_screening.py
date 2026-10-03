"""Synthetic eligibility tests are offline; they are not live evidence."""
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from app.screening.policy import ScreeningPolicy
from app.screening.service import ScreeningService,SharedIndustryContext,RequestCache
from app.data.cache import CacheKey,DataCache
from app.cli import main
from app.api import create_app
import pandas as pd

DAY='2026-09-30'

def heat(score=70,status='VALID'):
    return dict(trade_date=DAY,overall_status=status,total_score=score)

def analysis(symbol='600519.SH',sector='C15',score=80,risk='LOW'):
    return dict(symbol=symbol,name='synthetic test',evaluation_date=DAY,final_quant_score=score,
                positive_score=score,risk_penalty=0,risk_level=risk,
                positive_coverage=.1,data_status=dict(status='PARTIAL',rows=120,is_mock=True),
                industry_context=dict(data_status='VALID',primary_industry=dict(symbol=symbol,sector_id=sector,as_of=DAY),
                                      sector_heat=heat(),returns=dict(data_status='VALID')),
                rules=[dict(rule_id=k,score=1) for k in ('B1','B2')])

@pytest.mark.parametrize('score,state',[(69.999,'NOT_MATCHED'),(70,'ELIGIBLE'),(70.001,'ELIGIBLE')])
def test_sector_edges(score,state):
    assert ScreeningPolicy.current().sector(heat(score),DAY)==(state,'VALID')

@pytest.mark.parametrize('status',['DATA_INCOMPLETE','DATA_ERROR','DATA_STALE','DATA_INCONSISTENT'])
def test_bad_sector_is_not_low_score(status):
    assert ScreeningPolicy.current().sector(heat(None,status),DAY)==('NOT_EVALUABLE',status)

@pytest.mark.parametrize('score,risk,state',[(79.999,'LOW','NOT_MATCHED'),(80,'LOW','MATCHED'),(80.001,'MEDIUM','MATCHED'),(90,'HIGH','NOT_MATCHED')])
def test_stock_active_edges_no_global_coverage_gate(score,risk,state):
    assert ScreeningPolicy.current().stock(analysis(score=score,risk=risk),DAY,'C15')[0]==state

@pytest.mark.parametrize('change,quality',[
    ('unavailable','DATA_ERROR'),('short','DATA_INCOMPLETE'),('wrong_industry','DATA_INCONSISTENT'),
    ('stale','DATA_STALE'),('score_none','DATA_INCOMPLETE'),('bad_returns','DATA_INCONSISTENT'),
    ('bad_b1','DATA_ERROR')])
def test_stock_data_gates(change,quality):
    d=analysis()
    if change=='unavailable':d['data_status']['status']='UNAVAILABLE'
    if change=='short':d['data_status']['rows']=119
    if change=='wrong_industry':d['industry_context']['primary_industry']['sector_id']='C25'
    if change=='stale':d['evaluation_date']='2026-09-29'
    if change=='score_none':d['final_quant_score']=None
    if change=='bad_returns':d['industry_context']['returns']['data_status']='DATA_INCONSISTENT'
    if change=='bad_b1':d['rules'][0].update(score=None,raw_values={'upstream_data_status':'DATA_ERROR'})
    state,status,_=ScreeningPolicy.current().stock(d,DAY,'C15')
    assert (state,status)==('NOT_EVALUABLE',quality)

def test_unknown_and_unimplemented_rules_follow_existing_score_engine():
    d=analysis();d['rules'][1]['score']=None
    d['rules'].append(dict(rule_id='E4',score=None,status='UNKNOWN',code_status='NOT_IMPLEMENTED'))
    assert ScreeningPolicy.current().stock(d,DAY,'C15')[0]=='MATCHED'

class Adapter:
    mode='synthetic-test-only'
    is_mock=True
    def __init__(self):self.sector_calls=[];self.stock_calls=[]
    def prepare(self,refresh=False):
        return DAY,{'C15':dict(name='fixture',symbols=['600519.SH','600000.SH','600519.SH']),
                    'H61':dict(name='small',symbols=['600258.SH']),
                    'C25':dict(name='failure',symbols=['600688.SH'])},[dict(symbol='430001.BJ',reason='OUT_OF_SCOPE_FOR_V1')]
    def sector(self,sid,symbol,day,refresh=False):
        self.sector_calls.append(sid)
        if sid=='C25':raise RuntimeError('provider failure fixture')
        return dict(data_status='VALID',primary_industry=dict(sector_id=sid),sector_heat=heat(None,'DATA_INCOMPLETE') if sid=='H61' else heat())
    def stock(self,symbol,day,refresh=False):
        self.stock_calls.append(symbol)
        if symbol=='600000.SH':
            from app.data.models import ProviderError
            raise ProviderError('stock failure fixture')
        return analysis(symbol)
    def metrics(self):return dict(provider_requests=0,cache_hits=0,retry_count=0)

def test_batch_failure_isolation_denominators_dedup_and_outputs(tmp_path):
    a=Adapter();r=ScreeningService(a).run(output_dir=tmp_path)
    assert r['stats']['stock_expected']==2 and r['stats']['stock_analyzed']==2
    assert r['stats']['provider_error']==1 and len(r['candidates'])==1
    assert len(a.stock_calls)==len(set(a.stock_calls))==2
    assert '430001.BJ' not in a.stock_calls
    assert r['status']=='PARTIAL' and r['sectors'][1]['sector_heat'] is None
    assert json.loads((tmp_path/'screening_details.json').read_text('utf-8'))['is_mock']
    assert (tmp_path/'stock_failures.csv').exists()

def test_all_eligible_sectors_no_top_five_cap():
    class Many(Adapter):
        def prepare(self,refresh=False):return DAY,{f'C{i:02}':dict(name='fixture',symbols=[f'6000{i:02}.SH']) for i in range(10,17)},[]
        def sector(self,sid,symbol,day,refresh=False):return dict(data_status='VALID',primary_industry=dict(sector_id=sid),sector_heat=heat())
        def stock(self,symbol,day,refresh=False):return analysis(symbol,sector='C'+symbol[4:6])
    r=ScreeningService(Many()).run()
    assert r['stats']['industry_candidate']==7 and r['stats']['stock_analyzed']==7

def test_shared_heat_once_and_stock_identity():
    class Builder:
        calls=0
        def build(self,symbol,day,refresh=False):
            self.calls+=1
            return dict(primary_industry=dict(symbol=symbol,sector_id='C15'),sector_heat=heat())
    b=Builder();s=SharedIndustryContext(b,{'600519.SH':'C15','600000.SH':'C15'})
    first=s.build('600519.SH',DAY);second=s.build('600000.SH',DAY)
    assert b.calls==1 and first['primary_industry']['symbol']=='600519.SH'
    assert second['primary_industry']['symbol']=='600000.SH'
    second['sector_heat']['total_score']=0
    assert s.build('600000.SH',DAY)['sector_heat']['total_score']==70

def test_request_cache_exact_benchmark_reuse_even_refresh(tmp_path):
    c=RequestCache(DataCache(tmp_path/'cache.sqlite'));k=CacheKey('baostock','000001.SH','2026-09-01',DAY,'NONE')
    assert c.get(k,force_refresh=True) is None
    c.put(k,pd.DataFrame({'date':pd.to_datetime([DAY]),'close':[100.]}))
    assert c.get(k,force_refresh=True).close.iloc[0]==100 and c.hits==1
    assert c.get(k,force_refresh=True).attrs['cache_hit'] is True
    assert c.get(CacheKey('baostock','000001.SH','2025-01-01',DAY,'NONE'),force_refresh=True) is None
    assert c.get(CacheKey('baostock','000001.SH','2026-09-15',DAY,'industry_context:benchmark'),force_refresh=True).close.iloc[0]==100
    assert c.get(CacheKey('baostock','000001.SH','2026-09-01 00:00:00',DAY+' 00:00:00','NONE'),force_refresh=True).close.iloc[0]==100

def test_unverified_membership_blocks_sector_without_shrinking_denominator():
    class Bad(Adapter):
        def prepare(self,refresh=False):
            return DAY,{'C15':dict(name='fixture',symbols=['600519.SH','600000.SH'],quality_blocker='DATA_ERROR')},[]
    a=Bad();r=ScreeningService(a).run()
    assert r['sectors'][0]['constituent_count']==2 and r['sectors'][0]['sector_heat'] is None
    assert not a.sector_calls and not a.stock_calls

def test_engineering_order_deterministic():
    a=Adapter();one=ScreeningService(a).run();two=ScreeningService(Adapter()).run()
    assert one['stocks']==two['stocks']
    assert [s['symbol'] for s in one['stocks']]==['600519.SH','600000.SH']
    assert one['display_order_scope']=='ENGINEERING_DISPLAY_ORDER'

def test_screen_cli_json_and_api(tmp_path,capsys):
    s=ScreeningService(Adapter())
    assert main(['screen','--json','--output-dir',str(tmp_path)],screening_service=s)==0
    assert json.loads(capsys.readouterr().out)['stats']['industry_total']==3
    client=TestClient(create_app(screening_service=s))
    d=client.get('/api/screen?limit_industries=1').json()
    assert d['stats']['industry_total']==1
    assert client.get('/api/screen?limit_industries=0').status_code==422

def test_real_archive_replay_without_network(monkeypatch):
    import socket
    from app.screening.replay import ArchivedScreeningAdapter
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('network forbidden')))
    from pathlib import Path
    a=ArchivedScreeningAdapter(archive_directory=Path(__file__).parent/'fixtures/screening_real',stage35_loader=lambda _: [])
    r=ScreeningService(a).run()
    assert r['mode']=='archived-real-subset-replay' and not r['is_mock']
    assert r['performance']['provider_requests']==0 and not r['candidates']
    assert len(a.analyses)==3

def test_batch_worker_retains_login_logout_for_every_request(monkeypatch):
    from types import SimpleNamespace
    import sys
    from app.screening.batch_provider import batch_worker
    events=[]
    class Client:
        def login(self):events.append('login');return SimpleNamespace(error_code='0')
        def logout(self):events.append('logout')
        def query(self,**kwargs):
            events.append(kwargs['code'])
            class Result:
                error_code='0';fields=['close'];done=False
                def next(self):
                    if self.done:return False
                    self.done=True;return True
                def get_row_data(self):return ['10']
            return Result()
    class Pipe:
        commands=iter([('query',{'code':'sh.600519'}),('query',{'code':'sh.600688'}),None])
        sent=[]
        def recv(self):return next(self.commands)
        def send(self,value):self.sent.append(value)
        def close(self):events.append('closed')
    monkeypatch.setitem(sys.modules,'baostock',Client())
    monkeypatch.setattr('app.screening.batch_provider.socket.setdefaulttimeout',lambda _:None)
    pipe=Pipe();batch_worker(pipe,45)
    assert events==['login','sh.600519','logout','login','sh.600688','logout','closed']
    assert len(pipe.sent)==2 and all(ok for ok,_ in pipe.sent)

def test_batch_failure_closes_worker_before_existing_retry(monkeypatch):
    from app.screening.batch_provider import BatchBaoStockProvider
    from app.data.models import ProviderError
    class Process:
        def is_alive(self):return True
    class Pipe:
        def send(self,value):pass
        def poll(self,timeout):return True
        def recv(self):return False,'10002007: 网络接收错误。'
    p=BatchBaoStockProvider();p._process=Process();p._pipe=Pipe();closed=[]
    monkeypatch.setattr(p,'close',lambda:closed.append(True))
    with pytest.raises(ProviderError,match='10002007'):
        p._call_once('query',code='sh.600519')
    assert closed==[True]

def test_screening_stock_service_uses_existing_full_score_engine(tmp_path):
    from app.data.base import MockProvider
    from app.data.provider_manager import ProviderManager
    from app.screening.live import ScreeningStockAnalysisService
    from app.services.stock_analysis_service import StockAnalysisService
    dates=pd.bdate_range(end=DAY,periods=180)
    frame=pd.DataFrame(dict(date=dates,open=10.,high=10.1,low=9.9,close=10.,volume=1000.,amount=10000.,turnover_rate=2.))
    provider=MockProvider([dict(canonical_symbol='600519.SH',name='synthetic test')],frame,frame,frame)
    manager=ProviderManager(provider,cache=DataCache(tmp_path/'stock.sqlite'))
    class Industry:
        def build(self,symbol,day,refresh=False):
            c=analysis(symbol)['industry_context']
            c['returns'].update(sector_return_5d=0.,trade_dates=[str(d.date()) for d in dates[-6:]],
                                window_start=str(dates[-6].date()),window_end=day,adjustment_type='qfq')
            c['sector_heat'].update(sector_id='C15',score_coverage=1.,max_score=100)
            return c
    baseline=StockAnalysisService(manager,industry_service=Industry()).analyze('600519',as_of=DAY)
    screened=ScreeningStockAnalysisService(manager,industry_service=Industry()).analyze('600519',as_of=DAY)
    assert baseline.final_quant_score==screened.final_quant_score
    assert baseline.positive_score==screened.positive_score and baseline.risk_penalty==screened.risk_penalty
    assert [{k:r[k] for k in ('rule_id','score','penalty','status')} for r in baseline.rules]==[
        {k:r[k] for k in ('rule_id','score','penalty','status')} for r in screened.rules]

def test_live_adapter_metadata_universe_and_unknown_member_denominator(tmp_path):
    from app.screening.live import LiveScreeningAdapter
    from app.data.baostock_provider import BaoStockProvider
    from app.data.models import ProviderError
    class Source(BaoStockProvider):
        def _call(self,method,**kwargs):
            assert method=='query_stock_industry'
            return pd.DataFrame([dict(code=c,industry='C15fixture') for c in
                                 ['sh.600519','sh.600688','sh.510050','sh.000001','bj.430001']])
        def query_trade_dates(self,*args):
            return pd.DataFrame(dict(calendar_date=pd.to_datetime([DAY]),is_trading_day=[1]))
        def query_stock_basic(self,code=None):
            if code:raise ProviderError('metadata fixture unavailable')
            return pd.DataFrame([dict(code=c,code_name='fixture',type=t,ipoDate='2000-01-01') for c,t in
                                 [('sh.600519','1'),('sh.510050','3'),('sh.000001','2'),('bj.430001','1')]])
        def fetch_benchmark(self,*args):
            return pd.DataFrame(dict(date=pd.to_datetime([DAY]),close=[100.]))
    a=LiveScreeningAdapter(Source(),DataCache(tmp_path/'cache.sqlite'))
    day,universe,exclusions=a.prepare()
    assert universe['C15']['symbols']==['600519.SH','600688.SH']
    assert universe['C15']['quality_blocker']=='DATA_ERROR'
    assert {r['reason'] for r in exclusions}=={'METADATA_UNAVAILABLE','NON_STOCK_ASSET_TYPE','OUT_OF_SCOPE_FOR_V1'}

def test_unavailable_core_degraded_zero_is_not_batch_score():
    class Unavailable(Adapter):
        def stock(self,symbol,day,refresh=False):
            d=analysis(symbol,score=0);d['data_status'].update(status='UNAVAILABLE',rows=0)
            return d
    r=ScreeningService(Unavailable()).run()
    assert all(s['QuantScore'] is None and s['observed_quant_score']==0
               and s['candidate_status']=='NOT_EVALUABLE' for s in r['stocks'])
