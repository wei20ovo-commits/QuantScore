"""OFFLINE fixture transport only; never proof of real market/public success."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def offline_result(payload_file):
    from app.web_diagnostics import trace_call,emit,safe_event
    events=[]
    output=trace_call(events,'analysis',lambda:json.loads(Path(payload_file).read_text('utf-8')))
    if output['data_status']['status']=='UNAVAILABLE':
        events.append(emit(safe_event('analysis','UNAVAILABLE',reason_code='DATA_UNAVAILABLE')))
    output['web_diagnostics']={'events':events,'reason_code':
        'DATA_UNAVAILABLE' if output['data_status']['status']=='UNAVAILABLE' else 'NONE'}
    return output


def read_json_result(payload_file):
    return json.loads(Path(payload_file).read_text('utf-8'))


def immediate_index_batch(marker=None):
    if marker is not None:
        Path(marker).write_text('started', encoding='utf-8')
    return []


def slow_index_batch(marker, seconds=20):
    descendant=subprocess.Popen(
        [sys.executable,'-c',f'import time; time.sleep({seconds + 20!r})'])
    Path(marker).write_text(json.dumps({
        'started':True,'pid':os.getpid(),'descendant_pid':descendant.pid
    }),encoding='utf-8')
    time.sleep(seconds)
    return [{'name':'SLOW INDEX','date':'2026-09-30','close':1,'change':0,
             'percent':0,'trend':[1],'symbol':'000001.SH'}]


def delayed_result(payload_file, seconds):
    time.sleep(seconds)
    return read_json_result(payload_file)


def offline_initialization_failure():
    from app.web_diagnostics import trace_call,boundary_reason
    def fail():raise ValueError('PRIVATE_TEST_SENTINEL timeout connection Z:/private')
    trace_call([],'provider_init',fail,error_classifier=boundary_reason)
