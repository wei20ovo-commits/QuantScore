"""Read-only DOCX extraction. Generated text/registry are derivatives, never authority."""
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import hashlib
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'docs/QuantScore_V1.1_机器可执行评分规则规范_用户规则补全版.docx'
NAMES = {
 'S1':'Sector daily relative strength','S2':'Sector five day relative strength',
 'S3':'Sector breadth','S4':'Limit up density','S5':'Sector trading activity',
 'S6':'Sector persistence','S7':'Strong stock depth',
 'A1':'Benchmark short term trend','A2':'Benchmark medium term structure','A3':'Benchmark five day momentum',
 'B1':'Sector heat mapping','B2':'Stock sector relative strength','B3':'First limit up leader proxy',
 'C1':'Sustained position above M60','C2':'M60 direction','C3':'Moving average structure',
 'C4':'M60 breakout or rapid reclaim','C5':'M60 launch platform','C6':'Rising closing trough support',
 'D1':'Breakout volume','D2':'Low volume pullback','D3':'Up versus down day volume',
 'D4':'Consolidation volume contraction','D5':'Turnover health',
 'E1':'Bottom small bullish run','E2':'Weekly volume reversal','E3':'Small fluctuation volume proxy',
 'E4':'Low price chip peak','E5':'Chip concentration improvement',
 'F1-N':'N launch','F1-T':'T launch','F1-O':'One line launch','F1-X':'Probe and pullback',
 'F1-Y':'Dragon gate and one day fake fall','F2':'Launch location','F3':'High level continuation',
 'R1':'High zone abnormal turnover','R2':'High zone abnormal volume','R3':'High zone failed limit seal',
 'R4':'Double top risk','R5':'Three candle reversal','R6':'Intraday low volume second rally',
 'R7':'Lagged high match signal failure','R8':'Closing support break','R9':'M30 break',
 'R10':'Chip peak migration','R11':'N exchange M5 hard break','R12':'T or one line abnormal trading'}


def extract():
    with ZipFile(SPEC) as z:
        root = ET.fromstring(z.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns))
                      for p in root.findall('.//w:p', ns)]
        extra = [n for n in z.namelist() if n.startswith('word/') and
                 any(k in n for k in ('footnotes', 'endnotes', 'comments', 'header', 'footer')) and n.endswith('.xml')]
        auxiliary = {n: ''.join(ET.fromstring(z.read(n)).itertext()) for n in extra}
        changes = len(root.findall('.//w:del', ns)) + len(root.findall('.//w:ins', ns))
    text = '\n'.join(paragraphs)
    return text, {'sha256': hashlib.sha256(SPEC.read_bytes()).hexdigest(),
                  'paragraph_count': len(paragraphs), 'characters': len(text),
                  'tracked_change_elements': changes, 'auxiliary_parts': auxiliary}


def main():
    text, manifest = extract()
    (ROOT/'docs/SPEC_EXTRACTED.txt').write_text(text, encoding='utf-8')
    headings = list(re.finditer(r'^([SABCDEF R]\d+(?:-[NTOXY])?)｜(.+)$', text, re.M))
    rules = []
    for index, m in enumerate(headings):
        rid, name = m.groups()
        end = headings[index+1].start() if index+1 < len(headings) else text.index('7. 去重、互斥与类别封顶')
        body = text[m.end():end].strip()
        body = re.split(r'\n[567]\. (?:QuantScore|风险扣分|去重)', body)[0]
        sections = {}
        marks = list(re.finditer(r'(?m)^(10|[1-9])）[^：\n]+：', body))
        for j, mark in enumerate(marks):
            sections[int(mark.group(1))] = body[mark.end():marks[j+1].start() if j+1<len(marks) else len(body)].strip()
        # Revised tables physically follow section 10 in the source document.
        tail = sections.get(10, '')
        if '\n条件\n得分/扣分\n' in tail:
            template, table = tail.split('\n条件\n得分/扣分\n', 1)
            sections[10] = template.strip()
            sections[7] = '条件\n得分/扣分\n' + table.strip()
        max_text = re.search(r'最大分值/扣分\n([^\n]+)', body).group(1)
        maximum = int(re.search(r'[+\-](\d+)', max_text).group(1))
        source = re.search(r'自动化级别\n([^\n]+)', body).group(1)
        rules.append(dict(rule_id=rid, name_cn=name, name_en=NAMES[rid], category=rid[0],
            rule_type='RISK' if rid[0]=='R' else 'SECTOR' if rid[0]=='S' else 'POSITIVE',
            source_type='AUTO_IF_DATA' if source=='AUTO_IF_MINUTE_DATA' else source,
            source_type_in_spec=source, max_score=0 if rid[0]=='R' else maximum,
            max_penalty=maximum if rid[0]=='R' else 0, required_fields=sections.get(2, '').splitlines(),
            lookback=sections.get(3,''), prerequisites=sections.get(4,'').splitlines(),
            parameters={'ref':f'parameters.yaml#{rid}'},
            status_values=['PASS','PARTIAL','FAIL','UNKNOWN','CANDIDATE','FORMED','CONFIRMED','INVALIDATED'],
            scoring_levels={'spec_text':sections.get(7,'')}, invalidation_rules=sections.get(8,'').splitlines(),
            unknown_conditions=sections.get(8,'').splitlines(), conflict_rules=sections.get(9,'').splitlines(),
            explanation_template=sections.get(10,''), spec_version='1.1',
            spec_status='FROZEN_V1_1', code_status='NOT_IMPLEMENTED', evaluator=None,
            definition=sections.get(5,''), steps=sections.get(6,''),
            source_note=re.search(r'笔记依据\n([^\n]+)', body).group(1),
            source_text=body))
    assert set(NAMES) == {r['rule_id'] for r in rules}
    manifest['rule_count'] = len(rules)
    for path, data in [('config/scoring_rules.yaml',dict(spec_version='1.1',rules=rules)),
                       ('docs/SPEC_MANIFEST.yaml',manifest)]:
        dest=ROOT/path
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
    print(f'Extracted {len(rules)} rules; SHA256={manifest["sha256"]}')


if __name__=='__main__':
    raise SystemExit('Legacy V1.1 parser is archival only. V1.2: use python -m tools.upgrade_v12 followed by python -m tools.finalize_registry; do not overwrite active registry with legacy rules.')
