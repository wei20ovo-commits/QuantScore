"""Manual, bounded connectivity evidence; never a production Provider or snapshot.

One anonymous BaoStock session OR at most three serial HTTPS requests. No retries.
No raw payloads, exception messages, addresses, headers or environment values leave
the child. Run each profile once on the target runner, not as an automatic retry.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
import uuid

HOST = 'public-api.baostock.com'
PORT = 10030
MODES = ('baostock', 'https-eastmoney', 'https-tencent')
DEADLINE = 60
SOCKET_SECONDS = 5
HTTP_SECONDS = 8
MAX_BODY = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
REASONS = frozenset(('UNEXPECTED_ENDPOINT', 'EMPTY_DNS', 'EVENT_BUDGET',
    'UNSUPPORTED_SDK_ENDPOINT', 'ROW_BUDGET', 'CALENDAR_SCHEMA', 'CALENDAR_VALUES',
    'LOGOUT_FAILED', 'PRICE_ROWS', 'PRICE_FIELDS', 'PRICE_VALUES', 'PRICE_DATES',
    'HTTP_STATUS', 'BODY_BUDGET', 'HTTP_TIMEOUT', 'TLS_ERROR', 'PROXY_ERROR',
    'HTTP_CONNECTION_ERROR', 'EASTMONEY_RESPONSE', 'TENCENT_RESPONSE', 'SYMBOL',
    'DATE_RANGE', 'RAW_QFQ_INDEX_ALIGNMENT', 'JSON_SCHEMA'))


class ProbeFailure(Exception):
    def __init__(self, reason='UNKNOWN'):
        self.reason = reason if reason in REASONS else 'UNKNOWN'
        super().__init__(self.reason)


def error_kind(exc):
    """Fixed vocabulary only; exception text may contain credentials or paths."""
    if isinstance(exc, socket.gaierror):
        return 'DNS_FAILURE'
    if isinstance(exc, TimeoutError):
        return 'SOCKET_TIMEOUT'
    if isinstance(exc, ConnectionRefusedError):
        return 'CONNECTION_REFUSED'
    if isinstance(exc, EOFError):
        return 'REMOTE_EOF'
    if isinstance(exc, ConnectionError):
        return 'CONNECTION_ERROR'
    if isinstance(exc, OSError):
        return 'NETWORK_OR_OS_ERROR'
    if isinstance(exc, ProbeFailure):
        return 'VALIDATION_ERROR'
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return 'RESPONSE_PARSE_ERROR'
    return 'SDK_OR_PROBE_EXCEPTION'


class Recorder:
    def __init__(self, path):
        self.path = Path(path)
        self.start = time.monotonic()
        self.phase = 'worker'
        self.count = 0

    def emit(self, stage, status, **values):
        # All callers pass constants, counts or validated dates, never error text.
        self.count += 1
        if self.count > 128:
            raise ProbeFailure('EVENT_BUDGET')
        event = dict(stage=stage, phase=self.phase, status=status,
                     seconds=round(time.monotonic() - self.start, 4), **values)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=True) + '\n')
            stream.flush()

    def call(self, stage, func, *args, **kwargs):
        self.emit(stage, 'START')
        begin = time.monotonic()
        try:
            value = func(*args, **kwargs)
        except Exception as exc:
            self.emit(stage, 'FAILURE', error_kind=error_kind(exc),
                      duration=round(time.monotonic() - begin, 4))
            raise
        self.emit(stage, 'SUCCESS', duration=round(time.monotonic() - begin, 4))
        return value


def install_socket_trace(rec):
    """Child-only instrumentation. First IPv4 address, no alternate-IP retries.

    Explicit DNS is equivalent to the SDK's implicit AF_INET lookup. EOF is
    raised locally to stop the SDK's empty-recv loop; production is untouched.
    """
    original = socket.socket

    class TracedSocket(original):
        def connect(self, address):
            if address != (HOST, PORT):
                raise ProbeFailure('UNEXPECTED_ENDPOINT')
            addresses = rec.call('dns', socket.getaddrinfo, HOST, PORT,
                                 socket.AF_INET, socket.SOCK_STREAM)
            if not addresses:
                raise ProbeFailure('EMPTY_DNS')
            self.settimeout(SOCKET_SECONDS)
            return rec.call('tcp_connect', super().connect, addresses[0][4])

        def send(self, payload, *args):
            sent = rec.call('send', super().send, payload, *args)
            rec.emit('send_bytes', 'SUCCESS', bytes=sent,
                     partial_send=sent != len(payload))
            return sent

        def recv(self, size, *args):
            data = rec.call('receive', super().recv, size, *args)
            rec.emit('receive_bytes', 'SUCCESS' if data else 'FAILURE', bytes=len(data),
                     error_kind='NONE' if data else 'REMOTE_EOF')
            if not data:
                raise EOFError()
            return data

    socket.socket = TracedSocket
    return original


def sdk_code(result):
    value = str(getattr(result, 'error_code', ''))
    return value if re.fullmatch(r'-?\d{1,8}', value) else 'UNKNOWN'


def baostock_probe(rec):
    rec.phase = 'sdk_import'
    def load():
        import baostock
        return baostock
    sdk = rec.call('sdk_import', load)
    import baostock.common.contants as constants
    import baostock.common.context as context
    if (constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT) != (HOST, PORT):
        raise ProbeFailure('UNSUPPORTED_SDK_ENDPOINT')
    # Fresh anonymous session, never use environment or SDK API keys.
    if hasattr(context, 'apiKey'):
        delattr(context, 'apiKey')
    version = importlib.metadata.version('baostock')
    rec.emit('sdk_version', 'SUCCESS', version=version if re.fullmatch(r'[\d.]+', version) else 'UNKNOWN')
    original = install_socket_trace(rec)
    logged_in = False
    try:
        rec.phase = 'login'
        login = rec.call('login', sdk.login)
        rec.emit('login_result', 'SUCCESS' if sdk_code(login) == '0' else 'FAILURE', code=sdk_code(login))
        if sdk_code(login) != '0':
            return False
        logged_in = True
        rec.phase = 'calendar_query'
        today = datetime.now(timezone.utc).date()
        result = rec.call('calendar_query', sdk.query_trade_dates,
                          start_date=(today - timedelta(days=7)).isoformat(), end_date=today.isoformat())
        rec.emit('query_result', 'SUCCESS' if sdk_code(result) == '0' else 'FAILURE', code=sdk_code(result))
        if sdk_code(result) != '0':
            return False
        rows = []
        while result.next():
            rows.append(result.get_row_data())
            if len(rows) > 8:
                raise ProbeFailure('ROW_BUDGET')
        if result.fields != ['calendar_date', 'is_trading_day'] or not rows:
            raise ProbeFailure('CALENDAR_SCHEMA')
        dates = [date.fromisoformat(row[0]) for row in rows]
        if (len(set(dates)) != len(rows) or any(row[1] not in ('0', '1') for row in rows)
                or min(dates) < today - timedelta(days=7) or max(dates) > today):
            raise ProbeFailure('CALENDAR_VALUES')
        rec.emit('calendar_validation', 'SUCCESS', rows=len(rows),
                 source_date_min=min(dates).isoformat(), source_date_max=max(dates).isoformat())
        return True
    finally:
        try:
            # Unlike production query_session, no network logout after failed login.
            # A failed login is already terminal; always close its socket locally.
            if logged_in:
                rec.phase = 'logout'
                result = rec.call('logout', sdk.logout)
                rec.emit('logout_result', 'SUCCESS' if sdk_code(result) == '0' else 'FAILURE', code=sdk_code(result))
                if sdk_code(result) != '0':
                    raise ProbeFailure('LOGOUT_FAILED')
        finally:
            connection = getattr(context, 'default_socket', None)
            if connection is not None:
                connection.close()
            socket.socket = original


def validate_prices(rows, source):
    """Schema probe only: NOT equivalent to full production DataValidator."""
    import math
    dates = []
    if not rows or len(rows) > 100:
        raise ProbeFailure('PRICE_ROWS')
    for row in rows:
        if len(row) < (11 if source == 'eastmoney' else 6):
            raise ProbeFailure('PRICE_FIELDS')
        day = date.fromisoformat(row[0]).isoformat()
        opening, close, high, low, volume = map(float, row[1:6])
        if (not all(math.isfinite(x) for x in (opening, close, high, low, volume))
                or min(opening, close, high, low) <= 0 or volume < 0
                or low > min(opening, close) or high < max(opening, close) or low > high):
            raise ProbeFailure('PRICE_VALUES')
        dates.append(day)
    if dates != sorted(set(dates)):
        raise ProbeFailure('PRICE_DATES')
    return dates


def http_json(rec, session, url, params):
    # Requests has no adapter retries by default. Reject redirects rather than
    # following arbitrary origins. Record status only; never headers/body/errors.
    import requests
    rec.emit('http_request', 'START')
    begin = time.monotonic()
    try:
        with session.get(url, params=params, timeout=(HTTP_SECONDS, HTTP_SECONDS),
                         allow_redirects=False, stream=True) as response:
            rec.emit('http_status', 'SUCCESS' if response.status_code == 200 else 'FAILURE',
                     http_status=response.status_code, duration=round(time.monotonic()-begin, 4))
            if response.status_code != 200:
                raise ProbeFailure('HTTP_STATUS')
            data = bytearray()
            for chunk in response.iter_content(16384):
                data.extend(chunk)
                if len(data) > MAX_BODY:
                    raise ProbeFailure('BODY_BUDGET')
            # The Tencent SDK uses JSONP. Accept only this fixed inert wrapper,
            # parsed as JSON; never execute JavaScript from the response.
            text = data.decode('utf-8-sig')
            if text.startswith('probe='):
                text = text[len('probe='):].rstrip().removesuffix(';')
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ProbeFailure('JSON_SCHEMA')
            return result
    except requests.exceptions.Timeout:
        rec.emit('http_request', 'FAILURE', error_kind='HTTP_TIMEOUT')
        raise ProbeFailure('HTTP_TIMEOUT') from None
    except requests.exceptions.SSLError:
        rec.emit('http_request', 'FAILURE', error_kind='TLS_ERROR')
        raise ProbeFailure('TLS_ERROR') from None
    except requests.exceptions.ProxyError:
        rec.emit('http_request', 'FAILURE', error_kind='PROXY_ERROR')
        raise ProbeFailure('PROXY_ERROR') from None
    except requests.exceptions.ConnectionError:
        rec.emit('http_request', 'FAILURE', error_kind='HTTP_CONNECTION_ERROR')
        raise ProbeFailure('HTTP_CONNECTION_ERROR') from None


def https_probe(rec, source):
    import requests
    end = datetime.now(timezone.utc).date()
    begin = end - timedelta(days=20)
    calendars = []
    with requests.Session() as session:
        for phase, symbol, adjusted in (('stock_raw', '600519', False),
                                        ('stock_qfq', '600519', True),
                                        ('index_raw', '000001', False)):
            rec.phase = phase
            if source == 'eastmoney':
                payload = http_json(rec, session, 'https://push2his.eastmoney.com/api/qt/stock/kline/get',
                                    dict(secid='1.'+symbol, klt='101', fqt='1' if adjusted else '0',
                                         beg=begin.strftime('%Y%m%d'), end=end.strftime('%Y%m%d'),
                                         fields1='f1,f2,f3,f4,f5,f6',
                                         fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'))
                code = payload.get('rc')
                rec.emit('api_result', 'SUCCESS' if code == 0 else 'FAILURE',
                         code=code if type(code) is int else 'UNKNOWN')
                if payload.get('rc') != 0 or not isinstance(payload.get('data'), dict):
                    raise ProbeFailure('EASTMONEY_RESPONSE')
                if payload['data'].get('code') != symbol:
                    raise ProbeFailure('SYMBOL')
                rows = [item.split(',') for item in payload['data'].get('klines', [])]
            else:
                code = 'sh'+symbol
                payload = http_json(rec, session, 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get',
                                    dict(_var='probe', param=f'{code},day,{end.year}-01-01,{end.year+1}-12-31,640,{"qfq" if adjusted else ""}'))
                result_code=payload.get('code')
                rec.emit('api_result', 'SUCCESS' if result_code == 0 else 'FAILURE',
                         code=result_code if type(result_code) is int else 'UNKNOWN')
                if payload.get('code') != 0:
                    raise ProbeFailure('TENCENT_RESPONSE')
                body = payload.get('data', {}).get(code, {})
                # qfq must be explicitly returned, never silently use raw instead.
                rows = body.get('qfqday' if adjusted else 'day', [])
                rows = [r for r in rows if begin.isoformat() <= r[0] <= end.isoformat()]
            dates = validate_prices(rows, source)
            if dates[0] < begin.isoformat() or dates[-1] > end.isoformat():
                raise ProbeFailure('DATE_RANGE')
            calendars.append(dates)
            rec.emit('price_schema', 'SUCCESS', rows=len(rows), source_date_min=dates[0], source_date_max=dates[-1],
                     amount_turnover_columns=all(len(row)>=(11 if source=='eastmoney' else 9) for row in rows))
        if calendars[0] != calendars[1] or calendars[0][-1] != calendars[2][-1]:
            raise ProbeFailure('RAW_QFQ_INDEX_ALIGNMENT')
        # Do not claim index bar dates are a verified trading calendar.
        rec.emit('coverage', 'PARTIAL', calendar='NOT_TESTED', industry='NOT_TESTED',
                 corporate_actions='NOT_VERIFIED', units='NOT_CROSSCHECKED',
                 redistribution_permission='NOT_VERIFIED')
    return True


class Discard:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def worker(mode, event_path):
    rec = Recorder(event_path)
    rec.emit('worker_start', 'SUCCESS')
    with redirect_stdout(Discard()), redirect_stderr(Discard()):
        try:
            passed = baostock_probe(rec) if mode == 'baostock' else https_probe(rec, mode.removeprefix('https-'))
            rec.emit('probe_complete', 'SUCCESS' if passed else 'FAILURE')
        except Exception as exc:
            rec.emit('probe_complete', 'FAILURE', error_kind=error_kind(exc),
                     reason_code=exc.reason if isinstance(exc, ProbeFailure) else 'UNKNOWN')


def read_events(path):
    events = []
    if path.exists() and path.stat().st_size <= 128*2048:
        for line in path.read_text('utf-8', errors='replace').splitlines()[:128]:
            try:
                events.append(json.loads(line))
            except (ValueError, TypeError):
                break  # Preserve complete prefix if killed during final write.
    return events


def revision():
    try:
        value = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                        timeout=2, stderr=subprocess.DEVNULL).decode().strip()
        return value if re.fullmatch('[a-f0-9]{40}', value) else 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'


def run(mode, output, *, deadline=DEADLINE, target=worker):
    if mode not in MODES or not 0 < deadline <= DEADLINE:
        raise ValueError('INVALID_PROBE_BUDGET')
    start = time.monotonic()
    scratch = ROOT/'outputs/tmp'
    scratch.mkdir(parents=True, exist_ok=True)
    events = []
    terminal = 'WORKER_NOT_STARTED'
    exitcode = None
    with tempfile.TemporaryDirectory(prefix='conn-', dir=scratch) as folder:
        event_path = Path(folder)/'events.jsonl'
        process = mp.get_context('spawn').Process(target=target, args=(mode, str(event_path)))
        try:
            process.start()
            process.join(max(0, deadline-(time.monotonic()-start)))
            terminal = 'WORKER_DEADLINE' if process.is_alive() else 'WORKER_EXITED'
        except Exception:
            terminal = 'WORKER_START_FAILURE'
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join(1)
                exitcode = process.exitcode
            events = read_events(event_path)
            if process.pid is not None and not process.is_alive():
                process.close()
    completed = next((e for e in reversed(events) if e['stage']=='probe_complete'), None)
    report = dict(schema_version=1, request_id=uuid.uuid4().hex,
                  mode=mode, hosted=os.getenv('GITHUB_ACTIONS')=='true',
                  code_revision=revision(), probe_fingerprint=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  generated_at=datetime.now(timezone.utc).isoformat(),
                  status='PASS' if terminal=='WORKER_EXITED' and exitcode==0 and completed and completed['status']=='SUCCESS' else 'FAILURE',
                  terminal=terminal, worker_exitcode=exitcode, seconds=round(time.monotonic()-start, 4),
                  budget=dict(hard_run_seconds=deadline, cleanup_seconds=2, retries=0,
                              sdk_queries_max=1 if mode=='baostock' else 0,
                              http_requests_max=0 if mode=='baostock' else 3,
                              socket_seconds=SOCKET_SECONDS, http_seconds=HTTP_SECONDS),
                  last_observed_stage=events[-1]['stage'] if events else 'UNKNOWN',
                  observations_complete=bool(completed) and terminal=='WORKER_EXITED',
                  scope='CONNECTIVITY_SCHEMA_ONLY_NOT_PRODUCTION_ACCEPTANCE', events=events)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
    temporary.replace(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=MODES, default='baostock')
    args = parser.parse_args()
    result = run(args.mode, ROOT/f'outputs/free_cloud/connection_probe_{args.mode}.json')
    print(json.dumps({k:result[k] for k in ('mode','hosted','status','terminal','seconds','last_observed_stage')}))
    return 0 if result['status']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
