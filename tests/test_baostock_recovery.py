"""Regression for reproduced receive errors and overlapping live sessions."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading,time
import pytest
from app.data.baostock_provider import BaoStockProvider,query_session
from app.data.models import ProviderError

def test_sdk_error_message_and_request_are_preserved():
    class Client:
        def login(self):return SimpleNamespace(error_code='0')
        def query(self,**kwargs):return SimpleNamespace(error_code='10002007',error_msg='网络接收错误。')
        def logout(self):self.closed=True
    c=Client()
    with pytest.raises(ProviderError) as caught:query_session(c,'query',{'code':'sh.600519'})
    assert all(x in str(caught.value) for x in ['10002007','网络接收错误。','sh.600519'])
    assert c.closed

def test_separate_provider_instances_cannot_overlap_live_sessions(monkeypatch):
    active=0;peak=0;starts=[];lock=threading.Lock()
    def request(self,method,**kwargs):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active);starts.append(time.monotonic())
        time.sleep(.01)
        with lock:active-=1
        return 'ok'
    monkeypatch.setattr(BaoStockProvider,'_call_once',request)
    with ThreadPoolExecutor(max_workers=3) as pool:
        values=list(pool.map(lambda i:BaoStockProvider()._call('query'),range(3)))
    assert values==['ok']*3 and peak==1
    assert all(b-a>=.29 for a,b in zip(starts,starts[1:]))


def test_long_history_field_groups_preserve_window_and_adjustment():
    import pandas as pd
    calls=[]
    class Source(BaoStockProvider):
        def _call(self,method,**kwargs):
            calls.append(kwargs)
            values=dict(date='2026-09-30',code='sh.600519',open='10',high='11',low='9',close='10',preclose='9.9',pctChg='1',volume='1000',amount='10000',adjustflag=kwargs['adjustflag'],turn='2',tradestatus='1',isST='0')
            return pd.DataFrame([{k:values[k] for k in kwargs['fields'].split(',')}])
    frame=Source().fetch_stock_daily('600519.SH','2000-01-01','2026-09-30','qfq')
    assert len(calls)==4 and all(len(c['fields'].split(','))<=5 for c in calls)
    assert all(c['start_date']=='2000-01-01' and c['end_date']=='2026-09-30' and c['adjustflag']=='2' for c in calls)
    assert frame.close.iloc[0]==10 and frame.volume.iloc[0]==1000


def test_field_group_date_mismatch_never_fills_or_drops_rows():
    import pandas as pd
    from app.data.models import DataError
    class Source(BaoStockProvider):
        def _call(self,method,**kwargs):
            fields=kwargs['fields'].split(',')
            return pd.DataFrame([{k:('2026-09-30' if 'open' in fields else '2026-09-29') if k=='date' else 'sh.600519' if k=='code' else '10' for k in fields}])
    with pytest.raises(DataError,match='inconsistent dates'):
        Source().fetch_stock_daily('600519.SH','2000-01-01','2026-09-30','raw')
