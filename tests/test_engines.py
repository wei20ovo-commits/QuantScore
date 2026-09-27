from copy import deepcopy
import json
import numpy as np
import pytest
from app.engine.rule_engine import RuleEngine,EVALUATORS
from app.engine.score_engine import ScoreEngine
from app.engine.conflicts import resolve
from app.engine.coverage import calculate
from app.rules.base import Context,result
from app.models.schemas import RuleResult
from conftest import bars,evaluate,double_top


def sample(engine,rid,score=0,penalty=0,status=None,**extra):
    return result(engine.registry[rid],status,score=score,penalty=penalty,explanation='人工构造引擎输入，用于验证汇总契约。',**extra)


def test_registry_complete(engine):
    assert len(engine.registry)==48
    fields={'rule_id','name_cn','name_en','category','rule_type','source_type','max_score','max_penalty','required_fields','lookback','prerequisites','parameters','status_values','scoring_levels','invalidation_rules','unknown_conditions','conflict_rules','explanation_template','spec_version'}
    for rid,r in engine.registry.items():
        assert fields<=set(r)
        assert r['spec_version']=='1.4'  # Stage2 contract; frozen scoring thresholds unchanged.
        assert r['definition'] and r['scoring_levels']['spec_text'] and r['explanation_template']
        assert (rid in EVALUATORS)==(r['evaluator'] is not None)
    assert engine.registry['C1']['max_score']==5
    assert len([r for r in engine.registry.values() if r['code_status']=='IMPLEMENTED' and r['source_type'] in ('AUTO','AUTO_PROXY')])>=10


@pytest.mark.parametrize('rid',['E4','E5','R10','R6','C5','C6','F1-T','F1-O','F1-X','F1-Y','F3','E1','E2','E3','R7'])
def test_unimplemented_never_fake_pass(engine,rid):
    r=evaluate(engine,rid,bars([10]*150))
    # All original parameter cases retained. V1.2 migrated implemented IDs
    # now assert their exact deterministic flat-market outcome.
    expected={'C5':('PASS',4),'C6':('PARTIAL',0),'F1-T':('FAIL',0),
              'F1-O':('FAIL',0),'F1-Y':('FAIL',0),'F3':('FAIL',0),
              'E1':('INVALIDATED',0),'E2':('FAIL',0),'F1-X':('FAIL',0)}
    if rid in expected:
        assert (r.status,r.score)==expected[rid]
    else:
        assert r.status=='UNKNOWN' and r.score is None
        assert r.reason_code==('DATA_INSUFFICIENT' if rid in ('E3','R7') else 'NOT_IMPLEMENTED')


def test_manual_rule_cannot_auto_pass(engine):
    registry=deepcopy(engine.registry); registry['C1']['source_type']='MANUAL'
    manual=RuleEngine(registry,engine.parameters)
    r=evaluate(manual,'C1',bars(np.linspace(10,20,100)))
    assert r.status=='UNKNOWN' and r.reason_code=='MANUAL_REQUIRED'
    cov=calculate([r],engine.parameters)
    assert cov['breakdown']['positive']['manual']==1 and cov['coverage']==0


def test_unknown_schema_rejects_zero(engine):
    r=evaluate(engine,'C1',bars([10])); data=r.to_dict(); data['score']=0
    with pytest.raises(ValueError): RuleResult(**data)


def test_results_json_serializable(engine):
    d=bars(np.linspace(10,30,150)); out=ScoreEngine(engine).evaluate(Context(d,benchmark=d,metadata={'adjustment_consistent':True}))
    json.dumps(out,allow_nan=False)
    assert len(out['rules'])==41
    assert out['sector_heat_score'] is None
    assert out['score_status']=='PARTIAL' and .70<=out['positive_coverage']<.90  # Five additional rules increase observed coverage.


def test_coverage_exact_spec_formula(engine):
    items=[sample(engine,'C1',score=5),sample(engine,'C3',status='FAIL'),sample(engine,'D3',score=1),sample(engine,'C4',status='UNKNOWN'),sample(engine,'F1-N',status='CANDIDATE',score=4)]
    c=calculate(items,engine.parameters)
    assert c['coverage']==23
    assert c['positive_coverage']==0.23
    assert c['breakdown']['positive']['unknown']==1
    assert c['breakdown']['positive']['status_counts']['CANDIDATE']==1


