from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from conftest import bars,evaluate,n_board,double_top
from app.rules.base import Context,indicators,result
from app.rules.patterns.dragon_gate import gate_at
from app.rules.risks.should_rise import ScoreSnapshot
from app.engine.score_engine import ScoreEngine
from app.engine.coverage import calculate
from v12_fixtures import *


def test_C5_five_days_above(engine):
    r=evaluate(engine,'C5',platform_bars()); assert r.score==4


def test_C5_one_close_below_fails(engine):
    r=evaluate(engine,'C5',platform_bars(True)); assert r.status=='INVALIDATED'


def test_C5_no_volume_requirement(engine):
    d=platform_bars().drop(columns='volume'); assert evaluate(engine,'C5',d).score==4


def test_C4_quick_reclaim_v12(engine):
    assert evaluate(engine,'C4',bars([10]*75+[9.7,10.5])).score==4


def test_belt_intraday_low_does_not_break(engine):
    ctx=belt_context(intraday=True)
    assert engine.evaluate('C6',ctx).score==3
    assert engine.evaluate('R8',ctx).penalty==0


def test_belt_close_invalidates(engine):
    ctx=belt_context(broken=True)
    r=engine.evaluate('C6',ctx); risk=engine.evaluate('R8',ctx)
    assert r.status=='INVALIDATED' and r.score==0
    assert risk.penalty==12 and len(risk.conditions['broken_timeframes'])==3


def test_incomplete_week_not_used(engine):
    ctx=belt_context(); w=ctx.metadata['period_bars']['W']; w.loc[len(w)-1,'is_complete']=False
    r=engine.evaluate('C6',ctx)
    assert r.raw_values['timeframes']['W']['evaluation_date']==str(w.date.iloc[-2].date())


def test_E1_seven_small_bulls(engine):
    r=evaluate(engine,'E1',small_bulls()); assert r.score==4,r.to_dict()
    assert r.raw_values['started'] is not True


def test_E1_one_small_bear(engine):
    assert evaluate(engine,'E1',small_bulls(exception=True)).score==4


def test_E1_big_bull_invalidates(engine):
    assert evaluate(engine,'E1',small_bulls(big=True)).status=='INVALIDATED'


def test_E1_transition_explicit_partial_guard(engine):
    r=evaluate(engine,'E1',small_bulls(transition=True))
    assert r.score==4 and r.raw_values['transition_count']==1  # USER_CONFIRMED V1.3


def test_E2_reference_peak_window(engine):
    r=engine.evaluate('E2',weekly_reversal()); assert r.raw_values['previous_cycle_peak_volume']==1000
    assert len(r.raw_values['reference_weeks'])==5


def test_E2_exceeds_peak_no_wow_requirement(engine):
    r=engine.evaluate('E2',weekly_reversal()); assert r.status=='CONFIRMED' and r.score==4


def test_E2_strict_volume_exceed(engine):
    ctx=weekly_reversal(); ctx.metadata['period_bars']['W'].loc[24,'volume']=1000
    assert engine.evaluate('E2',ctx).status=='CANDIDATE'


def test_E3_variable_amplitudes(engine):
    r=evaluate(engine,'E3',damping()); assert r.score==3 and not r.conditions['shrinking_amplitude_required']


def test_E3_up_volume_must_exceed_down(engine):
    d=damping(); d['volume']=100
    assert evaluate(engine,'E3',d).status=='FAIL'


def test_E3_three_each_required(engine):
    d=bars([10,11,12,13,12,11,12,13])
    assert evaluate(engine,'E3',d).status=='UNKNOWN'


def test_N_multiple_starts_searches_older_complete(engine):
    d=n_board(confirmed=True); d.loc[123,'limit_up_price']=d.close_raw.iloc[123]
    r=evaluate(engine,'F1-N',d); assert r.status=='CONFIRMED'
    assert r.raw_values['first_start_date']==str(d.date.iloc[120].date())


def test_N_intraday_break_irreversible_v12(engine):
    assert evaluate(engine,'F1-N',n_board(broken=True,confirmed=True)).status=='INVALIDATED'


