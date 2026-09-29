"""Offline boundaries. Synthetic fixtures are tests, never live acceptance evidence."""
from datetime import date
from decimal import Decimal
import pandas as pd
import pytest
from app.data.market_rule import CurrentMarketLimitEngine
from app.sector.market_data import align_bars, sector_snapshot, s6_daily_comparisons, s7_strong_ratio
from tools.stage35_evidence import S4_FIELDS, cash_dividend_reference, ipo_trading_day_count, parse_tencent_quotes, comparison_summary

def resolve(**kwargs):
    args=dict(trade_date='2026-09-24',symbol='600000.SH',exchange='SH',previous_close=10,
              ipo_date='2026-09-17',trading_days_since_ipo=6,high=11,close=11)
    args.update(kwargs)
    return CurrentMarketLimitEngine().resolve_current(**args)

@pytest.mark.parametrize('symbol,exchange,ratio',[('600000.SH','SH',.1),('000001.SZ','SZ',.1),('300750.SZ','SZ',.2),('301190.SZ','SZ',.2),('688244.SH','SH',.2)])
@pytest.mark.parametrize('day',[1,2,3,4,5,6])
def test_official_first_five_sessions_and_sixth_boundary(symbol,exchange,ratio,day):
    r=resolve(symbol=symbol,exchange=exchange,trading_days_since_ipo=day)
    assert r.effective_from=='2026-07-06'
    assert r.rule_source.startswith('https://www.')
    if day<=5:
        assert r.status=='NOT_APPLICABLE' and r.limit_up_price is None
    else:
        assert r.status=='VALID' and r.limit_ratio==ratio

@pytest.mark.parametrize('exchange,symbol',[('SH','600107.SH'),('SZ','002193.SZ')])
def test_current_main_st_uses_official_ten_percent(exchange,symbol):
    assert resolve(exchange=exchange,symbol=symbol,is_st=True).limit_up_price==11

@pytest.mark.parametrize('updates',[{'trading_days_since_ipo':None},{'trading_days_since_ipo':0},{'trading_days_since_ipo':-1},{'trading_days_since_ipo':2.5},{'trade_date':'2026-07-05'},{'is_st':float('nan')}])
def test_incomplete_or_historical_current_metadata_is_not_verified(updates):
    assert resolve(**updates).status!='VALID'

def test_ipo_calendar_includes_listing_day_and_excludes_holiday():
    c=pd.DataFrame({'calendar_date':['2026-09-24','2026-09-25','2026-09-26','2026-09-27','2026-09-28'], 'is_trading_day':[1,0,0,0,1]})
    assert ipo_trading_day_count(c,'2026-09-24','2026-09-28')==2
    with pytest.raises(ValueError):ipo_trading_day_count(c,'2026-09-23','2026-09-28')

@pytest.mark.parametrize('previous,cash,reference',[('5.17','.04','5.13'),('155.59','.18','155.41')])
def test_ex_dividend_reference_is_not_yesterdays_actual_close(previous,cash,reference):
    ref=cash_dividend_reference(previous,cash)
    assert ref==Decimal(reference) and ref!=Decimal(previous)
    assert resolve(previous_close=ref).limit_up_price!=resolve(previous_close=previous).limit_up_price

def quote(close='11',up='11',timestamp='20260924160000'):
    f=['']*49
    for i,v in {1:'测试',2:'600000',3:close,4:'10',30:timestamp,33:'11',47:up,48:'9'}.items():f[i]=v
    return 'v_sh600000="'+'~'.join(f)+'";'

@pytest.mark.parametrize('close,closed',[('11',True),('10.9',False)])
def test_independent_positive_and_negative(close,closed):
    r=parse_tencent_quotes(quote(close), '2026-09-24')[0]
    assert r['closed']==closed and r['limit_up']==11
    assert resolve(close=close).closed_at_limit_up==closed

def test_parser_reads_reported_price_not_local_ratio_formula():
    assert parse_tencent_quotes(quote(up='12'),'2026-09-24')[0]['limit_up']==12

