import numpy as np
import pytest
from conftest import bars,evaluate,double_top,n_board
from app.rules.base import Context
from app.engine.score_engine import ScoreEngine


@pytest.mark.parametrize('turn,penalty',[(14.99,0),(15,5),(20,10),(30,15)])
def test_r1_tiers(engine,turn,penalty):
    d=bars(np.linspace(10,30,150)); d['turnover_rate']=turn
    r=evaluate(engine,'R1',d)
    assert r.penalty==penalty
    assert r.conditions['hard_high']==(turn>=30)


@pytest.mark.parametrize('vr,penalty',[(1.49,0),(1.5,5),(2,10),(3,15)])
def test_r2_tiers(engine,vr,penalty):
    d=bars(np.linspace(10,30,150)); d.loc[149,'volume']=vr*100
    assert evaluate(engine,'R2',d).penalty==penalty


def test_low_zone_not_penalized_for_volume_turnover(engine):
    d=bars(np.linspace(30,10,150)); d.loc[149,['volume','turnover_rate']]=[1000,40]
    assert evaluate(engine,'R1',d).penalty==0
    assert evaluate(engine,'R2',d).penalty==0


@pytest.mark.parametrize('tail,expected', [([9.5],6),([9.5,9.4],10),([10],2)])
def test_r9_tiers(engine,tail,expected):
    assert evaluate(engine,'R9',bars([10]*40+tail)).penalty==expected


def test_r9_recovery(engine):
    r=evaluate(engine,'R9',bars([10]*40+[9.5,10.3]))
    assert r.status=='INVALIDATED' and r.penalty==0


def test_r9_intraday_warning(engine):
    d=bars([10]*40); d.loc[39,'low_adj']=9
    assert evaluate(engine,'R9',d).penalty==2


@pytest.mark.parametrize('state,penalty',[('CANDIDATE',4),('FORMED',8),('CONFIRMED',12),('INVALIDATED',0)])
def test_double_top_states(engine,state,penalty):
    r=evaluate(engine,'R4',double_top(state),adjustment_consistent=True)
    assert (r.status,r.penalty)==(state,penalty),r.to_dict()
    assert r.raw_values['gap_days']==10
    assert r.raw_values['neckline']==17
    assert r.raw_values['valley_drawdown']>=0.05
    assert r.event_id and r.conditions['P2_confirmed']


def test_double_top_latest_peak_is_only_candidate(engine):
    d=double_top().iloc[:141]
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='CANDIDATE' and not r.conditions['P2_confirmed']


def test_double_top_one_right_bar_ambiguous(engine):
    r=evaluate(engine,'R4',double_top().iloc[:142],adjustment_consistent=True)
    assert r.status=='CANDIDATE' and not r.conditions['P2_confirmed']  # V1.2 no future confirmation


def test_double_top_adjustment_unknown(engine):
    assert evaluate(engine,'R4',double_top()).status=='UNKNOWN'


def test_double_top_requires_valley(engine):
    d=double_top(); d.loc[131:139,['open_adj','close_adj']]=19.4
    d.loc[131:139,'low_adj']=19.35; d.loc[131:139,'high_adj']=19.5
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='FAIL'


def test_double_top_requires_similar_heights(engine):
    d=double_top(); d.loc[140,'high_adj']=21
    # Prevent another flat candidate after replacing P2.
    d.loc[141:142,'high_adj']=[20.8,20.7]
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='FAIL'


def test_double_top_rejects_low_context(engine):
    d=double_top(); d.loc[:129,['open_adj','close_adj']]=20.5
    d.loc[:129,'high_adj']=20.6; d.loc[:129,'low_adj']=20.4
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='FAIL'


def test_double_top_one_breakout_day_not_invalidated(engine):
    d=double_top('INVALIDATED').iloc[:-1]
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status!='INVALIDATED'


def test_double_top_invalidation_is_strict(engine):
    d=double_top('INVALIDATED'); d.loc[143:144,'close_adj']=20*1.03
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status!='INVALIDATED'


def test_double_top_point_in_time(engine):
    d=double_top('INVALIDATED'); cutoff=str(d.date.iloc[142].date())
    r=engine.evaluate('R4',Context(d,as_of=cutoff,metadata={'adjustment_consistent':True}))
    assert r.status=='CANDIDATE' and r.penalty==4


def test_double_top_single_penalty(engine):
    r=evaluate(engine,'R4',double_top('CONFIRMED'),adjustment_consistent=True)
    score=ScoreEngine(engine).aggregate([r,r])
    assert score['risk_penalty']==12


def test_n_low_break_cannot_recover(engine):
    d=n_board(broken=True)
    n=evaluate(engine,'F1-N',d); risk=evaluate(engine,'R11',d)
    assert n.status=='INVALIDATED' and n.score==0
    assert risk.penalty==8
    assert risk.raw_values['break']['close']>risk.raw_values['break']['M5']


def test_n_candidate(engine):
    r=evaluate(engine,'F1-N',n_board())
    assert r.status=='CANDIDATE' and r.score==4


def test_n_second_start(engine):
    r=evaluate(engine,'F1-N',n_board(confirmed=True))
    assert r.status=='CONFIRMED' and r.score==10


def test_n_break_persists_after_recovery(engine):
    d=n_board(broken=True,confirmed=True)
    assert evaluate(engine,'F1-N',d).status=='INVALIDATED'
    assert evaluate(engine,'R11',d).penalty==8


def test_n_no_event(engine):
    r=evaluate(engine,'R11',bars([10]*100))
    assert r.penalty==0 and r.applicable is False