def test_T_open_not_at_limit(engine):
    assert evaluate(engine,'F1-T',t_board()).score==8


def test_T_low_not_two_percent(engine):
    assert evaluate(engine,'F1-T',t_board(open_price=10.95,low=10.9)).score==0


def test_one_word_clean(engine):
    r=evaluate(engine,'F1-O',one_word()); assert r.score==6,r.to_dict()


def test_one_word_turn_over_five_not_full(engine):
    r=evaluate(engine,'F1-O',one_word(turn=6)); assert r.score is None or r.score<6


def test_one_word_pre_volume_expansion_partial(engine):
    assert evaluate(engine,'F1-O',one_word(pre_expansion=True)).score==2


@pytest.mark.parametrize('length,score',[(2,8),(4,7),(6,6)])
def test_refuel_lengths(engine,length,score):
    r=evaluate(engine,'F3',refuel(length)); assert r.score==score,r.to_dict()


def test_refuel_low_break_invalidated(engine):
    assert evaluate(engine,'F3',refuel(4,broken=True)).status=='INVALIDATED'


def test_refuel_micro_gain_no_confirmation(engine):
    d=refuel(2); d.loc[123,'close_adj']=d.close_adj.iloc[122]*1.001
    assert evaluate(engine,'F3',d).status!='CONFIRMED'


def test_dragon_confluence(engine):
    d=indicators(dragon(),engine.parameters); gate=gate_at(d,140,engine.parameters)
    assert gate and gate['confluence_distance']<=0.03


def test_dragon_no_confluence(engine):
    d=dragon(); d.loc[:139,'high_adj']=14
    # All maxima at the same high leave an extrapolated resistance above M60.
    assert gate_at(indicators(d,engine.parameters),140,engine.parameters) is None


def test_dragon_single_day_huge_volume_and_recovery(engine):
    r=evaluate(engine,'F1-Y',dragon()); assert r.status=='CONFIRMED' and r.score==8,r.to_dict()
    assert r.conditions['huge_volume']


def snapshot_ctx(highs,score=80,risk='LOW',length=3):
    d=bars([10]*30+[10.01]*length)
    for i,h in enumerate(highs[:length]): d.loc[30+i,'high_adj']=h
    snap=ScoreSnapshot(str(d.date.iloc[29].date()),10,score,risk,'1.3','synthetic-frozen-evidence')
    return Context(d,metadata={'score_snapshots':[snap]})


def test_R7_exact_80_enters_observation(engine):
    r=engine.evaluate('R7',snapshot_ctx([],length=0))
    assert r.status=='UNKNOWN' and r.reason_code=='AWAITING_FORWARD_CONFIRMATION'


def test_R7_no_three_percent_triggers(engine):
    assert engine.evaluate('R7',snapshot_ctx([10.2]*3)).penalty==6


def test_R7_three_percent_boundary_invalidates(engine):
    assert engine.evaluate('R7',snapshot_ctx([10.2,10.3,10.2])).status=='INVALIDATED'


def test_R7_high_risk_not_eligible(engine):
    assert engine.evaluate('R7',snapshot_ctx([10.2]*3,risk='HIGH')).status=='FAIL'


def test_R7_asof_does_not_see_future(engine):
    ctx=snapshot_ctx([10.2]*3); ctx.as_of=ctx.metadata['score_snapshots'][0].signal_date
    assert engine.evaluate('R7',ctx).reason_code=='AWAITING_FORWARD_CONFIRMATION'


def test_R4_multiple_select_latest_P2(engine):
    d=double_top(); d.loc[139,'high_adj']=19.8
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='CANDIDATE' and r.raw_values['P2']['date']==str(d.date.iloc[140].date())


def test_R4_same_P2_closest_height(engine):
    d=double_top(); d.loc[129,'high_adj']=20.01; d.loc[130,'high_adj']=20.01
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status!='UNKNOWN'
    selected=abs(r.raw_values['P2']['high']-r.raw_values['P1']['high'])
    same=[c['absolute_peak_difference'] for c in r.raw_values['selection_candidates'] if c['P2_date']==r.raw_values['P2']['date']]
    assert selected==min(same)