@pytest.mark.parametrize('payload',[quote(timestamp='20260923160000'),quote(timestamp='20260924143000'),'v_sh600000="short";',quote().replace('~600000~','~000001~')])
def test_parser_rejects_stale_intraday_or_malformed(payload):
    with pytest.raises(ValueError):parse_tencent_quotes(payload,'2026-09-24')

def test_mismatch_and_missing_comparison_cannot_silently_pass():
    row=dict.fromkeys(S4_FIELDS)
    row.update(price_match=True,status_match=False,independent_limit_status='NOT_CLOSED_AT_LIMIT_UP')
    assert comparison_summary([row])['mismatch_count']==1
    assert comparison_summary([row])['comparison_status']=='PARTIAL'
    row.update(status_match=True,price_match=None)
    assert comparison_summary([row])['comparison_status']=='PARTIAL'
    with pytest.raises(ValueError):comparison_summary([{'price_match':True}])

def bars(n=63,periods=25):
    days=pd.bdate_range('2026-08-03',periods=periods)
    return pd.DataFrame([dict(symbol=f'{i:06d}.SZ',date=d,close=100+j,amount=1000) for i in range(n) for j,d in enumerate(days)]), [d.date() for d in days]

def test_full_63_expected_inputs_calendar_s1_s2_s3_s5_s6_s7():
    frame,days=bars();symbols=list(frame.symbol.unique());benchmark=frame[frame.symbol.eq(symbols[0])].copy()
    aligned=align_bars(frame,symbols=symbols,trading_days=days)
    assert len(aligned)==63*25
    snap=sector_snapshot('fixture',frame,symbols=symbols,trading_days=days)
    assert snap.quality.value==63 and snap.quality.status.value=='VALID'
    assert snap.return_1d==pytest.approx(124/123-1)
    assert snap.return_5d==pytest.approx(124/119-1)
    assert snap.breadth==1 and snap.amount==63000 and snap.amount_20d_ratio==1
    assert s6_daily_comparisons(frame,benchmark,trading_days=days,expected_constituents=symbols).value==0
    assert s7_strong_ratio(frame,expected_constituents=symbols,trading_days=days).value==0
    assert sum(resolve(symbol=s,exchange='SZ').status=='VALID' for s in symbols)==63

def test_missing_session_does_not_turn_row_lag_into_five_trading_days():
    frame,days=bars(n=1,periods=7)
    frame=frame.loc[frame.date.ne(pd.Timestamp(days[-2]))]
    snap=sector_snapshot('fixture',frame,trading_days=days)
    assert snap.return_1d is None
    assert snap.return_5d==pytest.approx(106/101-1)

def test_s6_does_not_replace_missing_recent_day_with_older_day():
    frame,days=bars(n=2,periods=10);benchmark=frame[frame.symbol.eq('000000.SZ')].copy()
    frame.loc[frame.date.eq(pd.Timestamp(days[-2])),'close']=float('nan')
    assert s6_daily_comparisons(frame,benchmark,trading_days=days).status.value=='DATA_INCONSISTENT'

def test_s7_keeps_expected_denominator_when_one_member_missing():
    frame,days=bars(n=1,periods=2);frame.loc[1,'close']=110
    r=s7_strong_ratio(frame,expected_constituents=['000000.SZ','000001.SZ'],trading_days=days)
    assert r.value==.5 and r.status.value=='DATA_INCONSISTENT'

def test_s5_missing_historical_amount_never_becomes_complete_mean():
    frame,days=bars(n=2);frame.loc[1,'amount']=float('nan')
    # Make the missing value fall inside the prior twenty-session window.
    frame.loc[frame.date.eq(pd.Timestamp(days[-3])),'amount']=float('nan')
    assert sector_snapshot('fixture',frame,trading_days=days).amount_20d_mean is None

def test_s4_close_required_even_when_high_touches_limit():
    r=resolve(high=11,close=10.5)
    assert r.touched_limit_up is True and r.closed_at_limit_up is False
