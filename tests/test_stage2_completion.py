"""Stage2 frozen-semantics boundary tests, synthetic/offline only."""
import numpy as np
import pytest
from conftest import bars, evaluate
from test_stage2_service import service
from app.api import create_app
from fastapi.testclient import TestClient
from app.rules.base import Context
from app.data.cache import DataCache
from app.rules.risks.should_rise import ScoreSnapshot


# V1.3 global frozen tier convention is [a,b); original V1.1 tables are inherited.
@pytest.mark.parametrize('ratio,score',[(.6,3),(.600001,3),(.8,1),(.800001,1),(1,0),(1.000001,0)])
def test_d2_tiers(engine,ratio,score):
    d=bars([10]*149+[11,10.8]); d.loc[149,'volume']=200; d.loc[150,'volume']=200*ratio
    assert evaluate(engine,'D2',d).score==score


def probe(turn=4.9):
    d=bars([10]*149+[10.3]); d.loc[149,['high_raw','high_adj','turnover_rate']]=[10.8,10.8,turn]
    return d


@pytest.mark.parametrize('turn,score',[(5,4),(5.00001,4),(10,0),(10.00001,0)])
def test_f1x_tiers(engine,turn,score):
    assert evaluate(engine,'F1-X',probe(turn)).score==score


def test_f1x_prior_pass_suppresses(engine):
    d=probe(); e=probe().iloc[-1:].copy(); e['date']=d.date.iloc[-1]+__import__('pandas').Timedelta(days=1)
    e['high_raw']=11.1; e['high_adj']=11.1
    d=__import__('pandas').concat([d,e],ignore_index=True)
    assert evaluate(engine,'F1-X',d).score==0


def test_f2_event_and_no_independent_score(engine):
    assert evaluate(engine,'F2',probe()).score==5
    assert evaluate(engine,'F2',bars([10]*150)).score==0


@pytest.mark.parametrize('turn,volume,penalty',[(20,100,15),(19.999,200,15),(19.999,199.99,8)])
def test_r3_large_trade_or_boundary(engine,turn,volume,penalty):
    d=bars(np.linspace(10,30,150)); d.loc[149,['high_raw','close_raw','limit_up_price','turnover_rate','volume']]=[33,32.34,33,turn,volume]
    d.loc[146:147,'limit_up_price']=d.loc[146:147,'close_raw']
    assert evaluate(engine,'R3',d).penalty==penalty


@pytest.mark.parametrize('close,penalty,status',[(20,10,'PASS'),(20.4,5,'CANDIDATE')])
def test_r5_midpoint(engine,close,penalty,status):
    d=bars(np.linspace(10,20,150))
    for i,o,c,h,l in [(147,20,20.6,20.7,19.9),(148,20.806,20.9,21,20.7),(149,21.1,close,21.2,19.9)]:
        d.loc[i,['open_adj','close_adj','high_adj','low_adj']]=[o,c,h,l]
    r=evaluate(engine,'R5',d)
    assert (r.penalty,r.status)==(penalty,status)


@pytest.mark.parametrize('rid',['D2','F1-X','F2','R3','R5'])
def test_new_rules_no_future_leak(engine,rid):
    d=probe(); day=str(d.date.iloc[-2].date())
    before=engine.evaluate(rid,Context(d,as_of=day)).to_dict()
    d.loc[149,['high_adj','high_raw','close_adj','close_raw']]=999
    assert engine.evaluate(rid,Context(d,as_of=day)).to_dict()==before


def test_public_schema(service):
    response=TestClient(create_app(service)).get('/api/analyze/000001').json()
    keys={'as_of','benchmark','data_status','market','price','indicators','positive_score','risk_penalty','final_quant_score','risk_level','positive_coverage','risk_coverage','score_status','top_positive_reasons','top_risk_reasons','rules'}
    assert keys<=response.keys()
    assert response['final_quant_score']==response['score']['final_score']
    assert response['benchmark']['symbol']=='000001.SH'
    assert all(r['spec_version']=='1.4' and 'data_provenance' in r for r in response['rules'])
    assert response['data_status']['raw_rows']==150
    assert response['indicators']['M60'] is not None


def test_snapshot_immutable(tmp_path):
    cache=DataCache(tmp_path/'frozen.sqlite')
    a=ScoreSnapshot('2024-01-02',10,80,'LOW','1.4','first')
    b=ScoreSnapshot('2024-01-02',10,90,'LOW','1.4','changed')
    cache.freeze_score('000001.SZ',a); cache.freeze_score('000001.SZ',b)
    assert cache.score_snapshots('000001.SZ')==[a]


def test_historical_forward_separate_from_score(service):
    data=service.provider_manager.fetch('000001')
    day=str(data.bars.date.iloc[-4].date())
    price=float(data.bars.close_adj.iloc[-4])
    service.provider_manager.cache.freeze_score('000001.SZ',ScoreSnapshot(day,price,80,'LOW','1.4','preexisting'))
    result=service.analyze('000001',as_of=day)
    assert result.as_of==day
    assert result.r7_forward_confirmation['raw_values']['signal_date']==day
    assert len(result.r7_forward_confirmation['raw_values']['forward_highs'])==3
    r7=next(r for r in result.rules if r['rule_id']=='R7')
    assert r7['reason_code']=='AWAITING_FORWARD_CONFIRMATION'
    assert service.provider_manager.cache.score_snapshots('000001.SZ')[0].quant_score==80


def test_adapter_missing_optional_columns():
    import pandas as pd
    from app.data.akshare_provider import AKShareProvider
    class Client:
        def stock_zh_a_hist(self,**kwargs):
            return pd.DataFrame({'日期':['2024-01-02'],'开盘':[10.],'最高':[11.],'最低':[9.],'收盘':[10.]})
    d=AKShareProvider(Client()).fetch_stock_daily('000001.SZ','2024-01-02','2024-01-02')
    assert d.turnover_rate.isna().all() and d.volume.isna().all()


def test_missing_limit_reason(engine):
    d=probe(); d.loc[149,'limit_up_price']=np.nan
    assert evaluate(engine,'F1-X',d).reason_code=='LIMIT_PRICE_UNRELIABLE'