def test_R4_alert_and_invalidation_clear(engine):
    a=evaluate(engine,'R4',double_top(),adjustment_consistent=True)
    b=evaluate(engine,'R4',double_top('INVALIDATED'),adjustment_consistent=True)
    assert a.exit_risk_alert and a.alert_type=='DOUBLE_TOP_EXIT_RISK'
    assert not b.exit_risk_alert and b.penalty==0 and b.alert_text is None


def test_coverage_states_and_caps_v12(engine):
    items=[]
    for r in engine.registry.values():
        if r['rule_type']=='POSITIVE':
            item=result(r,'CONFIRMED',score=0,explanation='synthetic coverage judgment'); item.code_status='IMPLEMENTED'; items.append(item)
    cov=calculate(items,engine.parameters); assert cov['coverage']==100


@pytest.mark.parametrize('rid,d,score',[('C2',bars([10]*80),2),('D3',bars([10,11,10,11,10,11,10,11,10,11,10],[100]+[110,100]*5),3)])
def test_resolved_boundaries(engine,rid,d,score):
    assert evaluate(engine,rid,d).score==score


def test_B3_leader_intraday_invalidates(engine):
    assert engine.evaluate('B3',leader_context()).status=='INVALIDATED'


@pytest.mark.parametrize('last_ten,expected',[(103,4),(112,5)])
def test_C2_half_percent_and_two_percent(engine,last_ten,expected):
    assert evaluate(engine,'C2',bars([100]*60+[last_ten]*10)).score==expected


@pytest.mark.parametrize('last,expected',[(100,2),(103,3),(97,1)])
def test_A3_boundaries(engine,last,expected):
    d=bars([100]*5+[last]); assert engine.evaluate('A3',Context(d,benchmark=d)).score==expected


def test_R4_same_P2_different_peak_heights(engine):
    d=double_top(); d.loc[122,'high_adj']=20.3
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.raw_values['P1']['date']==str(d.date.iloc[130].date())
    same=[x for x in r.raw_values['selection_candidates'] if x['P2_date']==r.raw_values['P2']['date']]
    assert len(same)>=2 and len({x['absolute_peak_difference'] for x in same})>=2


def test_R12_cancels_T_in_score_engine(engine):
    d=t_board(); d.loc[149,['volume','turnover_rate']]=[400,20]
    t=evaluate(engine,'F1-T',d); risk=evaluate(engine,'R12',d)
    report=ScoreEngine(engine).aggregate([t,risk])
    assert t.score==8 and risk.penalty==10
    assert report['positive_score']==0 and report['risk_penalty']==10


def test_snapshot_is_immutable_and_date_bound(engine):
    from dataclasses import FrozenInstanceError
    d=bars([10]*80); report=ScoreEngine(engine).evaluate(Context(d))
    snapshot=ScoreSnapshot.freeze(report,d)
    with pytest.raises(FrozenInstanceError): snapshot.quant_score=80
    with pytest.raises(ValueError): ScoreSnapshot.freeze(report,d.iloc[:-1])


def test_R7_adjustment_mismatch_unknown(engine):
    ctx=snapshot_ctx([10.2]*3); ctx.bars.loc[29,'close_adj']=11
    assert engine.evaluate('R7',ctx).reason_code=='INVALID_SNAPSHOT'


def test_R7_new_unassigned_severity_is_explicit(engine):
    ctx=snapshot_ctx([10.25]*3); ctx.bars.loc[30:32,'close_adj']=10.2
    ctx.bars.loc[30:32,'open_adj']=10.2
    r=engine.evaluate('R7',ctx)
    assert r.penalty==6 and r.reason_code is None  # USER_CONFIRMED V1.3


def test_E3_nan_in_earlier_window_unknown(engine):
    d=damping(); d.loc[0,'close_adj']=np.nan
    assert evaluate(engine,'E3',d).status=='UNKNOWN'
