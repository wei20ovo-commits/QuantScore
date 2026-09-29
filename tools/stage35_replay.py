"""Recompute acceptance evidence from this run's saved, real provider responses."""
from pathlib import Path
import sys, json, hashlib
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.data.market_rule import CurrentMarketLimitEngine
from app.sector.market_data import align_bars, _returns, sector_snapshot, s6_daily_comparisons, s7_strong_ratio
from tools.stage35_evidence import money, cash_dividend_reference, ipo_trading_day_count, parse_tencent_quotes, comparison_summary

OUT=ROOT/'outputs/stage35'
def save(name, rows):
    pd.DataFrame(rows).to_csv(OUT/name,index=False)

def main():
    membership=pd.read_csv(OUT/'membership.csv')
    calendar=pd.read_csv(OUT/'raw/calendar.csv')
    basic=pd.read_csv(OUT/'raw/security_metadata.csv').set_index('code')
    benchmark=pd.read_csv(OUT/'raw/benchmark.csv')
    latest=benchmark.date.max()
    days=pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date'])
    days=[d.date() for d in days if str(d.date())>=benchmark.date.min() and str(d.date())<=latest]
    engine=CurrentMarketLimitEngine()
    def resolve(symbol,row):
        meta=basic.loc[symbol[-2:].lower()+'.'+symbol[:6]]
        count=ipo_trading_day_count(calendar,meta.ipoDate,row.date)
        result=engine.resolve_current(trade_date=row.date,symbol=symbol,exchange=symbol[-2:],previous_close=row.preclose,
             ipo_date=meta.ipoDate,trading_days_since_ipo=count,is_st=int(row.isST),high=row.high,close=row.close)
        return dict(symbol=symbol,name=meta.code_name,date=row.date,exchange=symbol[-2:],board=engine.board_for(symbol,symbol[-2:],is_st=bool(row.isST)),
            preclose=row.preclose,isST=int(row.isST),ipoDate=meta.ipoDate,trading_days_since_ipo=count,limit_ratio=result.limit_ratio,
            calculated_limit_up=result.limit_up_price,calculated_limit_down=result.limit_down_price,actual_high=row.high,actual_close=row.close,
            touched_limit_up=result.touched_limit_up,closed_at_limit_up=result.closed_at_limit_up,status=result.status,
            rule_id=result.rule_id,rule_source=result.rule_source,effective_from=result.effective_from,provider='baostock',data_provenance=row.data_provenance)
    quotes=[]
    for stem in ('tencent','tencent_st'):
        source=(OUT/f'samples/{stem}_url.txt').read_text()
        for quote in parse_tencent_quotes((OUT/f'samples/{stem}_quotes.txt').read_bytes(),latest):
            symbol=quote['symbol']; path=OUT/f'samples/{symbol}.csv'
            if not path.exists():path=OUT/f'raw/{symbol}_raw.csv'
            raw=pd.read_csv(path); row=raw.loc[raw.date.eq(latest)].iloc[0]
            r=resolve(symbol,row)
            r.update(independent_source='Tencent public quote',independent_source_id_or_url=source,
                independent_limit_up_price=quote['limit_up'],independent_limit_down_price=quote['limit_down'],
                independent_limit_status='CLOSED_AT_LIMIT_UP' if quote['closed'] else 'NOT_CLOSED_AT_LIMIT_UP',
                independent_name=quote['name'],independent_timestamp=quote['timestamp'],
                price_match=money(r['calculated_limit_up'])==money(quote['limit_up']) and money(r['calculated_limit_down'])==money(quote['limit_down']),
                status_match=r['closed_at_limit_up']==quote['closed'],notes='Direct reported limits (fields 47/48); no independent price reconstruction')
            quotes.append(r)
    # Retain the conflicting discovery source instead of silently dropping it.
    from bs4 import BeautifulSoup
    pool=BeautifulSoup((OUT/'sources/pool.html').read_text(encoding='utf-8'),'html.parser')
    pool_row=next(tr for tr in pool.select('tr') if '600165' in tr.get_text())
    if '3.37' not in pool_row.get_text() or 'ST宁科' not in pool_row.get_text():
        raise ValueError('Saved pool conflict changed; investigate before replay')
    conflict=next(r.copy() for r in quotes if r['symbol']=='600165.SH')
    conflict.update(independent_source='观势公开涨停列表 (conflicting discovery source)',
        independent_source_id_or_url='https://www.lvzen.top/market/limit-up.html',
        independent_limit_up_price=None,independent_limit_down_price=None,
        independent_limit_status='CLOSED_AT_LIMIT_UP',independent_name='ST宁科',independent_timestamp=None,
        price_match=None,status_match=False,resolution_status='RESOLVED_SOURCE_RULE_INCONSISTENT',
        notes='Pool calls 3.37 (+4.98%) limit-up; official current SH main AND MAIN_ST ratio is 10%, upper limit 3.53, corroborated by Tencent field47. Pool does not report a separate limit-price field. Retained mismatch; not qualifying evidence.')
    quotes.append(conflict)
    save('s4_cross_validation_final.csv',quotes)
    summary=comparison_summary(quotes)
    summary['resolved_mismatch_count']=1
    summary['unresolved_mismatch_count']=summary['mismatch_count']-1
    summary['qualifying_sample_count']=len(quotes)-1
    summary['qualifying_positive_count']=sum(r['independent_limit_status']=='CLOSED_AT_LIMIT_UP' for r in quotes[:-1])
    exdiv=[]
    for symbol,day,record,cash in [('603018.SH','2026-09-21','2026-09-18','.04'),('301369.SZ','2026-09-24','2026-09-23','.18')]:
        history=json.loads((OUT/f'sources/tencent_history_{symbol[:6]}.json').read_text())['data'][symbol[-2:].lower()+symbol[:6]]['day']
        prior=next(r for r in history if r[0]==record)
        ref=cash_dividend_reference(prior[2],cash)
        raw=pd.read_csv(OUT/f'samples/{symbol}.csv');r=raw.loc[raw.date.eq(day)].iloc[0]
        urls=json.loads((OUT/f'sources/exdiv_{symbol[:6]}_urls.json').read_text())
        exdiv.append(dict(symbol=symbol,name=basic.loc[symbol[-2:].lower()+'.'+symbol[:6]].code_name,date=day,record_date=record,
            previous_actual_close=float(prior[2]),baostock_previous_actual_close=float(raw.loc[raw.date.eq(record),'close'].iloc[0]),
            announced_cash_per_share=float(cash),baostock_preclose=r.preclose,independent_reference_price=float(ref),
            match=money(r.preclose)==ref,independent_source='Issuer cash-only distribution formula + Tencent unadjusted record-date close',
            announcement_url=urls['announcement'],independent_history_url=urls['history'],method='record_date_close - issuer_announced_cash_per_share; rounded to cent'))
    save('ex_dividend_reference_validation.csv',exdiv)
    tables={f's{i}':[] for i in range(1,8)}; amount_daily=[]; s6_daily=[]; limits=[]; bars_audit=[]
    b=_returns(align_bars(benchmark,trading_days=days)).set_index('date')
    for industry, group in membership.groupby('industry'):
        symbols=group.symbol.tolist();frames=[]
        for symbol in symbols:
            raw=pd.read_csv(OUT/f'raw/{symbol}_raw.csv');adj=pd.read_csv(OUT/f'raw/{symbol}_qfq.csv')
            if not raw.date.equals(adj.date) or raw.date.duplicated().any():raise ValueError(f'Raw/qfq date mismatch: {symbol}')
            frame=adj[['date','symbol','close']].merge(raw[['date','symbol','amount']],on=['date','symbol'],validate='one_to_one')
            frames.append(frame)
            r=resolve(symbol,raw.loc[raw.date.eq(latest)].iloc[0]);r['industry']=industry;limits.append(r)
            bars_audit.append(dict(symbol=symbol,industry=industry,raw_rows=len(raw),qfq_rows=len(adj),latest_date=raw.date.max(),date_aligned=True,
                                   status='VALID' if raw.date.max()==latest else 'DATA_STALE'))
        bars=pd.concat(frames,ignore_index=True)
        aligned=align_bars(bars,symbols=symbols,trading_days=days);returns=_returns(aligned)
        current=returns.loc[returns.date.eq(days[-1])];n=len(symbols)
        snapshot=sector_snapshot(industry,bars,symbols=symbols,trading_days=days)
        def base(valid):
            return dict(industry=industry,trade_date=latest,expected_count=n,valid_count=int(valid),missing_count=n-int(valid),
                        coverage=float(valid/n),status='VALID' if valid==n else 'DATA_INCONSISTENT')
        v1=current.return_1d.notna().sum();v5=current.return_5d.notna().sum()
        tables['s1'].append(dict(**base(v1),sector_return_1d=snapshot.return_1d,benchmark_return_1d=b.iloc[-1].return_1d,sector_excess_return_1d=snapshot.return_1d-b.iloc[-1].return_1d))
        tables['s2'].append(dict(**base(v5),window_start=str(days[-6]),window_end=latest,return_intervals=5,sector_return_5d=snapshot.return_5d,benchmark_return_5d=b.iloc[-1].return_5d,sector_excess_return_5d=snapshot.return_5d-b.iloc[-1].return_5d))
        tables['s3'].append(dict(**base(v1),advancing_constituents=int(current.return_1d.gt(0).sum()),valid_constituents=int(v1),expected_constituents=n,breadth=snapshot.breadth))
        li=[r for r in limits if r['industry']==industry];vl=sum(r['status']=='VALID' and r['closed_at_limit_up'] is not None for r in li);lc=sum(r['closed_at_limit_up'] is True for r in li)
        tables['s4'].append(dict(**base(vl),valid_limit_count=vl,limit_up_count=lc,limit_up_ratio=lc/n,definition='close_raw >= verified limit_up_price'))
        for day in days[-21:]:
            amounts=aligned.loc[aligned.date.eq(day),'amount'];valid=amounts.notna().sum()
            amount_daily.append(dict(industry=industry,date=str(day),expected_members=n,valid_amount_members=int(valid),sector_amount=float(amounts.sum()) if valid==n else None,coverage=float(valid/n),status='VALID' if valid==n else 'DATA_INCONSISTENT'))
        ad=[r for r in amount_daily if r['industry']==industry];av=min(r['valid_amount_members'] for r in ad)
        tables['s5'].append(dict(**base(av),sector_amount_today=snapshot.amount,sector_amount_prior_20d_mean=snapshot.amount_20d_mean,amount_ratio=snapshot.amount_20d_ratio,prior_window_start=str(days[-21]),prior_window_end=str(days[-2]),prior_trading_days=20))
        for day in days[-5:]:
            r=returns.loc[returns.date.eq(day),'return_1d'];valid=r.notna().sum();br=b.loc[day,'return_1d'];sr=float(r.mean()) if valid==n else None
            s6_daily.append(dict(industry=industry,date=str(day),sector_return=sr,benchmark_return=br,sector_win=sr>br if sr is not None else None,expected_count=n,valid_count=int(valid),coverage=float(valid/n),status='VALID' if valid==n and pd.notna(br) else 'DATA_INCONSISTENT'))
        six=s6_daily_comparisons(bars,benchmark,trading_days=days,expected_constituents=symbols)
        sv=min(r['valid_count'] for r in s6_daily if r['industry']==industry)
        s6row=dict(**base(sv),win_count=six.value,observed_days=5);s6row['status']=six.status.value;tables['s6'].append(s6row)
        seven=s7_strong_ratio(bars,expected_constituents=symbols,trading_days=days)
        tables['s7'].append(dict(**base(v1),valid_return_count=int(v1),strong_count=int(current.return_1d.ge(.05).sum()),strong_ratio=seven.value,threshold=.05,denominator='expected_constituent_list'))
    for name,rows in tables.items():save(name+'_inputs.csv',rows)
    save('s5_daily_amounts.csv',amount_daily);save('s6_daily_comparisons.csv',s6_daily);save('s4_constituent_details.csv',limits);save('bar_alignment.csv',bars_audit)
    fm=json.loads((OUT/'fetch_metadata.json').read_text())
    metadata=dict(generated_at=datetime.now(timezone.utc).isoformat(),source_retrieved_at=fm['retrieved_at'],
        snapshot_note='Latest completed session at real collection on 2026-09-29 morning Asia/Shanghai; replay time is not a new market request',
        latest_trade_date=latest,industry_count=fm['industry_count'],
        selected_industry_count=3,expected_constituents=len(membership),valid_constituents=sum(r['status']=='VALID' for r in bars_audit),
        bar_expected=len(membership),bar_valid=sum(r['status']=='VALID' for r in bars_audit),bar_failure=sum(r['status']!='VALID' for r in bars_audit),
        s4_sample_count=summary['sample_count'],s4_price_match=summary['price_match_count'],s4_status_match=summary['status_match_count'],s4_mismatch=summary['mismatch_count'],
        s4_comparison_summary=summary,ex_dividend_samples=len(exdiv),ex_dividend_matches=sum(r['match'] for r in exdiv),
        return_price_basis='qfq close, aligned to BaoStock trading calendar',limit_price_basis='raw preclose, not yesterday raw close',
        universe='SH/SZ',BJ='OUT_OF_SCOPE_FOR_V1',sector_scoring='NOT_STARTED',pytest='PENDING',stage3a_status='PENDING_TESTS')
    for name,rows in tables.items():metadata[name+'_valid_industries']=sum(r['status']=='VALID' for r in rows)
    (OUT/'run_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    hashes={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['raw','samples','sources'] for p in (OUT/folder).iterdir() if p.is_file()}
    (OUT/'source_hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
