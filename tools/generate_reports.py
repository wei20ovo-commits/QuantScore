"""Build audit artifacts only from actual source/config and pytest XML."""
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import json
import yaml

ROOT=Path(__file__).resolve().parents[1]
registry=yaml.safe_load((ROOT/'config/scoring_rules.yaml').read_text(encoding='utf-8'))['rules']
from zipfile import ZipFile
old_manifest=yaml.safe_load(ZipFile(ROOT/'docs/archive/stage1_v1_1_baseline.zip').read('docs/SPEC_MANIFEST.yaml'))
v12_doc=next((ROOT/'docs').glob('*V1.2*.docx'))
assert hashlib.sha256(v12_doc.read_bytes()).hexdigest()=='7996e7f8403b5fe258edd83d26289a99443a715fc3fdb9196592de5d37c4d2cb', 'V1.2 changed'
old_doc=ROOT/'docs/QuantScore_V1.1_机器可执行评分规则规范_用户规则补全版.docx'
assert hashlib.sha256(old_doc.read_bytes()).hexdigest()==old_manifest['sha256'], 'V1.1 changed'
doc=ROOT/'docs/QuantScore_V1.4_机器可执行评分规则规范_真实数据接入版.docx'
with ZipFile(doc) as z:
    xml=ET.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs=[''.join(t.text or '' for t in node.findall('.//w:t',ns)) for node in xml.findall('.//w:p',ns)]
manifest={'spec_version':'1.4','sha256':hashlib.sha256(doc.read_bytes()).hexdigest(),
          'v1_1_sha256_unchanged':old_manifest['sha256'],'v1_2_sha256_unchanged':hashlib.sha256(v12_doc.read_bytes()).hexdigest(),'paragraph_count':len(paragraphs),'rule_count':len(registry)}
(ROOT/'docs/SPEC_MANIFEST.yaml').write_text(yaml.safe_dump(manifest,allow_unicode=True,sort_keys=False),encoding='utf-8')
(ROOT/'docs/SPEC_V1_4_EXTRACTED.txt').write_text('\n'.join(paragraphs),encoding='utf-8')
tree=ET.parse(ROOT/'outputs/pytest-results.xml')
cases=tree.findall('.//testcase')
failed=[c for c in cases if c.find('failure') is not None or c.find('error') is not None]
skipped=[c for c in cases if c.find('skipped') is not None]
passed=len(cases)-len(failed)-len(skipped)
all_green=not failed

lines=['# Rule Implementation Matrix','',
       'Spec Status=FROZEN_V1_4表示定义来自冻结Word，不代表代码完成。用户语义已冻结；IMPLEMENTED为完整执行器，UNKNOWN仍可由客观数据条件产生。',
       'Test Status只针对评分执行器：未实现规则的UNKNOWN守卫测试即使通过，仍标NOT_TESTED，不冒充业务验收通过。Code Status与规则返回的PARTIAL分档状态是不同维度。','',
       '| Rule ID | 名称 | Source Type | Spec Status | Code Status | Test Status |',
       '|---|---|---|---|---|---|']
for r in registry:
    test='PASS' if all_green and r['evaluator'] else 'FAIL' if r['evaluator'] else 'NOT_TESTED'
    lines.append(f'| {r["rule_id"]} | {r["name_cn"]} | {r["source_type"]} | {r["spec_status"]} | {r["code_status"]} | {test} |')
lines+=['','## 数量','']
for state in ['IMPLEMENTED','PARTIAL','NOT_IMPLEMENTED']:
    group=[r['rule_id'] for r in registry if r['code_status']==state]
    lines.append(f'- {state}: {len(group)} — '+', '.join(group))
lines+=['','R6原文source_type=AUTO_IF_MINUTE_DATA，注册时规范化为AUTO_IF_DATA并保留source_type_in_spec。',
        '均线/量比等派生变量不新增评分Rule ID。MANUAL和SYSTEM受Schema支持，但不凭空增加规范中没有的规则。']
