"""Publishable-change audit. Never prints matching credential/path contents."""
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/final_engineering'
FILES=['.github/workflows/market-update.yml','app/market_update.py','app/snapshot_publication.py',
       'app/screening/batch_provider.py','app/web.py','app/web_market.py','app/web_observability.py',
       'app/web_results.py','app/web_snapshots.py','tests/test_market_publication.py',
       'tests/test_provider_startup_cleanup.py','docs/MARKET_UPDATE_OPERATIONS.md',
       'docs/STAGE4_FINAL_ENGINEERING_RESULT.md','tools/update_published_context.py',
       'tools/scheduled_market_update.py','tools/commit_market_publication.py',
       'tools/product_public_verify.py','tools/final_public_verify.py','tools/final_live_probe.py',
       'tools/final_startup_probe.py','tools/final_engineering_audit.py','tools/final_closure_security.py']

def decode(data):
    if data.startswith((b'\xff\xfe',b'\xfe\xff')):return data.decode('utf-16')
    try:return data.decode('utf-8-sig')
    except UnicodeDecodeError:return data.decode('gb18030',errors='replace')

def main():
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.DEVNULL)
    initial=json.loads((OUT/'initial_integrity.json').read_text('utf-8'))
    related={'app/web_observability.py','app/snapshot_publication.py',
             'tools/product_public_verify.py','tools/update_published_context.py'}
    preserved={p:sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in initial['initial_files'].items()
               if p not in related and p!='README.md'}
    readme=(ROOT/'README.md').read_bytes();needle=b'## Stage 4 engineering closure'
    prefix=readme[:readme.index(needle)] if needle in readme else readme
    preserved['README_existing_changes']=any(sha256(prefix[:len(prefix)-n] if n else prefix).hexdigest()==initial['initial_files']['README.md'] for n in range(5))
    core=[p for p,h in initial['core'].items() if sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    assert all(preserved.values()) and core==['app/screening/batch_provider.py']
    private=re.compile(r'[A-Za-z]:[/\\]+(?:HuaweiMoveData[/\\]+)?Users[/\\]+(?:\\u[0-9a-fA-F]{4}|[^/\\\s"\'<>])+')
    artifacts=[p for p in OUT.rglob('*') if p.is_file() and p.suffix in {'.txt','.xml','.json'} and 'browser_tmp' not in p.parts]
    redactions=[]
    for p in artifacts:
        text=decode(p.read_bytes());text,n=private.subn('[REDACTED_USER_DIRECTORY]',text)
        if p.suffix=='.xml':text,h=re.subn(r'hostname="(?!REDACTED_HOST)[^"]*"','hostname="REDACTED_HOST"',text);n+=h
        if n:p.write_text(text,'utf-8');redactions.append(dict(file=p.relative_to(ROOT).as_posix(),count=n))
    values=[v for k,v in os.environ.items() if ('API_KEY' in k or k.endswith('_TOKEN')) and len(v)>=20]
    patterns=set(values)
    for value in values:patterns.update([base64.b64encode(value.encode()).decode(),value.encode().hex()])
    contents=[(p,(ROOT/p).read_text('utf-8')) for p in FILES if (ROOT/p).exists()]
    contents += [(p.relative_to(ROOT).as_posix(),decode(p.read_bytes())) for p in artifacts]
    contents += [('staged_diff',decode(git('diff','--cached','--')))]
    findings=[];fixture_sentinels=[]
    for name,text in contents:
        # Explicit artificial rejection fixture; not a real user directory.
        sentinel='D:'+'/Users/'+'PRIVATE_TEST/path'
        fixture_context=name=='tests/test_market_publication.py' or (
            name=='staged_diff' and 'diff --git a/tests/test_market_publication.py b/tests/test_market_publication.py' in text)
        if fixture_context and sentinel in text:
            fixture_sentinels.append(name);text=text.replace(sentinel,'OFFLINE_PRIVACY_REJECTION_SENTINEL')
        categories=[]
        if re.search(r'\bsk-[A-Za-z0-9]{24,}\b',text) or any(v in text for v in patterns):categories.append('CREDENTIAL')
        if private.search(text):categories.append('PRIVATE_DIRECTORY')
        if categories:findings.append(dict(file=name,categories=categories))
    # Inventory all differences without staging unrelated historical files.
    audit_names=set(decode(git('diff','--name-only')).splitlines()) | set(decode(git('diff','--cached','--name-only')).splitlines())
    audit_names |= set(decode(git('ls-files','--others','--exclude-standard')).splitlines())
    preexisting=[]
    for name in sorted(audit_names-set(FILES)):
        path=ROOT/name
        if not path.is_file():continue
        text=decode(path.read_bytes());categories=[]
        if re.search(r'\bsk-[A-Za-z0-9]{24,}\b',text) or any(v in text for v in patterns):categories.append('CREDENTIAL')
        if private.search(text):categories.append('PRIVATE_DIRECTORY')
        if categories:preexisting.append(dict(file=name,categories=categories,action='PRESERVED_NOT_STAGED'))
    tests={}
    for path in OUT.glob('*.xml'):
        a=ET.parse(path).getroot()[0].attrib
        c={k:int(a[k]) for k in ('tests','failures','errors','skipped')}
        c.update(passed=c['tests']-c['failures']-c['errors']-c['skipped'],seconds=float(a['time']))
        tests[path.name]=c
    value=dict(preserved=preserved,changed_core=core,tests=tests,
        publish_files=FILES,unrelated_differences_preserved=sorted(audit_names-set(FILES)-{'README.md'}),
        privacy=dict(scope='all Git differences inventoried/scanned; release allowlist + staged diff + new textual evidence gated; historical logs/temp/browser profiles not published',
            items=len(contents),findings=findings,artifacts_redacted=redactions,synthetic_privacy_fixtures=fixture_sentinels))
    value['privacy']['preexisting_excluded_findings']=preexisting
    value['privacy']['tracked_secret_files']=decode(git('ls-files','--','.env','.streamlit/secrets.toml')).splitlines()
    (OUT/'security_and_gate.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(findings=len(findings),preserved=all(preserved.values()),changed_core=core,
        final_gate=tests.get('full_2.xml'))))
    assert not findings and not value['privacy']['tracked_secret_files']

if __name__=='__main__':main()
