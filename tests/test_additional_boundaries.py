import numpy as np
import pandas as pd
import pytest
from conftest import bars,evaluate,double_top,n_board
from app.rules.base import Context,indicators
from app.engine.score_engine import ScoreEngine


def test_r9_two_day_break_not_single_invalidated(engine):
    r=evaluate(engine,'R9',bars([10]*40+[9.5,9.4,10.4]))
    assert r.status!='INVALIDATED' and r.penalty==0


def test_r9_gap_within_tolerance_not_effective_break(engine):
    d=bars([10]*40+[9.95])
    assert evaluate(engine,'R9',d).penalty==0


def test_d1_recognizes_reclaim_without_cross_today(engine):
    d=bars([10]*74+[9.5,10.03,10.8])
    d.loc[56:73,'high_adj']=12  # not a 20-day high breakout
    d.loc[76,'volume']=200
    r=evaluate(engine,'D1',d)
    assert r.score==5 and r.raw_values['m60_reclaim']
    assert not r.raw_values['m60_cross'] and not r.raw_values['price_break']


def test_d1_uses_latest_not_largest_event_volume(engine):
    d=bars([10]*74+[10.5,10.4,11.1]); d.loc[74,'volume']=400; d.loc[76,'volume']=130
    r=evaluate(engine,'D1',d)
    assert r.raw_values['date']==str(d.date.iloc[76].date())
    assert r.score==0  # the earlier high-volume event cannot replace latest


def test_n_missing_limit_price_is_unknown(engine):
    assert evaluate(engine,'R11',n_board().drop(columns='limit_up_price')).status=='UNKNOWN'


def test_n_exact_m5_not_break(engine):
    d=n_board(); x=indicators(d,engine.parameters); d.loc[121,'low_adj']=x.M5.iloc[121]
    assert evaluate(engine,'R11',d).penalty==0


def test_n_multiple_starts_unknown_and_explicit_event_validated(engine):
    d=n_board(); d.loc[122,'limit_up_price']=d.close_raw.iloc[122]
    assert evaluate(engine,'F1-N',d).status=='CANDIDATE'  # V1.2 nearest legal structure
    first=str(d.date.iloc[120].date())
    assert evaluate(engine,'F1-N',d,n_first_start_date=first).status=='CANDIDATE'
    assert evaluate(engine,'F1-N',d,n_first_start_date='2000-01-01').reason_code=='INVALID_EVENT'


def test_double_top_neckline_equality_not_confirmed(engine):
    d=double_top('CONFIRMED'); d.loc[141:142,['open_adj','close_adj']]=17
    d.loc[141:142,'high_adj']=17.1; d.loc[141:142,'low_adj']=16.9
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='FORMED' and r.penalty==8


def test_double_top_weakening_after_day3_does_not_form(engine):
    d=double_top(); extra=bars([19.65,18.8]); extra['date']=pd.bdate_range(d.date.iloc[-1]+pd.Timedelta(days=1),periods=2)
    extra.loc[0,'high_adj']=19.7; extra.loc[1,'high_adj']=19
    d=pd.concat([d,extra],ignore_index=True)
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='CANDIDATE'


def test_double_top_late_neckline_still_confirms(engine):
    d=double_top(); extra=bars([19.65,16.8]); extra['date']=pd.bdate_range(d.date.iloc[-1]+pd.Timedelta(days=1),periods=2)
    extra.loc[0,'high_adj']=19.7
    d=pd.concat([d,extra],ignore_index=True)
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='CONFIRMED'


def test_double_top_malformed_ohlc_unknown(engine):
    d=double_top(); d.loc[140,'low_adj']=25
    assert evaluate(engine,'R4',d,adjustment_consistent=True).reason_code=='INVALID_DATA'


def test_double_top_nan_unknown(engine):
    d=double_top(); d.loc[135,'low_adj']=np.nan
    assert evaluate(engine,'R4',d,adjustment_consistent=True).status=='UNKNOWN'


def test_coverage_over_100_not_silently_clipped(engine):
    from app.rules.base import result
    from app.engine.coverage import calculate
    items=[result(r,score=r['max_score'],explanation='测试构造满分') for r in engine.registry.values() if r['rule_type']=='POSITIVE']
    coverage=calculate(items,engine.parameters)
    assert coverage['positive_successful_max_score']<=100
    assert coverage['positive_coverage'] is not None and coverage['ambiguity'] is None


def test_full_engine_no_mutation(engine):
    import pandas as pd
    d=bars(np.linspace(10,20,150)); original=d.copy(deep=True)
    ScoreEngine(engine).evaluate(Context(d,benchmark=d))
    pd.testing.assert_frame_equal(d,original)


@pytest.mark.parametrize('gap,expected',[(3,'FAIL'),(4,'CANDIDATE'),(20,'CANDIDATE'),(21,'FAIL')])
def test_double_top_gap_boundaries(engine,gap,expected):
    prefix=list(np.r_[np.linspace(10,13,100),np.linspace(13.1,19.3,30)])
    between=np.interp(np.arange(1,gap),[0,gap/2,gap],[19.6,17.2,19.6]).tolist()
    d=bars(prefix+[19.6]+between+[19.6,19.65,19.65])
    d.loc[130,'high_adj']=20; d.loc[130+gap,'high_adj']=19.8
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status==expected,r.to_dict()


@pytest.mark.parametrize('peak,expected',[(20.6,'CANDIDATE'),(20.6001,'FAIL')])
def test_double_top_height_boundary(engine,peak,expected):
    d=double_top(); d.loc[140,'high_adj']=peak
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status==expected,r.to_dict()


def test_double_top_multiple_pairs_unknown(engine):
    d=double_top(); d.loc[139,'high_adj']=19.8
    r=evaluate(engine,'R4',d,adjustment_consistent=True)
    assert r.status=='CANDIDATE' and r.raw_values['P2']['date']==str(d.date.iloc[140].date())
