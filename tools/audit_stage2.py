"""Read-only baseline verification; writes only the audit evidence report."""
from collections import Counter
import ast
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import yaml

ROOT=Path(__file__).resolve().parents[1]

def case_ids(xml):
    return Counter((x.attrib.get('classname'),x.attrib['name']) for x in xml.findall('.//testcase'))

def main():
    current=ET.parse(ROOT/'outputs/pytest-results.xml').getroot()
    with ZipFile(ROOT/'docs/archive/stage1_2_v1_3_baseline.zip') as z:
        previous=ET.fromstring(z.read('outputs/pytest-results.xml'))
        old_rules=yaml.safe_load(z.read('config/scoring_rules.yaml'))['rules']
        old_parameters=yaml.safe_load(z.read('config/parameters.yaml'))
        changed_tests={}
        for n in z.namelist():
            if n.startswith('tests/') and n.endswith('.py'):
                before=z.read(n).decode('utf-8-sig');after=(ROOT/n).read_text('utf-8-sig')
                names=lambda s:{node.name for node in ast.walk(ast.parse(s)) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_')}
                changed_tests[n]={'content_changed':before!=after,'removed_test_functions':sorted(names(before)-names(after))}
    baseline=case_ids(previous);actual=case_ids(current)
    missing=list((baseline-actual).elements())
    new_rules=yaml.safe_load((ROOT/'config/scoring_rules.yaml').read_text('utf-8-sig'))['rules']
    new_parameters=yaml.safe_load((ROOT/'config/parameters.yaml').read_text('utf-8-sig'))
    weight=lambda rs:{r['rule_id']:(r['max_score'],r['max_penalty']) for r in rs}
    hashes=json.loads((ROOT/'docs/archive/pre_v1_4_spec_hashes.json').read_text('utf-8'))
    historic={n:hashlib.sha256((ROOT/'docs'/n).read_bytes()).hexdigest()==h for n,h in hashes.items()}
    original=json.loads((ROOT/'outputs/runtime/resume_input_hashes.json').read_text('utf-8'))
    changed=[n for n,h in original.items() if (ROOT/n).exists() and hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    source=[]
    for folder in ('app','config','tests','tools','docs'):
        source.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.yaml','.md','.txt','.json') and not {'archive','__pycache__'}&set(p.parts))
    patterns=[re.compile(r'(?i)(?:token|api_key|secret|cookie)\s*[:=]\s*[\"\x27]([A-Za-z0-9_+/=-]{24,})[\"\x27]'),re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
    findings=[]
    for p in source:
        text=p.read_text('utf-8-sig',errors='replace')
        if any(pattern.search(text) for pattern in patterns):findings.append(str(p.relative_to(ROOT)))
    report={'baseline_tests':sum(baseline.values()),'retained_tests':sum(baseline.values())-len(missing),'missing':missing,
            'test_source_comparison':changed_tests,'weights_unchanged':weight(old_rules)==weight(new_rules) and old_parameters['SYSTEM']==new_parameters['SYSTEM'],
            'historical_specs_unchanged':historic,'implementation_counts':dict(Counter(r['code_status'] for r in new_rules)),
            'changed_since_workbuddy_entry':changed,'git_status':'NOT_A_GIT_REPOSITORY',
            'secret_scan':{'files_scanned':len(source),'suspect_files':findings,'scope':'Static assignment/private-key patterns; no claim of an exhaustive security audit'},
            'env_template_blank':(ROOT/'.env.example').read_text('utf-8-sig').strip()=='TUSHARE_TOKEN='}
    (ROOT/'outputs/runtime/resume_final_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('test_source_comparison','changed_since_workbuddy_entry')},ensure_ascii=False))
    assert not missing and report['weights_unchanged'] and all(historic.values())
    assert not any(v['removed_test_functions'] for v in changed_tests.values())
    assert not findings and report['env_template_blank']

if __name__=='__main__':main()
