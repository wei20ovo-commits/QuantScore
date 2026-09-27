"""One-way V1.3 freeze; V1.1 and V1.2 documents are immutable."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
from copy import deepcopy
import hashlib, json, re, yaml

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'docs/QuantScore_V1.2_机器可执行评分规则规范_歧义清零版.docx'
DST=ROOT/'docs/QuantScore_V1.3_机器可执行评分规则规范_最终语义冻结版.docx'
FINAL={
 'R7':('U01 R7 该涨不涨',[
  '前提为历史冻结QuantScore>=80且Risk Level!=HIGH。观察信号日之后3个完整交易日，禁止未来数据回写历史评分。信号日及不足3日返回UNKNOWN，reason_code=AWAITING_FORWARD_CONFIRMATION。',
  '三日max(High)<signal_close*1.03时触发。max_close_return<=0扣10；0<max_close_return<3%且max_high_return<3%扣6。0~3%没有断档。任一日High>=signal_close*1.03，完整观察后返回INVALIDATED、扣0。',
  '快照保留信号日期、信号收盘价、QuantScore、Risk Level、规范版本及证据摘要；信号价格必须与当时复权口径一致。不同版本快照不得静默混用。']),
 'E1':('U02 E1 底部小连阳',[
  '连续至少7个交易日。普通小阳0<daily_return<4%；过渡阳线4%<=daily_return<5%，可计入连续长度，但整个连续段最多1根。daily_return>=5%大阳立即终止当前段。',
  '小阴线-3%<daily_return<=0；十字星abs(close-open)/previous_close<=0.5%。小阴/十字星合计最多1根，与过渡阳线是两个独立容错槽位。过渡阳线按收益优先归类，不再占用十字星槽位；其余满足十字星定义者使用例外槽位。',
  '第2根过渡阳线、第2根小阴/十字星、>=5%大阳或<=-3%大跌终止本段并清零；不能截掉破坏日拼接旧段，后续交易日可重新累计。3.999%普通小阳，4.000%和4.999%过渡阳，5.000%大阳。',
  '保留LOW_ZONE和已有工程扫描窗口。合法底部连续段得4分，未满7日得0。正式启动仅Close>M60且Close>C5.platform_high；单独站上M60不算启动。']),
 'F1-Y':('U03 F1-Y 鲤鱼跃龙门与单日假摔',[
  '突破日前至少两个已确认重要局部高点，沿用LOCAL_PEAK左右各2根，确认不得读取突破日或未来数据。最近合法两高点连线外推至突破日，得到resistance_price。',
  'abs(resistance_price-M60_price)/M60_price<=3%构成dragon_gate_zone。多个组合按第二高点最近、第一高点最近的顺序检查；最近组合不共振就继续向前，选最近合法共振组合。',
  'dragon_gate_breakout = Close>resistance_price AND Close>M60_price。仅High突破不成立。没有涨幅>=7%、量比>=1.2、NEAR_LIMIT_UP或额外突破幅度门槛；这些旧强势条件全部废止，不得再次用于F1-Y突破。突破本身不要求成交量或涨跌停价。',
  '假摔必须紧随突破的下1个交易日，持续仅1天。保留open_near_limit_up、close_near_limit_down、large_drop、huge_volume配置。开盘>=涨停价*0.98，收盘<=跌停价*1.02；实体跌幅>=12%，或实际涨跌停区间较窄时按接近实际跌停适配；量比>=2.0或假摔成交量>=突破日1.5倍。',
  '假摔后1~3日内Close>M5且收复假摔实体至少50%才CONFIRMED +8；等待恢复CANDIDATE 0，满3日未恢复INVALIDATED 0。恢复条件不反向修改突破定义。无假摔不发放完整形态分。']),
 'F1-O':('U04 F1-O 一字板与一字T',[
  '沿用非HIGH_ZONE前置和价格结构：open/high/close均距真实涨停价不超过0.2%；一字板(high-low)/limit<=0.5%，一字T low<=limit*0.98。前3日均量<=前20日均量*1.2为pre_volume_clean，两段均不含当日。',
  '价格成立、前期量干净且未触发R12：换手<=5%，一字板+6、一字T+5；5%<换手<15%，PARTIAL +2。前期已明显放量但未触发R12，PARTIAL +2。',
  '换手>=15%进入R12异常判定；R12沿用换手>=15%或量比>=3.0任一成立扣5，两项同时成立扣10。R12成立时F1-O正分清零，不能保留+2再扣风险。旧一字T换手<=10%及当前量比<=1.5满分门槛被本轮完整分档替代；价格结构未改。']),
 'C5':('C5 连续平台与T02_NEW',[
  '连续至少5个交易日，100%收盘Close>=M60，至少80%日满足0<=Close/M60-1<=8%；不增加成交量条件。platform_high为该连续有效平台段的最高High。',
  '任一日Close<M60，旧平台立即INVALIDATED、正分清零。TERMINATED仅为历史描述，不新增统一状态枚举。跌破日及后续收复不能并入原平台；重新站上后从当日重新累计，新平台必须再次连续>=5日。',
  '1~3日快速收复仅交C4按其原有完整条件判断，不修改C4的阈值、强度或确认规则。新C5只有4日时不得得分；第5日重新满足条件才得4分。保留最近跌破日期、旧平台起止日期、新段起点和连续长度。',
  'T02_NEW：平台先形成；第6日Close<M60则原平台INVALIDATED且0分；2日后强势收复可由C4命中，但C5不立即成立；收复后4日仍0，第5日满足条件后新平台+4。所有旧C5洗盘并入同一平台文字均为SUPERSEDED_BY_V1_3。'])}

LEVELS={
 'R7':[('三日High均未达+3%且最大收盘收益<=0','-10'),('三日High均未达+3%且0<最大收盘收益<3%','-6'),('任一High达到+3%（完成三日观察）','0 / INVALIDATED'),('未满3个完整交易日','UNKNOWN / AWAITING_FORWARD_CONFIRMATION')],
 'E1':[('底部连续>=7日，过渡阳<=1，小阴/十字星<=1，尚未正式启动','+4'),('连续不足7日且未破坏','CANDIDATE 0'),('第2根过渡阳/例外、>=5%大阳或<=-3%大跌','INVALIDATED 0'),('数据不足','UNKNOWN')],
 'F1-Y':[('收盘同时突破共振区两线、紧随单日假摔、3日内恢复','CONFIRMED +8'),('突破后等待假摔或等待恢复','CANDIDATE 0'),('假摔后3日未恢复','INVALIDATED 0'),('无共振或收盘未突破或无假摔','0'),('必要数据不足','UNKNOWN')],
 'F1-O':[('未触发R12且前期量干净，换手<=5%，一字板','+6'),('未触发R12且前期量干净，换手<=5%，一字T','+5'),('未触发R12且形态成立，5%<换手<15%或前期已放量','PARTIAL +2'),('R12成立或价格形态不成立','0'),('必要数据不足','UNKNOWN')],
 'C5':[('连续>=5日全close>=M60且至少80%距M60<=8%','+4'),('旧平台任一收盘跌破M60','INVALIDATED 0'),('收复后新连续段不足5日或无平台','0'),('M60历史或必要数据不足','UNKNOWN')]}

def freeze_config():
    rp=ROOT/'config/scoring_rules.yaml'; pp=ROOT/'config/parameters.yaml'
    registry=yaml.safe_load(rp.read_text(encoding='utf-8')); p=yaml.safe_load(pp.read_text(encoding='utf-8'))
    registry['spec_version']='1.3'; p.update(spec_version='1.3',assumption_version='v1.3')
    p['E1'].pop('transition_policy',None); p['E1']['max_transitions']=1
    p['R7'].pop('penalty_policy',None); p['R7'].pop('min_expected_close_gain',None)
    p['F1-Y'].pop('strong_start_policy',None)
    for key in ('volume_ratio_max','one_t_turnover_max'): p['F1-O'].pop(key,None)
    for r in registry['rules']:
        r['spec_version']='1.3'; r['spec_status']='FROZEN_V1_3'
        if r['rule_id'] in FINAL:
            rid=r['rule_id']; r.setdefault('inherited_contract_v1_2',{k:deepcopy(r[k]) for k in ('definition','prerequisites','invalidation_rules','unknown_conditions','scoring_levels','source_text')})
            if 'v1_2_override' in r: r['inherited_override_v1_2']=r.pop('v1_2_override')
            definition='\n'.join(FINAL[rid][1])
            r['definition']=definition; r['source_text']=definition; r['v1_3_override']=definition
            r['prerequisites']=[FINAL[rid][1][0]]
            r['invalidation_rules']='见V1.3最终定义：'+definition
            r['unknown_conditions']=['缺少必要数据、历史长度不足或未来确认期未结束；不再因用户语义返回UNKNOWN。']
            r['explanation_template']='V1.3 '+r['name_cn']+'：原始数据={raw_values}；逐项条件={conditions}；状态={status}；得分={score}；扣分={penalty}。'
            r['scoring_levels']['spec_text']='条件\n得分/扣分\n'+'\n'.join(x for pair in LEVELS[rid] for x in pair)
            r['code_status']='IMPLEMENTED'
            if rid=='R7': r['required_fields']=['冻结V1.3评分快照、信号日close、后3日high_adj/close_adj']
        p[r['rule_id']]['spec_definition']=r['definition']; p[r['rule_id']]['spec_scoring_levels']=r['scoring_levels']['spec_text']
    rp.write_text(yaml.safe_dump(registry,allow_unicode=True,sort_keys=False),encoding='utf-8')
    pp.write_text(yaml.safe_dump(p,allow_unicode=True,sort_keys=False),encoding='utf-8')

def build_document():
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; ns={'w':w}
    ET.register_namespace('w',w)
    with ZipFile(SRC) as z: files={n:z.read(n) for n in z.namelist()}
    tree=ET.fromstring(files['word/document.xml']); body=tree.find('w:body',ns)
    old=list(body); section=body.find('w:sectPr',ns)
    for child in old: body.remove(child)
    def para(text,style=None):
        node=ET.SubElement(body,'{'+w+'}p'); props=ET.SubElement(node,'{'+w+'}pPr')
        if style:
            ET.SubElement(props,'{'+w+'}pStyle',{'{'+w+'}val':style}); ET.SubElement(props,'{'+w+'}keepNext')
        ET.SubElement(props,'{'+w+'}spacing',{'{'+w+'}after':'100','{'+w+'}line':'260','{'+w+'}lineRule':'auto'})
        run=ET.SubElement(node,'{'+w+'}r'); rp=ET.SubElement(run,'{'+w+'}rPr')
        ET.SubElement(rp,'{'+w+'}rFonts',{'{'+w+'}ascii':'Calibri','{'+w+'}eastAsia':'微软雅黑'})
        ET.SubElement(rp,'{'+w+'}sz',{'{'+w+'}val':{'Title':'36','Heading1':'28','Heading2':'24'}.get(style,'21')})
        ET.SubElement(rp,'{'+w+'}color',{'{'+w+'}val':'000000'})
        ET.SubElement(run,'{'+w+'}t').text=text
    para('QuantScore V1.3 机器可执行评分规则规范','Title')
    para('最终语义冻结版 Stage 1.2','Heading1')
    para('本文件为新的Single Source of Truth。第一部分是用户最终确认，优先于任何继承文字；V1.1和V1.2原文件保持不变。U01至U04全部RESOLVED_IN_V1_3，resolution_source=USER_CONFIRMED。No unresolved user-defined trading semantics remain in V1.3.')
    para('第一部分 最终冻结规则','Heading1')
    for rid,(title,paragraphs) in FINAL.items():
        para(title,'Heading2')
        for text in paragraphs: para(text)
        for condition,award in LEVELS[rid]: para(condition+' → '+award)
    para('状态 版本与范围','Heading2')
    para('统一状态仍为PASS/PARTIAL/FAIL/UNKNOWN/CANDIDATE/FORMED/CONFIRMED/INVALIDATED。所有新结果spec_version=1.3、assumption_version=v1.3。UNKNOWN仅因数据不足、无可靠历史证据、确认期未结束、未实现规则或未提交人工证据；不再返回USER_DECISION_REQUIRED。未实现不是语义歧义。权重不变。')
    para('R4仍按最近P2、同P2绝对峰差最小选择；从CANDIDATE保留exit_risk_alert与相应扣分，INVALIDATED撤销。C6/E2/E3/F1-N/F1-T/F3/R8/R12和Coverage的V1.2修订继续有效。本阶段不接真实行情、不自动选股、不做前端或回测。')
    para('第二部分 继承规则与历史对照','Heading1')
    para('未修改定义沿用V1.2。被替代的段落逐段标SUPERSEDED_BY_V1_3，只用于历史对照，禁止据其生成当前代码或验收预期。继承的原始V1.1条款还须服从V1.2活动定义；其旧窗口、分档或状态不可覆盖第一部分。')
    active=False; changed=False; legacy=False
    for node in old:
        if node is section: continue
        text=''.join(t.text or '' for t in node.findall('.//w:t',ns))
        if text.startswith('第三部分 待明确'): break
        if text.startswith(('QuantScore V1.2','歧义清零版','本文件为QuantScore V1.2')): continue
        if text=='第二部分 继承的48条规则及原始评分依据': legacy=True
        heading=node.find('w:pPr/w:pStyle',ns)
        if heading is not None:
            rid=text.split(' ')[0]
            changed=rid in FINAL or bool(re.match(r'(四、C5|六、E1|十一、F1-O|十三、F1-Y|十四、R7)',text))
        obsolete=changed or 'T02 |' in text or 'C5.washout' in text or 'v1.1允许起飞前跌破' in text
        if obsolete:
            para('SUPERSEDED_BY_V1_3 历史对照：'+text)
        else:
            body.append(deepcopy(node))
    para('第三部分 最终验收与用户决策结案','Heading1')
    para('T02_NEW取代旧T02：已形成平台跌破当日INVALIDATED，收复交C4，新C5从收复日重新连续累计5日。R7测试-10/-6/盘中+3%失效和不足3日等待；E1测试3.999/4.000/4.999/5.000及两个独立槽位；F1-Y测试2%低量突破、仅盘中突破失败及多组合；F1-O测试4.9/5.0/5.1/14.9/15.0和R12清零。')
    para('U01 R7、U02 E1、U03 F1-Y、U04 F1-O：RESOLVED_IN_V1_3；resolution_source=USER_CONFIRMED。No unresolved user-defined trading semantics remain in V1.3.')
    body.append(deepcopy(section)); files['word/document.xml']=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
    for name,data in list(files.items()):
        if name.startswith(('word/header','word/footer')) and name.endswith('.xml'):
            files[name]=data.replace(b'V1.2',b'V1.3').replace(b'v1.2',b'v1.3')
    with ZipFile(DST,'w',ZIP_DEFLATED) as z:
        for name,data in files.items(): z.writestr(name,data)
    print(DST.name,hashlib.sha256(DST.read_bytes()).hexdigest())

if __name__=='__main__':
    build_document()
    freeze_config()
