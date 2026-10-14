"""OFFLINE fixture transport only; never proof of real market/public success."""
import json
from pathlib import Path


def offline_result(payload_file):
    from app.web_diagnostics import trace_call,emit,safe_event
    events=[]
    output=trace_call(events,'analysis',lambda:json.loads(Path(payload_file).read_text('utf-8')))
    if output['data_status']['status']=='UNAVAILABLE':
        events.append(emit(safe_event('analysis','UNAVAILABLE',reason_code='DATA_UNAVAILABLE')))
    output['web_diagnostics']={'events':events,'reason_code':
        'DATA_UNAVAILABLE' if output['data_status']['status']=='UNAVAILABLE' else 'NONE'}
    return output


def offline_initialization_failure():
    from app.web_diagnostics import trace_call,boundary_reason
    def fail():raise ValueError('PRIVATE_TEST_SENTINEL timeout connection Z:/private')
    trace_call([],'provider_init',fail,error_classifier=boundary_reason)
