"""复用 upgrade_v13 的 OOXML 模板，仅扩展数据契约，不修改历史原件。"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    if list((ROOT / 'docs').glob('*V1.4*.docx')):
        raise SystemExit('V1.4 already exists; edit the existing document without rebuilding historical content.')
    hashes = json.loads((ROOT / 'docs/archive/pre_v1_4_spec_hashes.json').read_text(encoding='utf-8'))
    for name, digest in hashes.items():
        assert hashlib.sha256((ROOT / 'docs' / name).read_bytes()).hexdigest() == digest
    src = next((ROOT / 'docs').glob('*V1.3*.docx'))
    dst = ROOT / 'docs/QuantScore_V1.4_机器可执行评分规则规范_真实数据接入版.docx'
    with ZipFile(src) as z:
        files = {n: z.read(n) for n in z.namelist()}
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    ET.register_namespace('w', w)
    ns = {'w': w}
    tree = ET.fromstring(files['word/document.xml'])
    body = tree.find('w:body', ns)
    original = list(body)
    for node in original:
        body.remove(node)

    def para(text, style=None):
        node = ET.SubElement(body, '{'+w+'}p')
        props = ET.SubElement(node, '{'+w+'}pPr')
        if style:
            ET.SubElement(props, '{'+w+'}pStyle', {'{'+w+'}val': style})
        ET.SubElement(props, '{'+w+'}spacing', {'{'+w+'}after': '100'})
        ET.SubElement(ET.SubElement(node, '{'+w+'}r'), '{'+w+'}t').text = text

    para('QuantScore V1.4 机器可执行评分规则规范', 'Title')
    para('真实数据接入版 · Stage 2', 'Heading1')
    para('本规范仅新增 benchmark_index/name 与数据契约；完整评分正文继承 V1.3，规则、权重、阈值和状态语义不变。API/数据契约版本为1.4，评分结果与新冻结快照统一标spec_version=1.4、assumption_version=v1.3。历史版本原件不覆盖。')
    para('V1.4 数据契约', 'Heading1')
    contract = (ROOT / 'docs/DATA_CONTRACT.md').read_text(encoding='utf-8')
    for line in contract.splitlines():
        if line.strip() and not line.startswith('```'):
            para(line.lstrip('# ').replace('`', ''), 'Heading2' if line.startswith('## ') else None)
    para('继承的 V1.3 完整评分规范', 'Heading1')
    para('以下历史版本名称表示来源。V1.3最终冻结评分定义继续有效；旧T02、v1.1版本标签及“不接真实行情”等阶段性描述标记 HISTORICAL / SUPERSEDED，不得覆盖本版数据契约。')
    for node in original:
        if node.tag != '{'+w+'}sectPr':
            for p in ([node] if node.tag == '{'+w+'}p' else node.findall('.//w:p', ns)):
                text = ''.join(t.text or '' for t in p.findall('.//w:t', ns))
                if re.search(r'v1\.1|T02(?!_NEW)|不接真实行情', text, re.I):
                    run = ET.Element('{'+w+'}r')
                    ET.SubElement(run, '{'+w+'}t').text = 'HISTORICAL / SUPERSEDED（仅旧版本、旧T02及阶段描述；其余有效评分条款按V1.3继承）：'
                    p.insert(1 if p.find('w:pPr', ns) is not None else 0, run)
        body.append(node)
    files['word/document.xml'] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    for name, data in files.items():
        if name.endswith('.xml'):
            ET.fromstring(data)
    with ZipFile(dst, 'w', ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    print('V14_CREATED', len(tree.findall('.//w:p', ns)), 'paragraphs', hashlib.sha256(dst.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
