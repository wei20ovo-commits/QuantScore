"""Synthetic boundary cases plus offline real archive fixtures. No live test dependency."""
from copy import deepcopy
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app.rules.base import Context
from app.engine.rule_engine import RuleEngine,EVALUATORS
from app.engine.score_engine import ScoreEngine
from app.data.base import MockProvider
from app.data.provider_manager import ProviderManager
from app.data.cache import DataCache
from app.services.stock_analysis_service import StockAnalysisService
from app.api import create_app
from app.cli import main

DAYS=['2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-28']
DAY=DAYS[-1]

def industry(heat=80,sector_return=0):
    return dict(data_status='VALID',primary_industry=dict(symbol='600519.SH',sector_id='C15',name='fixture industry',provider='fixture',as_of=DAY,provenance={'provider':'fixture'}),
        sector_heat=dict(sector_id='C15',trade_date=DAY,total_score=heat,max_score=100,score_coverage=1,overall_status='VALID'),
        returns=dict(sector_return_5d=sector_return,window_start=DAYS[0],window_end=DAY,trade_dates=DAYS.copy(),adjustment_type='qfq',data_status='VALID'),provenance={'provider':'fixture'})

def context(heat=80,relative=0):
    bars=pd.DataFrame({'date':pd.to_datetime(DAYS),'close_adj':[100]*5+[100*(1+relative)]})
    return Context(bars,metadata={'industry_context':industry(heat),'symbol':'600519.SH','adjustment_type':'qfq'})

@pytest.mark.parametrize('heat,score',[(0,0),(49.999,0),(50,2),(50.001,2),(59.999,2),(60,4),(60.001,4),(69.999,4),(70,6),(70.001,6),(74.999,6),(75,7),(75.001,7),(84.999,7),(85,8),(85.001,8),(100,8)])
def test_b1_all_bands_and_edges(heat,score):
    r=RuleEngine().evaluate('B1',context(heat))
    assert r.score==score and r.code_status=='IMPLEMENTED'
    assert r.to_dict()['sector_heat_score']==heat and r.to_dict()['threshold_band']

@pytest.mark.parametrize('relative,score',[(-.1,0),(-.000001,0),(0,1),(.000001,1),(.009999,1),(.01,2),(.010001,2),(.039999,2),(.04,3),(.040001,3),(.079999,3),(.08,4),(.080001,4),(.2,4)])
def test_b2_all_bands_and_edges(relative,score):
    r=RuleEngine().evaluate('B2',context(relative=relative))
    assert r.score==score and r.raw_values['relative_return_5d']==pytest.approx(relative)
    assert r.raw_values['stock_window_start']==r.raw_values['window_start']

@pytest.mark.parametrize('status',['DATA_INCOMPLETE','DATA_ERROR','DATA_STALE','DATA_INCONSISTENT'])
def test_bad_heat_is_not_business_zero(status):
    c=context();c.metadata['industry_context']['sector_heat'].update(overall_status=status,total_score=None)
    r=RuleEngine().evaluate('B1',c)
    assert r.score is None and r.status=='UNKNOWN' and r.raw_values['data_status']==status
    assert r.raw_values['upstream_data_status']==status and r.raw_values['sector_heat_status']==status
    # B2 does not require the small industry's unavailable Heat, only complete returns.
    assert RuleEngine().evaluate('B2',c).score==1

@pytest.mark.parametrize('rid',['B1','B2'])
def test_missing_primary_and_bad_context(rid):
    c=context();c.metadata['industry_context']['primary_industry']={}
    assert RuleEngine().evaluate(rid,c).reason_code=='NO_PRIMARY_INDUSTRY'
    for status in ['DATA_ERROR','DATA_STALE','DATA_INCONSISTENT']:
        c=context();c.metadata['industry_context']['data_status']=status
        r=RuleEngine().evaluate(rid,c);assert r.score is None and r.raw_values['data_status']==status

@pytest.mark.parametrize('field,value',[('window_start','2026-09-17'),('window_end','2026-09-24'),('sector_return_5d',None),('sector_return_5d',float('nan')),('adjustment_type','raw'),('data_status','DATA_STALE'),('data_status','DATA_INCONSISTENT')])
def test_b2_bad_sector_inputs(field,value):
    c=context();c.metadata['industry_context']['returns'][field]=value
    assert RuleEngine().evaluate('B2',c).score is None

def test_missing_stock_and_holiday_misalignment():
    c=context();c.bars.loc[5,'close_adj']=float('nan')
    assert RuleEngine().evaluate('B2',c).score is None
    c=context();c.bars.loc[1,'date']=pd.Timestamp('2026-09-19')
    assert RuleEngine().evaluate('B2',c).reason_code=='TRADE_WINDOW_MISMATCH'

