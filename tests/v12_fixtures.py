import numpy as np
import pandas as pd
from conftest import bars
from app.rules.base import Context


def platform_bars(broken=False):
    d=bars([10]*70+[10.02]*5)
    if broken: d.loc[72,'close_adj']=9.8; d.loc[72,'low_adj']=9.7
    return d


def belt_context(broken=False,intraday=False):
    d=bars([10,9.5,9,9.5,10,10.2,9.9,9.5,9.9,10.3,10.8,11])
    if broken: d.loc[11,['open_adj','high_adj','low_adj','close_adj']]=[9.8,9.9,9.7,9.8]
    if intraday: d.loc[11,'low_adj']=8
    w=d.copy(); m=d.copy()
    w['date']=pd.date_range('2023-01-06',periods=len(d),freq='W-FRI'); w['is_complete']=True
    m['date']=pd.date_range('2022-01-31',periods=len(d),freq='ME'); m['is_complete']=True
    return Context(d,metadata={'period_bars':{'W':w,'M':m}})


def small_bulls(exception=False,big=False,transition=False):
    c=[10]*140
    for _ in range(7): c.append(c[-1]*1.01)
    d=bars(c)
    # Broad prior range makes the latest run genuinely low in 120-day space.
    d.loc[30:80,'high_adj']=20
    d.loc[140:146,'open_adj']=d.close_adj.shift(1).iloc[140:147].values
    if exception:
        d.loc[143,'close_adj']=d.close_adj.iloc[142]*0.995
        for i in range(144,147): d.loc[i,'close_adj']=d.close_adj.iloc[i-1]*1.01
        d.loc[140:146,'open_adj']=d.close_adj.shift(1).iloc[140:147].values
    if big: d.loc[146,'close_adj']=d.close_adj.iloc[145]*1.06
    if transition: d.loc[146,'close_adj']=d.close_adj.iloc[145]*1.045
    d['high_adj']=np.maximum(d.high_adj,np.maximum(d.open_adj,d.close_adj)+0.1)
    d['low_adj']=np.minimum(d.low_adj,np.minimum(d.open_adj,d.close_adj)-0.1)
    return d


def weekly_reversal():
    highs=list(np.linspace(12,19,10))+[20,19,18]+list(np.linspace(16,12,12))
    w=bars(np.asarray(highs)-0.4); w['high_adj']=highs; w['low_adj']=w.close_adj-0.3
    w.loc[24,['close_adj','low_adj']]=[11,10]
    w['date']=pd.date_range('2023-01-06',periods=25,freq='W-FRI'); w['is_complete']=True
    w.loc[10,'volume']=400; w.loc[12,'volume']=1000; w.loc[23,'volume']=1200; w.loc[24,'volume']=1100
    return Context(bars([10]*150),metadata={'period_bars':{'W':w}})


def damping():
    changes=[0.01,-0.01,0.04,-0.04,0.02,-0.02,0.03,-0.03]
    c=[10]
    for r in changes: c.append(c[-1]*(1+r))
    return bars(c,[100]+[150 if r>0 else 100 for r in changes])


def t_board(open_price=10.2,low=10.7):
    d=bars([10]*149+[11]); d.loc[149,['open_raw','high_raw','low_raw','close_raw','limit_up_price']]=[open_price,11,low,11,11]
    # When open is lower than the requested low, preserve valid OHLC.
    d.loc[149,'low_raw']=min(open_price,low)
    return d


def one_word(turn=5,pre_expansion=False):
    d=bars([12]*130+[10]*19+[11]); d.loc[149,['open_raw','high_raw','low_raw','close_raw','limit_up_price']]=11
    d.loc[149,'turnover_rate']=turn
    if pre_expansion: d.loc[146:148,'volume']=300
    return d


def refuel(length=2,broken=False,confirm=True):
    prefix=list(np.linspace(10,15,120)); c=prefix+[16.5]+[16.55]*length+([17.0] if confirm else [])
    d=bars(c); j=120
    d.loc[j,'limit_up_price']=16.5; d.loc[j,'volume']=100
    for k in range(j+1,j+length+1):
        d.loc[k,'volume']=150; d.loc[k,'low_adj']=16.55
    if broken: d.loc[j+min(2,length),'low_adj']=14
    return d


def dragon():
    # Two descending confirmed highs extrapolate to M60's neighborhood.
    d=bars([10]*140+[11,9,10.7,10.8,10.9])
    d.loc[128,'high_adj']=10.36; d.loc[134,'high_adj']=10.24
    d.loc[140,['open_adj','high_adj','low_adj','close_adj','close_raw','limit_up_price']]=[10,11.1,9.9,11,11,11]
    d.loc[140,'volume']=100
    d.loc[141,['open_raw','high_raw','low_raw','close_raw','limit_up_price','limit_down_price']]=[12.1,12.1,9.9,9.9,12.1,9.9]
    # Adjusted body is consistent in ratio with the raw fake-fall day.
    d.loc[141,['open_adj','high_adj','low_adj','close_adj']]=[11,11,9,9]
    d.loc[141,'volume']=400
    d['limit_down_price']=d.get('limit_down_price',d.close_raw*0.9).fillna(d.close_raw*0.9)
    return d


def leader_context(broken=True):
    members={str(i):bars([10]*30) for i in range(10)}
    target=members['0']; target.loc[23,'limit_up_price']=target.close_raw.iloc[23]
    target.loc[24:,'low_adj']=10
    if broken: target.loc[25,'low_adj']=9.5
    return Context(target,metadata={'stock_id':'0','sector_bars':members})
