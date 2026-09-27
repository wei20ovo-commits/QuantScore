"""Source completeness checks: prevent empty amendments and source drift."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import yaml

ROOT=Path(__file__).resolve().parents[1]


def document_paragraphs():
    with ZipFile(ROOT/'docs/QuantScore_V1.2_机器可执行评分规则规范_歧义清零版.docx') as z:
        root=ET.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    return [''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in root.findall('.//w:p',ns)]


def test_v11_source_unchanged():
    doc=ROOT/'docs/QuantScore_V1.1_机器可执行评分规则规范_用户规则补全版.docx'
    assert hashlib.sha256(doc.read_bytes()).hexdigest()=='79ec2876cd3658a2ae9da2fab3a397c9b192d98d39058cb6ed60c0e7448b0a8b'


def test_v12_contains_all_amendment_bodies():
    amendments=json.loads((ROOT/'docs/V1_2_AMENDMENTS.json').read_text(encoding='utf-8'))
    paragraphs=document_paragraphs(); normalized=''.join(''.join(paragraphs).split())
    assert len(amendments)==14
    for title,body in amendments:
        assert body.strip() and title in paragraphs
        assert ''.join(body.split()) in normalized


def test_v12_preserves_all_rule_definitions_and_pending_decisions():
    rules=yaml.safe_load((ROOT/'config/scoring_rules.yaml').read_text(encoding='utf-8'))['rules']
    paragraphs=document_paragraphs()
    assert len(rules)==48
    for r in rules:
        assert r['rule_id']+' '+r['name_cn'] in paragraphs
    for rid in ('U01 R7','U02 E1','U03 F1-Y','U04 F1-O'):
        assert rid in paragraphs


def test_s4_real_limit_contract_agrees_with_active_spec():
    rules=yaml.safe_load((ROOT/'config/scoring_rules.yaml').read_text(encoding='utf-8'))['rules']
    params=yaml.safe_load((ROOT/'config/parameters.yaml').read_text(encoding='utf-8'))
    r=next(r for r in rules if r['rule_id']=='S4')
    assert 'count(close_raw >= limit_up_price)' in r['definition']
    assert params['S4']['spec_definition']==r['definition']
    assert 'S4真实封停以close_raw>=真实limit_up_price判断' in ''.join(document_paragraphs())
