"""User-confirmed V1.3 scenarios; all prices are synthetic test fixtures."""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from dataclasses import replace
import hashlib
import json
import numpy as np
import pytest
from conftest import bars,evaluate
from v12_fixtures import one_word,dragon
from app.rules.base import Context,indicators
from app.rules.patterns.dragon_gate import gate_at
from app.rules.risks.should_rise import ScoreSnapshot
from app.engine.score_engine import ScoreEngine

ROOT=Path(__file__).resolve().parents[1]


def r7_context(closes,highs):
    d=bars([10]*30+closes)
    for i,h in enumerate(highs): d.loc[30+i,'high_adj']=h
    snap=ScoreSnapshot(str(d.date.iloc[29].date()),10,80,'LOW','1.3','fixed-test-signal')
    return Context(d,metadata={'score_snapshots':[snap]})


@pytest.mark.parametrize('closes,highs,penalty,status',[
    ([9.9,10,9.95],[10.1]*3,10,'PASS'),
    ([10.01,10.1,10.05],[10.2]*3,6,'PASS'),
    ([10.1,10.29,10.2],[10.295]*3,6,'PASS'),
    ([10.1,10.2,10.1],[10.2,10.3,10.2],0,'INVALIDATED')],ids=['no_close_gain','one_percent','two_point_nine_percent','high_three_percent'])
def test_R7_final_penalty(engine,closes,highs,penalty,status):
    r=engine.evaluate('R7',r7_context(closes,highs))
    assert r.penalty==penalty and r.status==status
    assert r.raw_values['max_close_return']==pytest.approx(max(closes)/10-1)


@pytest.mark.parametrize('length',[0,1,2])
def test_R7_waits_three_complete_days(engine,length):
    r=engine.evaluate('R7',r7_context([10.1]*length,[10.2]*length))
    assert r.status=='UNKNOWN' and r.reason_code=='AWAITING_FORWARD_CONFIRMATION' and r.penalty is None


def test_R7_future_high_cannot_change_signal_day(engine):
    ctx=r7_context([10.1]*3,[10.2,10.3,10.2]); ctx.as_of=ctx.metadata['score_snapshots'][0].signal_date
    before=engine.evaluate('R7',ctx).to_dict()
    ctx.bars.loc[30:,'high_adj']=100
    assert engine.evaluate('R7',ctx).to_dict()==before


def e1_data(returns):
    c=[10]*140
    for ret in returns: c.append(c[-1]*(1+ret))
    d=bars(c); d.loc[30:80,'high_adj']=20
    d.loc[140:,'open_adj']=d.close_adj.shift().iloc[140:].values
    d['high_adj']=np.maximum(d.high_adj,np.maximum(d.open_adj,d.close_adj)+0.1)
    d['low_adj']=np.minimum(d.low_adj,np.minimum(d.open_adj,d.close_adj)-0.1)
    return d


def test_E1_seven_small_bulls_final(engine):
    r=evaluate(engine,'E1',e1_data([.01]*7))
    assert r.score==4 and r.raw_values['length']==7


def test_E1_one_transition_counts_as_day(engine):
    r=evaluate(engine,'E1',e1_data([.01]*6+[.045]))
    assert r.score==4 and r.raw_values['transition_count']==1 and r.raw_values['length']==7


def test_E1_second_transition_ends_current_run(engine):
    r=evaluate(engine,'E1',e1_data([.01,.04]+[.01]*5+[.049]))
    assert r.status=='INVALIDATED' and r.score==0
    assert r.raw_values['invalid_reason']=='TOO_MANY_TRANSITIONS'


def test_E1_transition_and_bear_have_separate_slots(engine):
    r=evaluate(engine,'E1',e1_data([.01,.04,.01,-.01,.01,.01,.01]))
    assert r.score==4
    assert r.raw_values['transition_count']==r.raw_values['exception_count']==1


def test_E1_second_exception_ends_current_run(engine):
    r=evaluate(engine,'E1',e1_data([.01,-.01]+[.01]*5+[-.01]))
    assert r.status=='INVALIDATED' and r.score==0


@pytest.mark.parametrize('ret,kind,score',[(.03999,'small_bull',4),(.04,'transition',4),(.04999,'transition',4),(.05,'BIG_BULL',0)],ids=['3.999','4.000','4.999','5.000'])
def test_E1_exact_boundaries(engine,ret,kind,score):
    r=evaluate(engine,'E1',e1_data([.01]*6+[ret]))
    assert r.score==score
    if kind=='BIG_BULL': assert r.status=='INVALIDATED' and r.raw_values['invalid_reason']==kind
    else: assert r.raw_values['run'][-1][kind]


