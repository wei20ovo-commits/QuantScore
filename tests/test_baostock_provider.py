"""Artificial SDK fixtures for offline regression; real evidence is separate."""
from types import SimpleNamespace
import pandas as pd
import pytest
from app.data.baostock_provider import BaoStockProvider
from app.data.models import DataError, ProviderError, Security
from app.data.provider_manager import ProviderManager
from app.data.cache import DataCache
from app.data.validators import DataValidator
from test_stage2_data import provider


class Result:
    def __init__(self, fields, rows, error='0'):
        self.fields, self.rows, self.error_code = fields, iter(rows), error
    def next(self):
        self.row = next(self.rows, None)
        return self.row is not None
    def get_row_data(self):
        return self.row


class SDK:
    def __init__(self):
        self.logouts = 0
        self.login_error = '0'
        self.query_error = '0'
        self.blank_turn = False
        self.calls = []
    def login(self):
        print('login success!')
        return SimpleNamespace(error_code=self.login_error)
    def logout(self):
        self.logouts += 1
    def query_history_k_data_plus(self, **kwargs):
        self.calls.append(kwargs)
        values = dict(date='2024-01-02',code=kwargs['code'],open='10',high='11',low='9',close='10',
                      preclose='9.9',volume='12345',amount='123450',adjustflag=kwargs['adjustflag'],
                      turn='' if self.blank_turn else '5.1',tradestatus='1',isST='0')
        fields = kwargs['fields'].split(',')
        return Result(fields, [[values[k] for k in fields]], self.query_error)
    def query_stock_basic(self):
        return Result(['code','code_name','ipoDate','type'],
                      [['sh.600519','测试沪股','2001-08-27','1'],['sz.000001','测试深股','1991-04-03','1'],
                       ['sh.000001','测试指数','1991-07-15','2']])


@pytest.mark.parametrize('symbol,code', [('600519.SH','sh.600519'),('000001.SZ','sz.000001'),('000001.SH','sh.000001')])
def test_mapping(symbol, code):
    assert BaoStockProvider.source_code(symbol) == code

@pytest.mark.parametrize('adjustment,flag',[('raw','3'),('qfq','2')])
def test_fields_units_and_logout(adjustment,flag,capsys):
    sdk=SDK(); p=BaoStockProvider(sdk)
    d=p.fetch_stock_daily('600519.SH','2024-01-01','2024-01-03',adjustment)
    assert sdk.calls[0]['adjustflag']==flag
    assert d.volume.iloc[0]==12345 and d.turnover_rate.iloc[0]==5.1
    assert d.preclose.iloc[0]==9.9 and d.isST.iloc[0]==0 and d.tradestatus.iloc[0]==1
    assert d.provider.iloc[0]=='baostock' and flag in d.data_provenance.iloc[0]
    assert sdk.logouts==1 and capsys.readouterr().out==''

@pytest.mark.parametrize('kind',['login','query','exception'])
def test_logout_after_failure(kind):
    sdk=SDK()
    if kind=='login': sdk.login_error='1'
    if kind=='query': sdk.query_error='1'
    if kind=='exception':
        def fail(**kwargs): raise RuntimeError('fixture')
        sdk.query_history_k_data_plus=fail
    with pytest.raises((ProviderError,RuntimeError)):
        BaoStockProvider(sdk).fetch_stock_daily('600519.SH','2024-01-01','2024-01-03')
    assert sdk.logouts==1

def test_missing_turnover_not_fabricated():
    sdk=SDK();sdk.blank_turn=True
    d=BaoStockProvider(sdk).fetch_stock_daily('600519.SH','2024-01-01','2024-01-03')
    assert pd.isna(d.turnover_rate.iloc[0])

def test_index_fields_and_stock_list_are_distinct():
    sdk=SDK();p=BaoStockProvider(sdk)
    d=p.fetch_benchmark('2024-01-01','2024-01-03')
    assert sdk.calls[0]['code']=='sh.000001' and sdk.calls[0]['adjustflag']=='3'
    assert 'turnover_rate' not in d and 'isST' not in d
    assert set(p.list_securities().canonical_symbol)=={'600519.SH','000001.SZ'}

def test_raw_qfq_strict_date_alignment():
    p=BaoStockProvider(SDK());a=p.fetch_stock_daily('600519.SH','2024-01-01','2024-01-03')
    b=a.copy();b['date']=pd.to_datetime(['2024-01-03'])
    with pytest.raises(DataError): DataValidator.align_raw_qfq(a,b)


class Broken:
    name='broken';is_mock=True
    def list_securities(self): raise ProviderError('fixture list outage')
    def fetch_stock_daily(self,*args): raise RuntimeError('fixture SDK outage')

def test_fallback_security_list_data_and_provenance(provider,tmp_path):
    manager=ProviderManager(providers=[Broken(),provider],cache=DataCache(tmp_path/'c.sqlite'),retries=1)
    data=manager.fetch('600519')
    assert data.metadata['provider']=='mock'
    assert [x['status'] for x in data.metadata['provider_attempts']]==['FAILED','SUCCESS']
    assert all(x['provider']=='mock' for x in data.metadata['data_provenance'])
    assert data.bars.limit_up_price.isna().all()

def test_qfq_failure_restarts_whole_pair(provider,tmp_path):
    class Half(Broken):
        name='half'
        def fetch_stock_daily(self,*args):
            if args[-1]=='qfq':raise ProviderError('qfq outage')
            return provider.raw.assign(close=11)
    manager=ProviderManager(providers=[Half(),provider],cache=DataCache(tmp_path/'c.sqlite'),retries=1)
    data=manager.fetch('600519')
    assert (data.bars.close_raw==data.bars.close_adj).all()
    assert data.metadata['provider']=='mock'

def test_all_providers_fail(provider,tmp_path):
    manager=ProviderManager(providers=[Broken(),Broken()],resolver=SimpleNamespace(resolve=lambda _:Security('600519.SH','测试沪股')),
                            cache=DataCache(tmp_path/'c.sqlite'),retries=1)
    with pytest.raises(ProviderError,match='All providers unavailable'):manager.fetch('600519')

def test_config_order_and_token_gating(tmp_path,monkeypatch):
    monkeypatch.delenv('TUSHARE_TOKEN',raising=False)
    config=tmp_path/'providers.yaml';config.write_text('provider_order: [akshare, baostock, tushare]')
    manager=ProviderManager(config_path=config,cache=DataCache(tmp_path/'c.sqlite'))
    assert [p.name for p in manager.providers]==['akshare','baostock']
    default=ProviderManager(cache=manager.cache)
    assert [p.name for p in default.providers]==['baostock','akshare']

def test_benchmark_can_fall_back_without_mixing_stock_pair(provider,tmp_path):
    from copy import deepcopy
    first=deepcopy(provider); first.name='first'; first.benchmark=None
    manager=ProviderManager(providers=[first,provider],cache=DataCache(tmp_path/'c.sqlite'),retries=1)
    data=manager.fetch('600519')
    assert data.metadata['provider']=='first' and data.benchmark is not None
    assert any(x['provider']=='mock' and x['adjustment_type']=='NONE' for x in data.metadata['data_provenance'])

def test_invalid_symbol_is_not_network_unavailable(provider,tmp_path):
    manager=ProviderManager(providers=[Broken(),provider],cache=DataCache(tmp_path/'c.sqlite'))
    with pytest.raises(DataError):manager.fetch('invalid!')
