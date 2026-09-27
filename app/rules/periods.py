"""Completed-period data only. Explicit feeds support exchange holiday calendars."""
import pandas as pd
from app.rules.base import Context,require,UnknownData


def completed_periods(ctx,timeframe):
    if timeframe=='D': return ctx.bars.copy()
    supplied=ctx.metadata.get('period_bars',{}).get(timeframe)
    asof=pd.Timestamp(ctx.as_of) if ctx.as_of else ctx.bars.date.iloc[-1]
    if supplied is not None:
        d=Context(supplied,as_of=str(asof)).prepared().bars
        if 'is_complete' not in d:
            raise UnknownData('显式周/月线必须提供is_complete','AWAITING_PERIOD_CLOSE')
        # date is the period closing date, not its opening date.
        d=d.loc[d.is_complete.eq(True) & (d.date<=asof)].reset_index(drop=True)
        return d
    require(ctx.bars,['close_adj'],1)
    d=ctx.bars.copy(); frequency='W-FRI' if timeframe=='W' else 'M'
    d['_period']=d.date.dt.to_period(frequency)
    rows=[]
    for period,group in d.groupby('_period',sort=True):
        # A calendar end not yet observed is not declared complete. A supplied
        # period feed is required to recognize holiday-shortened closing days.
        if period.end_time.date()>asof.date(): continue
        # A partial first group cannot represent a full week/month.
        if period.start_time.date()<d.date.iloc[0].date(): continue
        row={'date':pd.Timestamp(period.end_time.date()),'close_adj':float(group.close_adj.iloc[-1]),'is_complete':True}
        for field,op in [('open_adj','first'),('high_adj','max'),('low_adj','min'),('volume','sum')]:
            if field in group:
                if group[field].isna().any(): row[field]=float('nan')
                else: row[field]=float(group[field].iloc[0] if op=='first' else getattr(group[field],op)())
        rows.append(row)
    return pd.DataFrame(rows,columns=['date','open_adj','high_adj','low_adj','close_adj','volume','is_complete'])


def peaks(series,side=2,strict=False):
    out=[]
    for i in range(side,len(series)-side):
        value=float(series.iloc[i]); neighbors=list(series.iloc[i-side:i])+list(series.iloc[i+1:i+side+1])
        if all(value>x if strict else value>=x for x in neighbors): out.append(i)
    return out


def close_troughs(series,side=2):
    return peaks(-series,side,strict=True)