def test_b1_stale_wrong_industry_and_invalid_heat():
    for change in [{'trade_date':'2026-09-24'},{'sector_id':'C25'},{'total_score':float('nan')},{'score_coverage':.79}]:
        c=context();c.metadata['industry_context']['sector_heat'].update(change)
        assert RuleEngine().evaluate('B1',c).score is None

def test_registry_dedup_cap_and_coverage_unchanged():
    e=RuleEngine();assert {'B1','B2'}<=EVALUATORS.keys()
    a=e.evaluate('B1',context(100));b=e.evaluate('B2',context(relative=.1));s=ScoreEngine(e)
    one=s.aggregate([a,b]);two=s.aggregate([a,b,a,b])
    assert one==two and one['category_scores']['B']==12 and len(one['rules'])==2
    assert one['positive_coverage']==.12

class FixtureIndustry:
    def __init__(self):self.calls=[]
    def build(self,symbol,day,refresh=False):
        self.calls.append((symbol,day));return industry()

@pytest.fixture
def service(tmp_path):
    frame=pd.DataFrame(dict(date=pd.to_datetime(DAYS),open=100.,high=101.,low=99.,close=100.,volume=1000.,amount=100000.,turnover_rate=2.))
    provider=MockProvider([{'canonical_symbol':'600519.SH','name':'fixture stock'}],frame,frame,frame)
    manager=ProviderManager(provider,cache=DataCache(tmp_path/'stock.sqlite'))
    return StockAnalysisService(manager,industry_service=FixtureIndustry())

def test_service_context_built_once_both_rules_and_score(service):
    r=service.analyze('600519')
    assert len(service.industry_service.calls)==1
    rules={r['rule_id']:r for r in r.rules}
    assert rules['B1']['score']==7 and rules['B2']['score']==1
    assert r.score.category_scores['B']==8
    assert r.industry_context['primary_industry']['sector_id']=='C15'

def test_cli_json_and_api_preserve_fields(service,capsys):
    assert main(['analyze','600519','--json'],service=service)==0
    cli=json.loads(capsys.readouterr().out)
    response=TestClient(create_app(service)).get('/api/analyze/600519')
    assert response.status_code==200;api=response.json()
    for data in [cli,api]:
        assert {'score','rules','data_status','price','indicators','industry_context'}<=data.keys()
        assert next(r for r in data['rules'] if r['rule_id']=='B1')['score']==7

def test_provider_failure_does_not_break_stock_service(service):
    class Broken:
        def build(self,*a,**k):raise RuntimeError('fixture provider unavailable')
    service.industry_service=Broken();r=service.analyze('600519')
    assert r.industry_context['data_status']=='DATA_ERROR'
    assert all(x['score'] is None for x in r.rules if x['rule_id'] in ('B1','B2'))

def test_deterministic_rule_replay():
    e=RuleEngine();c=context(relative=.02);before=deepcopy(c.metadata)
    assert e.evaluate('B2',c).to_dict()==e.evaluate('B2',c).to_dict()
    assert c.metadata==before


def test_industry_adapter_accepts_equal_dates_with_different_storage_units():
    from app.sector.industry_context import context_from_frames
    days=pd.bdate_range('2026-08-03',periods=35)
    symbol='600519.SH';day=str(days[-1].date())
    raw=pd.DataFrame(dict(date=days,symbol=symbol,close=100.,high=101.,preclose=100.,isST=0,amount=100000.))
    adj=raw.copy();raw['date']=raw.date.astype('datetime64[ms]')
    adj['date']=adj.date.astype('datetime64[ns]')
    basic=pd.DataFrame([dict(code='sh.600519',ipoDate=str(days[0].date()))])
    cal=pd.DataFrame(dict(calendar_date=days,is_trading_day=1))
    benchmark=pd.DataFrame(dict(date=days,close=100.,symbol='000001.SH'))
    data=context_from_frames(symbol,'C15fixture',day,{symbol:raw},{symbol:adj},basic,cal,benchmark,{'provider':'fixture'})
    assert data['returns']['data_status']=='VALID'
    assert data['sector_heat']['overall_status']=='DATA_INCOMPLETE'
    json.dumps(data,allow_nan=False)


def test_nonfinite_industry_evidence_serializes_as_null():
    from app.sector.industry_context import json_values
    assert json_values({'raw':[float('nan'),float('inf'),0.]})=={'raw':[None,None,0.]}
