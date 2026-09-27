import numpy as np
import pytest
from app.rules.base import Context, indicators
from conftest import bars,evaluate


@pytest.mark.parametrize('window',[5,20,30,60])
def test_moving_average_exact(engine,window):
    d=bars(np.arange(1,101)); x=indicators(d,engine.parameters)
    assert x[f'M{window}'].iloc[-1]==np.mean(np.arange(101-window,101))
    assert x[f'M{window}'].iloc[window-2]!=x[f'M{window}'].iloc[window-2]


def test_volume_ratio_excludes_current(engine):
    d=bars([10]*21,[100]*20+[300]); x=indicators(d,engine.parameters)
    assert x.volume_ratio_20.iloc[-1]==3
    assert x.VMA20.iloc[-1]==110


def test_c1_full(engine):
    r=evaluate(engine,'C1',bars(np.linspace(10,20,80)))
    assert (r.status,r.score)==('PASS',5)
    assert len(r.raw_values['M60'])==5


@pytest.mark.parametrize('days,expected',[ (2,0),(3,2),(4,4),(5,5)])
def test_c1_days(engine,days,expected):
    d=bars([10]*65+[9]*(5-days)+[11]*days)
    assert evaluate(engine,'C1',d).score==expected


def test_c1_tolerance(engine):
    d=bars([10]*65+[9.975]*5)
    assert evaluate(engine,'C1',d).score==5


def test_c2_positive_and_ambiguous_zero(engine):
    assert evaluate(engine,'C2',bars(np.linspace(10,20,80))).score==5
    r=evaluate(engine,'C2',bars([10]*80))
    assert r.status=='PARTIAL' and r.score==2  # V1.2: x=0 belongs to [0, 0.5%)


def test_c3_full_and_fail(engine):
    assert evaluate(engine,'C3',bars(np.linspace(10,20,80))).score==4
    assert evaluate(engine,'C3',bars(np.linspace(20,10,80))).status=='FAIL'


def test_c4_confirmed(engine):
    r=evaluate(engine,'C4',bars([10]*75+[10.3,10.4,10.5]))
    assert r.score==4 and r.raw_values['events'][0]['confirmed']


def test_c4_candidate(engine):
    r=evaluate(engine,'C4',bars([10]*75+[10.3]))
    assert r.score==2


def test_c4_failed_confirmation_is_unknown(engine):
    r=evaluate(engine,'C4',bars([10]*75+[10.3,9.8,9.7,9.6]))
    assert r.status=='FAIL' and r.score==0  # V1.2: completed failed confirmation


def test_c4_reclaim_proxy(engine):
    d=bars([10]*74+[9.7,10.5]).drop(columns=['limit_up_price'])
    r=evaluate(engine,'C4',d)
    assert r.score==4 and r.conditions['limit_proxy_used']


@pytest.mark.parametrize('vr,expected',[(1.19,0),(1.2,2),(1.5,4),(1.8,5)])
def test_d1_volume_tiers(engine,vr,expected):
    d=bars([10]*75+[10.3],[100]*75+[vr*100]); r=evaluate(engine,'D1',d)
    assert r.score==expected
    assert r.raw_values['price_break'] and r.raw_values['m60_cross']


def test_d1_no_breakout(engine):
    assert evaluate(engine,'D1',bars([10]*80)).status=='FAIL'


@pytest.mark.parametrize('ratio,expected',[(0.8,0),(0.9,1),(1.2,3),(1.3,4)])
def test_d3_up_down(engine,ratio,expected):
    d=bars([10,11,10,11,10,11,10,11,10,11,10],[100]+[ratio*100,100]*5)
    assert evaluate(engine,'D3',d).score==expected


def test_d3_missing_group(engine):
    assert evaluate(engine,'D3',bars(range(10,31))).status=='UNKNOWN'


def test_d3_ambiguous_boundary(engine):
    d=bars([10,11,10,11,10,11,10,11,10,11,10],[100]+[110,100]*5)
    assert evaluate(engine,'D3',d).score==3  # V1.2: [1.10, 1.30)


@pytest.mark.parametrize('ratio,expected',[(0.7,2),(0.85,1),(1,0),(1.01,0)])
def test_d4_contraction(engine,ratio,expected):
    d=bars([10]*13,[100]*10+[ratio*100]*3)
    assert evaluate(engine,'D4',d).score==expected


def test_d4_limit_day_excluded(engine):
    d=bars([10]*12+[11]); r=evaluate(engine,'D4',d)
    assert r.status=='FAIL' and r.reason_code=='NOT_APPLICABLE'


@pytest.mark.parametrize('turn,score',[(0.9,0),(1,1),(2,3),(8,2),(8.01,2),(12,1),(12.01,1),(20,0),(20.1,0)])
def test_d5_boundaries(engine,turn,score):
    d=bars([10]); d['turnover_rate']=turn
    assert evaluate(engine,'D5',d).score==score


@pytest.mark.parametrize('rid',['A1','A2','A3'])
def test_benchmark_rules(engine,rid):
    d=bars(np.linspace(10,20,100)); r=engine.evaluate(rid,Context(d,benchmark=d))
    assert r.score>0 and r.status!='UNKNOWN'


def test_benchmark_stale(engine):
    d=bars(np.linspace(10,20,100)); r=engine.evaluate('A1',Context(d,benchmark=d.iloc[:-1]))
    assert r.status=='UNKNOWN'


@pytest.mark.parametrize('rid',['A1','A2','A3'])
def test_missing_benchmark(engine,rid):
    assert evaluate(engine,rid,bars([10]*100)).status=='UNKNOWN'


@pytest.mark.parametrize('rid',['C1','C2','C3','C4','D1','D3','D4','R9','R4','R11'])
def test_insufficient_data(engine,rid):
    r=evaluate(engine,rid,bars([10]*3))
    assert r.status=='UNKNOWN' and r.score is None and r.penalty is None


@pytest.mark.parametrize('rid',['C1','C2','C3','C4','D1','D3','D4','R9'])
def test_nan_is_not_fail(engine,rid):
    d=bars(np.linspace(10,20,100)); d.loc[99,'close_adj']=np.nan
    r=evaluate(engine,rid,d)
    assert r.status=='UNKNOWN'


def test_raw_does_not_replace_adjusted(engine):
    d=bars([10]*100).drop(columns='close_adj')
    assert evaluate(engine,'C1',d).status=='UNKNOWN'


def test_no_future_leakage(engine):
    d=bars([10]*75+[10.3,10.4,10.5]); cutoff=str(d.date.iloc[75].date())
    assert engine.evaluate('C4',Context(d,as_of=cutoff)).to_dict()==engine.evaluate('C4',Context(d.iloc[:76])).to_dict()


def test_zero_volume_denominator_unknown(engine):
    d=bars([10]*75+[10.3],[0]*75+[100])
    assert evaluate(engine,'D1',d).status=='UNKNOWN'