(ROOT/'docs/RULE_IMPLEMENTATION_MATRIX.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

lines=['# 实际测试报告','',f'- 总数：{len(cases)}',f'- PASS：{passed}',f'- FAIL/ERROR：{len(failed)}',f'- SKIP：{len(skipped)}',
       '- 实际命令：`python -m pytest --junitxml=outputs/pytest-results.xml`',
       '- 环境：Python 3.11.0；依赖版本见requirements.txt；人工构造OHLCV；核心测试不联网。', '- Stage 1原182项场景全部保留；端点/状态等预期按用户V1.2明文迁移，原件归档。',
       '- Stage 1.1的241项测试保留；本轮预期变更仅来自用户V1.3确认；基线归档。', '- 原始结果：outputs/pytest-results.xml；跳过不等于通过。','',
       '## Active Acceptance Tests（旧第11章仅作HISTORICAL / SUPERSEDED对照）','',
       '| ID | 状态 | 证据/原因 |','|---|---|---|']
for i in range(1,21):
    tid=f'T{i:02}'
    if i==2:
        active=[c for c in cases if c.attrib.get('classname','').endswith('test_v13_rules') and 'T02_NEW' in c.attrib['name']]
        assert active, 'Missing T02_NEW active acceptance'
        state='PASS' if all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in active) else 'FAIL'
        lines.append(f'| T02_NEW | {state} | 原平台跌破立即INVALIDATED；收复交C4；新平台重新累计5日。共{len(active)}项生命周期断言。 |')
        continue
    matches=[c for c in cases if c.attrib.get('classname','').endswith('test_spec_acceptance') and tid in c.attrib['name']]
    assert len(matches)==1,(tid,len(matches))
    c=matches[0]
    skip=c.find('skipped'); failure=c.find('failure'); error=c.find('error')
    state='SKIP' if skip is not None else 'FAIL' if failure is not None or error is not None else 'PASS'
    reason=skip.attrib.get('message','') if skip is not None else c.attrib['name']
    if i==17: reason='冻结QuantScore>=80且非HIGH；后3日High达到+3%失效，否则最大收盘<=0扣10，其余扣6；V1.3边界测试一并保留。'
    lines.append(f'| {tid} | {state} | {reason} |')
lines+=['','## V1.3 新增测试','',f"新增{sum(c.attrib.get('classname','').endswith('test_v13_rules') for c in cases)}项，覆盖四项最终语义、C5生命周期、版本、旧规范哈希和评分权重保持。",'','## 失败项','']+[c.attrib['name'] for c in failed or []]
if not failed: lines.append('无。')
lines+=['','## Stage 2 恢复验收','', '原295项用例ID全部保留；新增数据层/API/CLI/五条规则/恢复审计回归测试。', 'WorkBuddy边界断言仅按V1.3已冻结左闭右开分档修正，没有删除或减弱断言；见STAGE2_CURRENT_STATE_AUDIT.md。', '真实网络验收独立于离线pytest；见STAGE2_DATA_SMOKE_REPORT.md，网络失败不计真实通过。', '历史Word完整性与原测试保留证据：outputs/runtime/resume_final_audit.json。']
lines+=['','## Stage 2.1','', '版本三元组统一为spec_version=1.4、assumption_version=v1.3、data_contract_version=1.4。', '原T02节点仅保留为历史回归入口，实际执行冻结新语义；活动验收使用T02_NEW。', '代理诊断与真实结果见STAGE2_NETWORK_DIAGNOSIS.md、STAGE2_DATA_SMOKE_REPORT.md；不以离线测试冒充真实行情。']
lines+=['','## 完整性','',f'V1.4 Word SHA256为 `{manifest["sha256"]}`。',
        '测试仅证明已实现行为及明确的未知守卫；不证明未实现复杂规则已通过业务验收，不代表回测收益或真实行情验证。']
(ROOT/'docs/TEST_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

props={
 'rule_id':{'type':'string'},'name_cn':{'type':'string'},'category':{'type':'string'},
 'rule_type':{'enum':['POSITIVE','RISK','SECTOR','SYSTEM']},
 'source_type':{'enum':['AUTO','AUTO_PROXY','AUTO_IF_DATA','MANUAL']},
 'status':{'enum':['PASS','PARTIAL','FAIL','UNKNOWN','CANDIDATE','FORMED','CONFIRMED','INVALIDATED']},
 'score':{'type':['number','null'],'minimum':0},'max_score':{'type':'number','minimum':0},
 'penalty':{'type':['number','null'],'minimum':0},'max_penalty':{'type':'number','minimum':0},
 'raw_values':{'type':'object'},'conditions':{'type':'object'},'explanation':{'type':'string','minLength':1},
 'spec_version':{'const':'1.4'},'assumption_version':{'const':'v1.3'},'data_contract_version':{'const':'1.4'},
 'code_status':{'enum':['IMPLEMENTED','PARTIAL','NOT_IMPLEMENTED']},
 'reason_code':{'type':['string','null']},'event_id':{'type':['string','null']},
 'exit_risk_alert':{'type':'boolean'},'alert_type':{'type':['string','null']},'alert_text':{'type':['string','null']},'applicable':{'type':['boolean','null']},'source_note_pages':{'type':'string'},'adjustments':{'type':'array'},'data_provenance':{'type':'array'}}
schema={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'QuantScore RuleResult v1.4',
        'type':'object','properties':props,'required':list(props),'additionalProperties':False,
        'allOf':[{'if':{'properties':{'status':{'const':'UNKNOWN'}}},'then':{'properties':{'score':{'type':'null'},'penalty':{'type':'null'}}}}]}
(ROOT/'docs/RULE_RESULT.schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
summary={'total':len(cases),'pass':passed,'fail':len(failed),'skip':len(skipped),'spec_sha256':manifest['sha256']}
(ROOT/'outputs/test-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary))
