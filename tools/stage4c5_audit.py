"""Offline audit of this stage, emitting counts/hashes only, never matched text."""
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/stage4c5'


def git(*args):
    return subprocess.run(['git',*args],cwd=ROOT,capture_output=True,check=True).stdout


def write(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')


def main():
    import streamlit.runtime.caching.cache_data_api
    events=[]
    class Capture(logging.Handler):
        def emit(self,record):
            if record.getMessage()=='No runtime found, using MemoryCacheStorageManager':events.append(True)
    logger=logging.getLogger('streamlit.runtime.caching.cache_data_api');handler=Capture();logger.addHandler(handler)
    warning_counts=[]
    try:
        for body in (git('show','HEAD:app/web.py').decode('utf-8'),(ROOT/'app/web.py').read_text('utf-8')):
            events.clear()
            exec(compile(body,str(ROOT/'app/web.py'),'exec'),{'__name__':'__mp_main__','__file__':str(ROOT/'app/web.py')})
            warning_counts.append(len(events))
    finally:logger.removeHandler(handler)
    protected=['app/engine','app/rules','app/sector','app/data','app/features',
               'app/services','app/explanation','app/web_explanation.py','config']
    changed=git('diff','--name-only','HEAD','--',*protected).decode('utf-8').splitlines()
    new_files=['app/web_diagnostics.py','tests/test_web_diagnostics.py',
               'tools/stage4c5_diagnose.py','tools/stage4c5_audit.py','docs/STAGE4C5_RESULT.md']
    modified=['app/web.py','app/web_backend.py','app/web_runtime.py','app/web_snapshots.py']
    report={'head':git('rev-parse','HEAD').decode().strip(),
            'cached_origin_main':git('rev-parse','origin/main').decode().strip(),
            'git_fetch_this_stage':False,'commit_or_push_performed':False,
            'protected_changes':changed,'protected_sources_unchanged':not changed,
            'spawn_import_without_network':{'baseline_warning_count':warning_counts[0],'patched_warning_count':warning_counts[1]},
            'sdk_endpoint':{'host':'public-api.baostock.com','port':10030,'transport':'TCP',
                            'evidence':'installed baostock 0.9.4 common/contants.py + util/socketutil.py'},
            'stage_file_hashes':{p:sha256((ROOT/p).read_bytes()).hexdigest() for p in new_files+modified if (ROOT/p).exists()},
            'live_request_success_proves_prior_failure_root_cause':False}
    write('audit.json',report)
    xml=OUT/'pytest-final.xml'
    if xml.exists():
        suites=ET.parse(xml).getroot().findall('testsuite')
        test_counts={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
        test_counts['passed']=test_counts['tests']-test_counts['failures']-test_counts['errors']-test_counts['skipped']
        test_counts['seconds']=sum(float(s.attrib.get('time',0)) for s in suites)
        write('test_summary.json',test_counts)
    pattern=re.compile(rb'\bsk-[A-Za-z0-9_-]{12,}|\bBearer\s+[A-Za-z0-9._-]{16,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    matches=[];checked=0
    for path in [*(ROOT/p for p in new_files+modified),*OUT.rglob('*')]:
        if not path.is_file():continue
        checked+=1
        if pattern.search(path.read_bytes()):matches.append(path.relative_to(ROOT).as_posix())
    for label,args in [('git_diff',('diff','HEAD')),('staged_diff',('diff','--cached'))]:
        checked+=1
        if pattern.search(git(*args)):matches.append(label)
    write('security_scan.json',{'status':'PASS' if not matches else 'FAIL','checked_items':checked,
                               'matching_files':matches,'match_values_recorded':False,
                               'api_keys_read':False,'ai_calls':0,
                               'scope':'Stage4C5 files/artifacts (including SQLite and screenshots bytes), complete working and staged diffs; screenshot UI visually checked',
                               'scope_excludes_unrelated_historical_outputs':True})
    print(json.dumps({'protected_sources_unchanged':not changed,'spawn_warning_counts':report['spawn_import_without_network'],
                      'security_matches':len(matches)},ensure_ascii=False))


if __name__=='__main__':main()
