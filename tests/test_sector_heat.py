"""Offline scoring boundaries. Altered values below are synthetic test scenarios."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from app.sector.models import SectorRuleInput
from app.sector.scoring import SectorHeatEngine
from app.sector.readiness import downstream_readiness

FIXTURE=json.loads((Path(__file__).parent/'fixtures/stage3b_c25_inputs.json').read_text(encoding='utf-8'))
DAY=FIXTURE['trade_date']

def inputs():
    return {k:SectorRuleInput(deepcopy(v),DAY) for k,v in FIXTURE['inputs'].items()}

def raw_for(rid,value):
    raw=deepcopy(FIXTURE['inputs'][rid])
    if rid in ('S1','S2'):
        p='1d' if rid=='S1' else '5d'
        raw.update({f'sector_return_{p}':value,f'benchmark_return_{p}':0,f'sector_excess_return_{p}':value})
    elif rid in ('S3','S7'):
        n=1000000;count=round(value*n)
        if rid=='S3':raw.update(advancing_constituents=count,valid_constituents=n,expected_constituents=n,breadth=value,coverage=1)
        else:raw.update(strong_count=count,valid_return_count=n,expected_count=n,strong_ratio=value)
    elif rid=='S5':
        raw.update(sector_amount_today=value*100,sector_amount_prior_20d_mean=100,amount_ratio=value)
        for r in raw['daily_amounts']:r['sector_amount']=100
        raw['daily_amounts'][-1]['sector_amount']=value*100
    elif rid=='S6':
        raw['win_days']=value
        for i,r in enumerate(raw['daily_comparisons']):r.update(sector_return=.01 if i<value else 0,benchmark_return=0,sector_win=i<value)
    return raw

CASES={
 'S1':[(-.01,0),(0,5),(.000001,5),(.004999,5),(.005,10),(.005001,10),(.009999,10),(.01,16),(.010001,16),(.019999,16),(.02,20),(.020001,20),(.1,20)],
 'S2':[(-.01,0),(0,6),(.000001,6),(.019999,6),(.02,12),(.020001,12),(.039999,12),(.04,16),(.040001,16),(.059999,16),(.06,20),(.060001,20),(.2,20)],
 'S3':[(.1,0),(.499999,0),(.5,4),(.500001,4),(.599999,4),(.6,8),(.600001,8),(.699999,8),(.7,12),(.700001,12),(.799999,12),(.8,15),(.800001,15),(1,15)],
 'S5':[(0,0),(.899999,0),(.9,4),(.900001,4),(1.149999,4),(1.15,8),(1.150001,8),(1.399999,8),(1.4,12),(1.400001,12),(1.799999,12),(1.8,15),(1.800001,15),(3,15)],
 'S6':[(0,0),(1,0),(2,2),(3,5),(4,8),(5,10)],
 'S7':[(0,0),(.049999,0),(.05,2),(.050001,2),(.099999,2),(.1,4),(.100001,4),(.149999,4),(.15,5),(.150001,5),(1,5)]}

@pytest.mark.parametrize('rid,value,score',[(rid,x,s) for rid,pairs in CASES.items() for x,s in pairs])
def test_all_continuous_and_discrete_boundaries(rid,value,score):
    r=SectorHeatEngine().score_rule(rid,SectorRuleInput(raw_for(rid,value),DAY),DAY)
    assert r.score==score,r.explanation
    assert r.threshold_band and str(score) in r.explanation and r.raw_inputs

def limit_raw(n,expected=100):
    details=[dict(symbol=f'{i:06d}.SZ',date=DAY,status='VALID',rule_source='fixture verified limit source',calculated_limit_up=11,actual_close=11 if i<n else 10,closed_at_limit_up=i<n) for i in range(expected)]
    return dict(limit_up_count=n,valid_limit_count=expected,expected_count=expected,limit_up_ratio=n/expected,limit_details=details)

@pytest.mark.parametrize('n,expected,score',[(0,100,0),(1,100,3),(2,100,6),(3,100,12),(4,100,12),(5,101,12),(5,100,15),(6,100,15),(10,100,15)])
def test_s4_absolute_and_ratio_boundaries(n,expected,score):
    assert SectorHeatEngine().score_rule('S4',SectorRuleInput(limit_raw(n,expected),DAY),DAY).score==score

@pytest.mark.parametrize('rid',[f'S{i}' for i in range(1,8)])
@pytest.mark.parametrize('status',['DATA_ERROR','DATA_STALE','DATA_INCONSISTENT','NOT_APPLICABLE'])
def test_data_status_never_becomes_zero(rid,status):
    r=SectorHeatEngine().score_rule(rid,SectorRuleInput(FIXTURE['inputs'][rid],DAY,status),DAY)
    assert r.score is None and r.status=='UNKNOWN' and r.data_status==status

@pytest.mark.parametrize('rid',['S1','S3','S5','S6'])
def test_low_coverage_blocks_score(rid):
    raw=deepcopy(FIXTURE['inputs'][rid]);raw['coverage']=.799999
    assert SectorHeatEngine().score_rule(rid,SectorRuleInput(raw,DAY),DAY).score is None

@pytest.mark.parametrize('rid',['S3','S4','S7'])
def test_minimum_sample_below_and_exact(rid):
    if rid=='S4':raw=limit_raw(0,9)
    elif rid=='S3':raw=dict(valid_constituents=9,expected_constituents=9,advancing_constituents=0,breadth=0,coverage=1)
    else:raw=dict(valid_return_count=9,expected_count=9,strong_count=0,strong_ratio=0)
    assert SectorHeatEngine().score_rule(rid,SectorRuleInput(raw,DAY),DAY).reason_code=='INSUFFICIENT_MEMBERS'
    if rid=='S4':raw=limit_raw(0,10)
    else:
        for k in list(raw):
            if k.startswith(('valid_','expected_')):raw[k]=10
    assert SectorHeatEngine().score_rule(rid,SectorRuleInput(raw,DAY),DAY).score==0

def test_total_partial_max_and_manual_independent_c25_scores():
    e=SectorHeatEngine();r=e.evaluate('C25','fixture',DAY,inputs(),{'source':'fixed Stage35 fixture'})
    # Hand-derived CSV thresholds: 0.203746% ->5; 2.016126% ->12;
    # 4/17 breadth ->0; no limits ->0; .808071 amount ->0; four daily wins ->8; zero strong ->0.
    assert [getattr(r,f's{i}').score for i in range(1,8)]==[5,12,0,0,0,8,0]
    assert r.total_score==25 and r.max_score==100 and r.score_coverage==1
    x=inputs();x['S2']=SectorRuleInput({},DAY,'DATA_ERROR')
    r=e.evaluate('C25','fixture',DAY,x,{})
    assert r.total_score is None and r.available_score==13 and r.available_max_score==80 and r.score_coverage==.8
    assert r.overall_status=='DATA_INCOMPLETE'

def test_highest_all_rules_naturally_sum_to_100():
    x={rid:SectorRuleInput(raw_for(rid,pairs[-1][0]),DAY) for rid,pairs in CASES.items()}
    x['S4']=SectorRuleInput(limit_raw(10),DAY)
    r=SectorHeatEngine().evaluate('x','x',DAY,x,{})
    assert r.total_score==100 and r.available_max_score==100

def test_deterministic_and_does_not_mutate_inputs():
    x=inputs();before=deepcopy(x);e=SectorHeatEngine()
    a=e.evaluate('x','x',DAY,x,{'provider':'archive'}).to_dict()
    assert a==e.evaluate('x','x',DAY,x,{'provider':'archive'}).to_dict() and x==before

@pytest.mark.parametrize('rid',[f'S{i}' for i in range(1,8)])
def test_date_mismatch_is_stale(rid):
    r=SectorHeatEngine().score_rule(rid,SectorRuleInput(FIXTURE['inputs'][rid],'2026-09-24'),DAY)
    assert r.score is None and r.data_status=='DATA_STALE'

@pytest.mark.parametrize('rid',['S1','S2','S3','S5','S7'])
def test_nan_inf_and_inconsistent_derived_inputs_are_rejected(rid):
    raw=raw_for(rid,0)
    key={'S1':'sector_excess_return_1d','S2':'sector_excess_return_5d','S3':'breadth','S5':'amount_ratio','S7':'strong_ratio'}[rid]
    for bad in [float('nan'),float('inf'),.777]:
        raw[key]=bad
        assert SectorHeatEngine().score_rule(rid,SectorRuleInput(raw,DAY),DAY).score is None

def test_s4_touched_or_unverified_limits_cannot_score():
    raw=limit_raw(1);raw['limit_details'][0]['actual_close']=10
    assert SectorHeatEngine().score_rule('S4',SectorRuleInput(raw,DAY),DAY).score is None

def test_s5_insufficient_history_and_s6_missing_day_are_not_zero():
    for rid,key in [('S5','daily_amounts'),('S6','daily_comparisons')]:
        raw=deepcopy(FIXTURE['inputs'][rid]);raw[key].pop()
        assert SectorHeatEngine().score_rule(rid,SectorRuleInput(raw,DAY),DAY).score is None

def test_s7_expected_denominator_not_valid_denominator():
    raw=dict(strong_count=1,expected_count=20,valid_return_count=10,strong_ratio=.05)
    assert SectorHeatEngine().score_rule('S7',SectorRuleInput(raw,DAY),DAY).score==2
    raw['strong_ratio']=.1
    assert SectorHeatEngine().score_rule('S7',SectorRuleInput(raw,DAY),DAY).score is None

def test_readiness_never_integrates_stock_score_and_checks_dates():
    r=SectorHeatEngine().evaluate('C25','fixture',DAY,inputs(),{})
    ok=downstream_readiness(r,primary_sector_id='C25',stock_return_5d=.1,industry_return_5d=.02,return_date=DAY)
    assert ok['B1_READY'] and ok['B2_READY'] and not ok['integrated_into_stock_score']
    bad=downstream_readiness(r,primary_sector_id='other',stock_return_5d=.1,industry_return_5d=.02,return_date=DAY)
    assert not bad['B1_READY'] and not bad['B2_READY']

def test_archive_adapter_round_trip_is_deterministic(tmp_path):
    import pandas as pd
    from app.sector.replay import replay,write_results
    name='C25固定真实存档'
    for rid,original in FIXTURE['inputs'].items():
        raw=deepcopy(original);raw.update(industry=name,trade_date=DAY,status='VALID')
        for key,file in [('limit_details','s4_constituent_details.csv'),('daily_amounts','s5_daily_amounts.csv'),('daily_comparisons','s6_daily_comparisons.csv')]:
            if key in raw:
                rows=raw.pop(key)
                for row in rows:row['industry']=name
                pd.DataFrame(rows).to_csv(tmp_path/file,index=False)
        raw.pop('expected_trade_dates',None)
        pd.DataFrame([raw]).to_csv(tmp_path/(rid.lower()+'_inputs.csv'),index=False)
    a=replay(tmp_path);b=replay(tmp_path)
    assert a[0].to_dict()==b[0].to_dict() and a[0].total_score==25
    write_results(a,tmp_path/'result')
    assert json.loads((tmp_path/'result/sector_heat_details.json').read_text(encoding='utf-8'))[0]['total_score']==25

def test_empty_inputs_have_no_business_total_or_available_max():
    r=SectorHeatEngine().evaluate('x','x',DAY,{},{} )
    assert r.total_score is None and r.available_score==0 and r.available_max_score==0 and r.score_coverage==0

@pytest.mark.parametrize('rid',['S1','S5','S6'])
def test_exact_coverage_threshold_is_eligible(rid):
    raw=deepcopy(FIXTURE['inputs'][rid]);raw['coverage']=.8
    assert SectorHeatEngine().score_rule(rid,SectorRuleInput(raw,DAY),DAY).score is not None