def test_risk_coverage_unknown_applicability(engine):
    items=[sample(engine,'R1',penalty=5,applicable=True),sample(engine,'R2',status='UNKNOWN'),sample(engine,'R11',status='FAIL',applicable=False)]
    c=calculate(items,engine.parameters)
    assert c['risk_coverage']==pytest.approx(2/3)
    assert c['risk_coverage_lower_bound']==pytest.approx(2/3)
    assert c['risk_coverage_upper_bound']==pytest.approx(2/3)


def test_risk_coverage_known_denominator(engine):
    items=[sample(engine,'R1',penalty=5,applicable=True),sample(engine,'R2',status='UNKNOWN',applicable=True)]
    assert calculate(items,engine.parameters)['risk_coverage']==0.5


def test_n_cancellation_before_penalty(engine):
    n=sample(engine,'F1-N',score=10); r=sample(engine,'R11',penalty=8)
    out=ScoreEngine(engine).aggregate([n,r,r])
    assert out['positive_score']==0 and out['risk_penalty']==8 and out['final_score']==0
    assert out['rules'][0]['status']=='INVALIDATED'
    assert n.score==10  # immutable evaluation evidence


@pytest.mark.parametrize('risk,targets,penalty',[('R12',['F1-T','F1-O'],10),('R3',['F1-T','F1-O'],15),('R10',['E4','E5'],12)])
def test_corresponding_positive_cancellation(engine,risk,targets,penalty):
    items=[sample(engine,rid,score=engine.registry[rid]['max_score']) for rid in targets]
    out=ScoreEngine(engine).aggregate(items+[sample(engine,risk,penalty=penalty)])
    assert out['positive_score']==0 and out['risk_penalty']==penalty


def test_r8_cancels_only_corresponding_timeframe(engine):
    c=sample(engine,'C6',score=3,raw={'timeframe_scores':{'D':1,'W':1,'M':1}})
    r=sample(engine,'R8',penalty=6,conditions={'broken_timeframes':['D']})
    resolved=resolve([c,r]); assert resolved[0].score==2


def test_f1_mutual_exclusion_and_f_cap(engine):
    items=[sample(engine,'F1-N',score=10),sample(engine,'F1-T',score=8),sample(engine,'F2',score=5),sample(engine,'F3',score=8)]
    out=ScoreEngine(engine).aggregate(items)
    assert out['positive_score']==15
    assert [r for r in out['rules'] if r['rule_id']=='F1-T'][0]['score']==0


def test_f2_requires_f1(engine):
    assert ScoreEngine(engine).aggregate([sample(engine,'F2',score=5)])['positive_score']==0


def test_risk_hard_high_overrides_low_sum(engine):
    r=sample(engine,'R1',penalty=15,conditions={'hard_high':True})
    assert ScoreEngine(engine).aggregate([r])['risk_level']=='HIGH'


def test_double_top_and_volume_hard_high(engine):
    r4=sample(engine,'R4',status='CONFIRMED',penalty=12)
    r2=sample(engine,'R2',penalty=5)
    out=ScoreEngine(engine).aggregate([r4,r2])
    assert out['risk_level']=='HIGH' and out['risk_penalty']==17


def test_conflicting_duplicate_rejected(engine):
    with pytest.raises(ValueError): resolve([sample(engine,'R1',penalty=5),sample(engine,'R1',penalty=15)])


@pytest.mark.parametrize('problem',['date_missing','duplicate','unsorted','invalid_date'])
def test_invalid_date_contract(engine,problem):
    d=bars([10]*100)
    if problem=='date_missing': d=d.drop(columns='date')
    elif problem=='duplicate': d.loc[99,'date']=d.date.iloc[98]
    elif problem=='unsorted': d=d.iloc[::-1]
    else: d.loc[99,'date']=None
    assert evaluate(engine,'C1',d).reason_code=='INVALID_DATA'


def test_schema_all_statuses(engine):
    for status in engine.registry['C1']['status_values']:
        r=sample(engine,'C1',status=status)
        assert r.to_dict()['status']==status


def test_at_least_ten_auto_rules_have_evidence(engine):
    d=bars(np.linspace(10,30,150))
    results=engine.evaluate_all(Context(d,benchmark=d,metadata={'adjustment_consistent':True}))
    known=[r for r in results if r.code_status=='IMPLEMENTED' and r.status!='UNKNOWN']
    assert len(known)>=10
    for r in known:
        assert r.raw_values and r.conditions and r.explanation
