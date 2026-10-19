"""Local-only acceptance evidence. No Git mutation, tokens or upstream logs."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

DELIVERY=[
    'app/cloud_state.py','app/cloud_update.py','app/screening/service.py',
    'tools/cloud_market_update.py','tools/cloud_provider_probe.py','tools/cloud_update_acceptance.py',
    'tests/test_cloud_update.py','tests/test_ui_final.py','tests/test_web_explanation.py',
    'docs/STAGE4_FREE_CLOUD_FEASIBILITY.md',
    'deployment/github-hosted/provider-probe.yml.example',
    'deployment/github-hosted/market-slice.yml.example',
    'deployment/github-hosted/market-update.yml.example',
    'app/data/errors.py','app/data/models.py','app/web_diagnostics.py',
    'tools/stage4c7_r1_workers.py','tests/test_web_observability.py',
    'tests/test_cloud_state_security.py','tests/test_web_diagnostics.py']
CREDENTIAL=re.compile(r'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
                      r'AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
PRIVATE=re.compile(r'(?i)(?:[A-Z]:[\\/](?:[^\r\n"\s]*[\\/])?(?:Users|HuaweiMoveData)[\\/]|/(?:home|Users)/[^\s"/]+/)')


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--junit',default='outputs/free_cloud/pytest_full.xml')
    parser.add_argument('--output',default='outputs/free_cloud/acceptance.json')
    args=parser.parse_args()
    initial=json.loads((ROOT/'outputs/free_cloud/initial_integrity.json').read_text('utf-8'))
    changed=[]
    for group in ('protected','frozen'):
        for name,digest in initial[group].items():
            p=ROOT/name
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                changed.append(dict(group=group,file=name))
    head=git('rev-parse','HEAD').decode().strip()
    index=hashlib.sha256(git('diff','--cached','--binary')).hexdigest()
    findings=[]
    missing=[]
    # Compare configured credential values in memory only; do not serialize
    # names, values, excerpts or encodings into evidence.
    configured=[v for k,v in os.environ.items() if len(v)>=12 and
                re.search(r'(?:API_KEY|TOKEN|SECRET|PASSWORD)$',k,re.I)]
    # All changed/staged/untracked sources are audited; do not edit someone
    # else's findings to manufacture a zero. Never print a matched secret.
    names=set(DELIVERY)
    for git_args in [('diff','--name-only','-z'),('diff','--cached','--name-only','-z'),
                     ('ls-files','--others','--exclude-standard','-z')]:
        names.update(n for n in git(*git_args).decode('utf-8').split('\0') if n)
    names.update('outputs/free_cloud/'+n for n in (
        'provider_probe.json','provider_probe_initial_script_error.json','cache_sizing.json',
        'cache_sizing_128mib.json','cache_roundtrip.json'))
    for name in sorted(names):
        p=ROOT/name
        if not p.is_file():
            if name in DELIVERY:missing.append(name)
            continue
        # Runtime binary state has already been content-scanned on export and
        # verified on import. Never interpret pixels/binary as secret text.
        if p.stat().st_size>8*1024**2:
            findings.append(dict(file=name,category='REQUIRES_LARGE_FILE_REVIEW'))
            continue
        text=p.read_text('utf-8',errors='replace')
        if any(value in text for value in configured):
            findings.append(dict(file=name,category='CONFIGURED_CREDENTIAL_VALUE'))
        for category,pattern in [('CREDENTIAL',CREDENTIAL),('PERSONAL_PATH',PRIVATE)]:
            if pattern.search(text):
                findings.append(dict(file=name,category=category,scope='delivery' if name in DELIVERY else 'preexisting'))
    suites=ET.parse(ROOT/args.junit).getroot()
    if suites.tag=='testsuite':all_suites=[suites]
    else:all_suites=list(suites.findall('testsuite'))
    counts={k:sum(int(s.attrib.get(k,0)) for s in all_suites) for k in ('tests','failures','errors','skipped')}
    counts['passed']=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
    local_ok=(not changed and head==initial['HEAD'] and index==initial['index'] and not missing
              and not findings and counts['failures']==0 and counts['errors']==0 and counts['skipped']==1)
    result=dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),
        status='LOCAL_PASS' if local_ok else 'BLOCKED',cloud_status='NOT_RUN',
        head=head,head_preserved=head==initial['HEAD'],index_preserved=index==initial['index'],
        preexisting_files_checked=len(initial['protected']),frozen_files_checked=len(initial['frozen']),
        integrity_changes=changed,delivery=DELIVERY,missing=missing,
        scanned_text_files=len(names),findings=findings,tests=counts,
        safety_scope='delivery + current Git diff/index/untracked sources + small sanitized evidence JSON; '
                     'historical ignored logs/JUnit/private workstation files are NOT public artifacts',
        real_network='See provider_probe.json; local network success is not hosted success')
    output=ROOT/args.output
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if local_ok else 1


if __name__=='__main__':
    raise SystemExit(main())