def test_E1_cannot_reuse_segment_after_second_transition(engine):
    r=evaluate(engine,'E1',e1_data([.01,.04]+[.01]*5+[.049]+[.01]*4))
    assert r.score==0 and r.raw_values['length']==4


def test_E1_can_start_new_seven_day_run_after_break(engine):
    # Keep the new run's start within the inherited 15%-above-M60 low-zone gate.
    r=evaluate(engine,'E1',e1_data([.006,.04]+[.006]*5+[.049]+[.01]*7))
    assert r.score==4 and r.raw_values['length']==7


def jump_data():
    d=bars([10]*140+[10.2]); d['high_adj']=10.005+np.arange(len(d))*.00001
    d.loc[[128,134],'high_adj']=10.1
    d.loc[140,['open_adj','high_adj','low_adj','volume']]=[10,10.21,9.99,40]
    return d


def test_F1Y_two_percent_close_breakout(engine):
    r=evaluate(engine,'F1-Y',jump_data())
    assert r.conditions['dragon_gate_breakout'] and r.status=='CANDIDATE'
    assert r.raw_values['jump_close']==10.2


def test_F1Y_low_breakout_volume_is_allowed(engine):
    d=jump_data(); d.loc[140,'volume']=1
    r=evaluate(engine,'F1-Y',d)
    assert r.conditions['dragon_gate_breakout']


def test_F1Y_breakout_needs_no_limit_or_volume_fields(engine):
    d=jump_data().drop(columns=['limit_up_price','volume'])
    assert evaluate(engine,'F1-Y',d).conditions['dragon_gate_breakout']


def test_F1Y_intraday_high_only_is_not_breakout(engine):
    d=jump_data(); d.loc[140,['close_adj','open_adj']]=10
    d.loc[140,'high_adj']=12
    r=evaluate(engine,'F1-Y',d)
    assert not r.conditions['dragon_gate_breakout'] and r.score==0


@pytest.mark.parametrize('distance,valid',[(.03,True),(.03001,False)])
def test_F1Y_confluence_boundary(engine,distance,valid):
    d=jump_data(); d.loc[[128,134],'high_adj']=10*(1+distance)
    d['M60']=10
    assert (gate_at(d,140,engine.parameters) is not None)==valid


def test_F1Y_searches_older_confluence_pair(engine):
    d=jump_data(); d.loc[128,'high_adj']=10.00628
    d.loc[[100,120],'high_adj']=10.1; d.loc[134,'high_adj']=11
    d['M60']=10
    gate=gate_at(d,140,engine.parameters)
    assert gate['P2_date']==str(d.date.iloc[120].date())
    assert gate['P1_date']==str(d.date.iloc[100].date())


def test_F1Y_latest_valid_pair_wins(engine):
    d=jump_data(); d.loc[[100,120],'high_adj']=10.1; d['M60']=10
    gate=gate_at(d,140,engine.parameters)
    assert gate['P2_date']==str(d.date.iloc[134].date())
    assert gate['P1_date']==str(d.date.iloc[128].date())


def test_F1Y_only_confirmed_past_peaks(engine):
    d=jump_data(); d.loc[139,'high_adj']=15; d['M60']=10
    gate=gate_at(d,140,engine.parameters)
    assert gate['P2_date']==str(d.date.iloc[134].date())


def test_F1Y_low_gain_low_volume_full_fake_fall(engine):
    d=dragon(); d.loc[140,['close_adj','close_raw']]=10.2; d.loc[140,'volume']=40
    r=evaluate(engine,'F1-Y',d)
    assert r.score==8 and r.status=='CONFIRMED' and r.conditions['dragon_gate_breakout']


@pytest.mark.parametrize('turn,score,state',[(4.9,6,'PASS'),(5,6,'PASS'),(5.1,2,'PARTIAL'),(14.9,2,'PARTIAL'),(15,0,'FAIL')])
def test_F1O_final_turnover_tiers(engine,turn,score,state):
    r=evaluate(engine,'F1-O',one_word(turn=turn))
    assert r.score==score and r.status==state
    assert r.conditions['R12_abnormal']==(turn>=15)


@pytest.mark.parametrize('turn,score',[(5,5),(5.1,2),(14.9,2),(15,0)])
def test_F1O_one_word_T_same_tiers(engine,turn,score):
    d=one_word(turn=turn); d.loc[149,'low_raw']=10.7
    r=evaluate(engine,'F1-O',d)
    assert r.score==score and r.conditions['one_line_t']


