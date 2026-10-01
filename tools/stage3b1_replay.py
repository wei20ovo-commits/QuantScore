"""Offline archived real-data replay; never overwrites Stage35 or Stage3B evidence."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.sector.replay import replay,load_archive
from app.data.validators import DataValidator
from app.rules.base import Context
from app.engine.rule_engine import RuleEngine
from app.engine.score_engine import ScoreEngine

def archive_contexts():
    path=ROOT/'outputs/stage35';members=pd.read_csv(path/'membership.csv')
    heat={r.sector_id:r.to_dict() for r in replay(path)}
    sources={sid:(name,day,inp) for sid,name,day,inp in load_archive(path)}
    cal=pd.read_csv(path/'raw/calendar.csv');engine=RuleEngine();rows=[]
    for sid in ['C25','C18','H61']:
        name,day,inputs=sources[sid];symbol=members.loc[members.industry.eq(name),'symbol'].iloc[0]
        raw=pd.read_csv(path/f'raw/{symbol}_raw.csv');adj=pd.read_csv(path/f'raw/{symbol}_qfq.csv')
        bars=DataValidator.align_raw_qfq(raw,adj)
        days=cal.loc[cal.is_trading_day.eq(1)&cal.calendar_date.le(day),'calendar_date'].tail(6).tolist()
        provenance=dict(provider='baostock',as_of=day,source='Stage35 archived-current-snapshot',symbol=symbol)
        data=dict(data_status='VALID',primary_industry=dict(symbol=symbol,sector_id=sid,name=name,provider='baostock',as_of=day,provenance=provenance),
            sector_heat=heat[sid],returns=dict(sector_return_5d=inputs['S2'].raw_inputs['sector_return_5d'],window_start=days[0],window_end=days[-1],trade_dates=days,adjustment_type='qfq',data_status='VALID'),provenance=provenance)
        ctx=Context(bars,metadata=dict(symbol=symbol,adjustment_type='qfq',adjustment_consistent=True,industry_context=data))
        rows.append((symbol,ctx,engine.evaluate('B1',ctx),engine.evaluate('B2',ctx)))
    return rows

def main():
    out=ROOT/'outputs/stage3b1';out.mkdir(parents=True,exist_ok=True)
    data=archive_contexts();engine=ScoreEngine();b1=[];b2=[];integration=[];details=[]
    for symbol,ctx,a,b in data:
        b1.append(dict(symbol=symbol,**a.raw_values,score=a.score,status=a.status,reason=a.reason_code))
        raw=b.raw_values;stock=ctx.bars.close_adj
        manual=float(stock.iloc[-1]/stock.iloc[-6]-1)-raw['sector_return_5d']
        b2.append(dict(symbol=symbol,**raw,score=b.score,status=b.status,manual_relative_return=manual,manual_match=abs(manual-raw['relative_return_5d'])<1e-12))
        total=engine.evaluate(ctx);dup=engine.aggregate([a,b,a,b])
        integration.append(dict(symbol=symbol,quant_score=total['quant_score'],B1_count=sum(r['rule_id']=='B1' for r in total['rules']),B2_count=sum(r['rule_id']=='B2' for r in total['rules']),dedup_B_score=dup['category_scores']['B']))
        details.append(dict(symbol=symbol,B1=a.to_dict(),B2=b.to_dict()))
    pd.DataFrame(b1).to_csv(out/'b1_replay.csv',index=False);pd.DataFrame(b2).to_csv(out/'b2_replay.csv',index=False)
    pd.DataFrame(integration).to_csv(out/'single_stock_integration.csv',index=False)
    (out/'replay_details.json').write_text(json.dumps(details,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    assert data[-1][2].score is None and all(r['manual_match'] for r in b2)
    print([(s,a.score,a.status,b.score,b.status) for s,c,a,b in data])

if __name__=='__main__':main()
