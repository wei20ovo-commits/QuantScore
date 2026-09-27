"""Synthetic OHLCV is used only as deterministic test data, never market data."""
import numpy as np
import pandas as pd
import pytest
from app.engine.rule_engine import RuleEngine
from app.rules.base import Context


def bars(closes,volumes=None):
    c=np.asarray(closes,dtype=float); n=len(c)
    d=pd.DataFrame({'date':pd.bdate_range('2024-01-02',periods=n),
                    'open_adj':c,'high_adj':c+0.1,'low_adj':c-0.1,'close_adj':c,
                    'volume':np.ones(n)*100 if volumes is None else volumes,
                    'turnover_rate':np.ones(n)*5})
    for name in ('open','high','low','close'): d[name+'_raw']=d[name+'_adj']
    # This is a supplied fixture field, NOT a production fixed-limit calculator.
    d['limit_up_price']=np.r_[c[0],c[:-1]]*1.1
    return d


def double_top(state='CANDIDATE'):
    c=list(np.r_[np.linspace(10,13,100),np.linspace(13.1,19.3,30)])
    c += [19.6,19.3,18.8,18.2,17.5,17.2,17.6,18.3,19.0,19.3,19.6,19.65,19.65]
    d=bars(c)
    d.loc[130,'high_adj']=20
    d.loc[140,'high_adj']=19.8
    d.loc[135,'low_adj']=17
    if state=='FORMED':
        d.loc[141,['open_adj','high_adj','low_adj','close_adj']]=[18.9,19.0,18.8,18.9]
        d.loc[142,['open_adj','high_adj','low_adj','close_adj']]=[18.8,18.9,18.7,18.8]
    elif state=='CONFIRMED':
        d.loc[141,['open_adj','high_adj','low_adj','close_adj']]=[16.8,16.9,16.7,16.8]
        d.loc[142,['open_adj','high_adj','low_adj','close_adj']]=[16.7,16.8,16.6,16.7]
    elif state=='INVALIDATED':
        extension=bars([20.8,20.9]); extension['date']=pd.bdate_range(d.date.iloc[-1]+pd.Timedelta(days=1),periods=2)
        d=pd.concat([d,extension],ignore_index=True)
    return d


def n_board(broken=False,confirmed=False):
    d=bars([10]*120+[11,11.05,11.1]+([11.4] if confirmed else []))
    d.loc[120,'volume']=130
    if confirmed: d.loc[123,'volume']=150
    if broken: d.loc[121,'low_adj']=9.9
    return d


@pytest.fixture
def engine(): return RuleEngine()


def evaluate(engine,rid,d,**metadata):
    return engine.evaluate(rid,Context(d,metadata=metadata))