def test_F1O_prior_expansion_partial_is_retained(engine):
    assert evaluate(engine,'F1-O',one_word(turn=4.9,pre_expansion=True)).score==2


def test_F1O_R12_cancels_positive_before_risk(engine):
    d=one_word(turn=5.1); d.loc[149,'volume']=300
    positive=evaluate(engine,'F1-O',d); risk=evaluate(engine,'R12',d)
    report=ScoreEngine(engine).aggregate([positive,risk])
    assert positive.score==0 and risk.penalty==5
    assert report['positive_score']==0 and report['risk_penalty']==5


def test_F1O_clean_tier_does_not_keep_superseded_volume_cap(engine):
    d=one_word(turn=5); d.loc[149,'volume']=200
    assert evaluate(engine,'F1-O',d).score==6


def c5_timeline():
    # 5-day platform, break, one more below day, recovery +8.25%, then flat.
    return bars([10]*70+[10.02]*5+[9.7,9.7]+[10.5]*5)


@pytest.mark.parametrize('end,score,state',[(75,4,'PASS'),(76,0,'INVALIDATED'),(78,0,'INVALIDATED'),(81,0,'INVALIDATED'),(82,4,'PASS')],ids=['five_days','break_sixth','recover_two_days','four_new_days','five_new_days'])
def test_T02_NEW_c5_platform_lifecycle(engine,end,score,state):
    d=c5_timeline().iloc[:end]
    r=evaluate(engine,'C5',d)
    assert r.score==score and r.status==state
    if end>75:
        assert r.raw_values['last_break_date']==str(d.date.iloc[76 if end>76 else 75].date())
    if end==82:
        assert r.raw_values['start_date']==str(d.date.iloc[77].date())
        assert r.raw_values['consecutive_days']==5


def test_T02_NEW_c4_recovery_does_not_restore_old_c5(engine):
    d=c5_timeline().iloc[:78]
    assert evaluate(engine,'C4',d).score==4
    assert evaluate(engine,'C5',d).score==0


def test_no_unresolved_user_semantics():
    text=(ROOT/'docs/USER_DECISIONS_REQUIRED.md').read_text(encoding='utf-8')
    assert 'No unresolved user-defined trading semantics remain in V1.3.' in text
    assert text.count('RESOLVED_IN_V1_3')>=4
    for p in (ROOT/'app').rglob('*.py'):
        assert 'USER_DECISION_REQUIRED' not in p.read_text(encoding='utf-8')


def test_all_rule_results_have_v13_version(engine):
    ctx=Context(bars([10]*150))
    for r in engine.evaluate_all(ctx,include_sector=True):
        assert r.spec_version=='1.4' and r.assumption_version=='v1.3'
    report=ScoreEngine(engine).evaluate(ctx)
    assert report['spec_version']=='1.4' and report['assumption_version']=='v1.3'


@pytest.mark.parametrize('version,digest',[
    ('1.1','79ec2876cd3658a2ae9da2fab3a397c9b192d98d39058cb6ed60c0e7448b0a8b'),
    ('1.2','7996e7f8403b5fe258edd83d26289a99443a715fc3fdb9196592de5d37c4d2cb')])
def test_old_spec_documents_unchanged(version,digest):
    path=next((ROOT/'docs').glob('*V'+version+'*.docx'))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def test_final_four_code_status_implemented(engine):
    for rid in ['E1','F1-O','F1-Y','R7','C5','C6','E2','E3','F1-N','F1-T','F3','R8','R12']:
        assert engine.registry[rid]['code_status']=='IMPLEMENTED'


def test_v13_word_contains_final_semantics_and_superseded_markers():
    with ZipFile(next((ROOT/'docs').glob('*V1.3*.docx'))) as z:
        doc=ET.fromstring(z.read('word/document.xml'))
    text=''.join(doc.itertext())
    assert 'No unresolved user-defined trading semantics remain in V1.3.' in text
    assert 'T02_NEW' in text and 'SUPERSEDED_BY_V1_3' in text
    assert '0<max_close_return<3%' in text and '最多1根' in text


def test_scoring_weights_unchanged(engine):
    import yaml
    with ZipFile(ROOT/'docs/archive/stage1_1_v1_2_baseline.zip') as z:
        old=yaml.safe_load(z.read('config/scoring_rules.yaml'))['rules']
    for r in old:
        now=engine.registry[r['rule_id']]
        assert (now['max_score'],now['max_penalty'])==(r['max_score'],r['max_penalty'])
