"""Synthetic protocol fixtures only; never real network or credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time
from types import SimpleNamespace

import pytest

from tools import cloud_connection_probe as probe


def test_error_redaction(tmp_path):
    rec = probe.Recorder(tmp_path/'events')
    with pytest.raises(RuntimeError):
        rec.call('login', lambda: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_PRIVATE_ERROR')))
    data = probe.read_events(rec.path)
    assert data[-1]['error_kind']=='SDK_OR_PROBE_EXCEPTION'
    assert 'SYNTHETIC_PRIVATE_ERROR' not in rec.path.read_text()
    assert data[-1]['duration'] >= 0


@pytest.mark.parametrize('exc,kind', [(socket.gaierror(), 'DNS_FAILURE'),
    (TimeoutError(), 'SOCKET_TIMEOUT'), (ConnectionRefusedError(), 'CONNECTION_REFUSED'),
    (EOFError(), 'REMOTE_EOF'), (OSError(), 'NETWORK_OR_OS_ERROR')])
def test_error_vocabulary(exc, kind):
    assert probe.error_kind(exc)==kind


@pytest.mark.parametrize('failure', ['none','dns','tcp','read','eof','partial'])
def test_socket_phases_and_no_payload(tmp_path, monkeypatch, failure):
    class OfflineSocket:
        def __init__(self): pass
        def settimeout(self, value): assert value==5
        def connect(self, address):
            if failure=='tcp': raise TimeoutError()
        def send(self, data): return len(data)-(1 if failure=='partial' else 0)
        def recv(self, size):
            if failure=='read': raise TimeoutError()
            return b'' if failure=='eof' else b'SYNTHETIC_RESPONSE'
    def resolve(*args):
        if failure=='dns': raise socket.gaierror()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 10030))]
    monkeypatch.setattr(socket,'socket',OfflineSocket)
    monkeypatch.setattr(socket,'getaddrinfo',resolve)
    rec=probe.Recorder(tmp_path/'events')
    probe.install_socket_trace(rec)
    obj=socket.socket()
    rec.phase='login'
    if failure in ('dns','tcp'):
        with pytest.raises(OSError):obj.connect((probe.HOST,probe.PORT))
    else:
        obj.connect((probe.HOST,probe.PORT))
        obj.send(b'SYNTHETIC_LOGIN_PAYLOAD')
        if failure in ('read','eof'):
            with pytest.raises((TimeoutError,EOFError)):obj.recv(8192)
        else:obj.recv(8192)
    events=probe.read_events(rec.path)
    assert events[0]['stage']=='dns'
    if failure=='dns':assert not any(e['stage']=='tcp_connect' for e in events)
    if failure=='eof':assert events[-1]['error_kind']=='REMOTE_EOF'
    if failure=='partial':assert next(e for e in events if e['stage']=='send_bytes')['partial_send']
    text=rec.path.read_text()
    for forbidden in ('192.0.2.1','SYNTHETIC_LOGIN_PAYLOAD','SYNTHETIC_RESPONSE'):
        assert forbidden not in text


@pytest.mark.parametrize('failure', ['none','login','query','logout','schema'])
def test_sdk_session_cleanup_and_phase_attribution(tmp_path, monkeypatch, failure):
    import baostock
    import baostock.common.context as context
    called=[]
    class Result:
        fields=['calendar_date','is_trading_day']
        error_code='0'
        def __init__(self): self.done=False
        def next(self):
            if self.done:return False
            self.done=True
            return True
        def get_row_data(self):return [datetime.now(timezone.utc).date().isoformat(),'1']
    def login():
        called.append('login')
        print('SYNTHETIC_SDK_PRIVATE_OUTPUT')
        return SimpleNamespace(error_code='1' if failure=='login' else '0')
    def query(**kwargs):
        called.append('query')
        result=Result()
        if failure=='query':result.error_code='2'
        if failure=='schema':result.fields=['wrong']
        return result
    def logout():
        called.append('logout')
        return SimpleNamespace(error_code='3' if failure=='logout' else '0')
    class Connection:
        def close(self):called.append('close')
    monkeypatch.setattr(context,'default_socket',Connection(),raising=False)
    monkeypatch.setattr(context,'apiKey','SYNTHETIC_NOT_A_CREDENTIAL',raising=False)
    monkeypatch.setattr(baostock,'login',login)
    monkeypatch.setattr(baostock,'query_trade_dates',query)
    monkeypatch.setattr(baostock,'logout',logout)
    monkeypatch.setattr(probe,'install_socket_trace',lambda rec: socket.socket)
    probe.worker('baostock',tmp_path/'events')
    events=probe.read_events(tmp_path/'events')
    assert events[-1]['status']==('SUCCESS' if failure=='none' else 'FAILURE')
    assert called==(['login','close'] if failure=='login' else ['login','query','logout','close'])
    assert not hasattr(context,'apiKey')
    assert 'SYNTHETIC' not in (tmp_path/'events').read_text()
    # The tested child deletes this field; restore the fixture's placeholder so
    # monkeypatch can restore the pre-test absent attribute without teardown error.
    context.apiKey='SYNTHETIC_NOT_A_CREDENTIAL'


@pytest.mark.parametrize('rows', [[], [['2026-01-01','10','10','9','8','1']],
    [['2026-01-01','nan','10','11','9','1']], [['2026-01-01','10','10','11','9','-1']],
    [['invalid','10','10','11','9','1']],
    [['2026-01-01','10','10','11','9','1']]*2])
def test_invalid_prices_rejected(rows):
    with pytest.raises((ValueError,probe.ProbeFailure)):probe.validate_prices(rows,'tencent')


def test_http_transport_options_and_redaction(tmp_path):
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def iter_content(self,size):return [b'{"value":1}']
    class Session:
        def get(self,url,**kwargs):
            assert kwargs['allow_redirects'] is False
            assert kwargs['stream'] is True
            assert kwargs['timeout']==(8,8)
            return Response()
    rec=probe.Recorder(tmp_path/'events')
    assert probe.http_json(rec,Session(),'https://example.invalid',{})==dict(value=1)
    assert 'example.invalid' not in rec.path.read_text()


@pytest.mark.parametrize('code',[301,403,429,500])
def test_http_rejected_no_redirect_no_retry(tmp_path,code):
    calls=[]
    class Response:
        status_code=code
        def __enter__(self):return self
        def __exit__(self,*a):pass
    class Session:
        def get(self,*a,**kw):calls.append(kw);return Response()
    rec=probe.Recorder(tmp_path/'events')
    with pytest.raises(probe.ProbeFailure):probe.http_json(rec,Session(),'https://example.invalid',{})
    assert len(calls)==1
    assert probe.read_events(rec.path)[-1]['http_status']==code


@pytest.mark.parametrize('source',['eastmoney','tencent'])
@pytest.mark.parametrize('failure',['none','first','unaligned','missing_qfq'])
def test_https_bounded_profile_schema_not_production(tmp_path,monkeypatch,source,failure):
    calls=[]
    today=datetime.now(timezone.utc).date().isoformat()
    def fetch(rec,session,url,params):
        calls.append(params)
        if failure=='first':raise probe.ProbeFailure()
        day='2000-01-01' if failure=='unaligned' and len(calls)==2 else today
        symbol='000001' if len(calls)==3 else '600519'
        if source=='eastmoney':
            return dict(rc=0,data=dict(code=symbol,klines=[] if failure=='missing_qfq' and len(calls)==2
                else [','.join([day,'10','10','11','9','100','1000','1','1','1','1'])]))
        return dict(code=0,data={'sh'+symbol:{'day' if len(calls)!=2 or failure=='missing_qfq' else 'qfqday':
                [[day,'10','10','11','9','100']]}})
    monkeypatch.setattr(probe,'http_json',fetch)
    rec=probe.Recorder(tmp_path/'events')
    if failure=='none':
        assert probe.https_probe(rec,source)
        coverage=probe.read_events(rec.path)[-1]
        assert coverage['calendar']=='NOT_TESTED'
        assert coverage['industry']=='NOT_TESTED'
        assert coverage['redistribution_permission']=='NOT_VERIFIED'
    else:
        with pytest.raises(probe.ProbeFailure):probe.https_probe(rec,source)
    assert len(calls)==(1 if failure=='first' else 2 if failure!='none' else 3)


def offline_hang(mode,path):
    rec=probe.Recorder(path)
    rec.emit('worker_start','SUCCESS')
    rec.phase='calendar_query'
    rec.emit('receive','START')
    time.sleep(30)  # Child must be terminated; parent must not wait for this.


def offline_success(mode,path):
    rec=probe.Recorder(path)
    rec.emit('worker_start','SUCCESS')
    rec.emit('probe_complete','SUCCESS')


@pytest.mark.parametrize('target,status',[(offline_success,'PASS'),(offline_hang,'FAILURE')])
def test_spawn_deadline_cleanup_and_partial_evidence(tmp_path,monkeypatch,target,status):
    # No network. Lightweight worker startup is covered separately from SDK import.
    monkeypatch.setattr(probe,'ROOT',tmp_path)
    result=probe.run('baostock',tmp_path/'result.json',deadline=3,target=target)
    assert result['status']==status
    assert result['seconds'] < 6
    assert result['budget']['retries']==0
    assert len(result['request_id'])==32
    if target==offline_hang:
        assert result['terminal']=='WORKER_DEADLINE'
        assert result['events'][-1]['stage']=='receive'
        assert result['observations_complete'] is False
    assert not list((tmp_path/'outputs/tmp').glob('conn-*'))


def test_absent_and_partial_events_unknown_not_zero(tmp_path):
    assert probe.read_events(tmp_path/'missing')==[]
    path=tmp_path/'events'
    path.write_text('{"stage":"worker_start"}\n{"incomplete":',encoding='utf-8')
    assert probe.read_events(path)==[{'stage':'worker_start'}]


def test_probe_workflow_is_manual_bounded_and_readonly():
    import yaml
    root=Path(__file__).resolve().parents[1]
    path=root/'.github/workflows/hosted-provider-probe.yml'
    value=yaml.load(path.read_text(),Loader=yaml.BaseLoader)
    assert set(value['on'])=={'workflow_dispatch'}
    assert value['permissions']=={'contents':'read'}
    assert value['jobs']['probe']['timeout-minutes']=='10'
    text=path.read_text()
    assert 'cloud_connection_probe.py' in text
    assert 'market_update.py' not in text and 'market-slice' not in text
    assert 'secrets.' not in text
    assert text==(root/'deployment/github-hosted/provider-probe.yml.example').read_text()
