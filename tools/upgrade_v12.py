"""Versioned migration. The original DOCX and archived baseline stay immutable."""
from pathlib import Path
from zipfile import ZipFile
import hashlib, json, re, yaml
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
REQUEST=ROOT/'docs/V1_2_USER_REQUEST.txt'
SRC=ROOT/'docs/QuantScore_V1.1_机器可执行评分规则规范_用户规则补全版.docx'
DST=ROOT/'docs/QuantScore_V1.2_机器可执行评分规则规范_歧义清零版.docx'

def migrate():
    text=REQUEST.read_text(encoding='utf-8')
    (ROOT/'docs/V1_2_USER_REQUEST.txt').write_text(text,encoding='utf-8')
    p=yaml.safe_load((ROOT/'config/parameters.yaml').read_text(encoding='utf-8'))
    p.update(spec_version='1.2',assumption_version='v1.2')
    p['SYSTEM'].update(f1_coverage_cap=10,interval_convention='[a,b)',risk_empty_coverage=1.0)
    p['GLOBAL']['confirmed_close_trough_side']=2
    p['C5'].update(minimum_samples=5,m60_platform_max_distance_pct=0.08,near_fraction_min=0.80,scores=[0,4])
    p['C6'].update(weekly_monthly_trough_side_bars=2,scores_per_tf=1)
    p['E1'].update(small_bull_max=0.04,big_bull_return_min=0.05,small_bear_min=-0.03,doji_body_max=0.005,max_exceptions=1,scores=[0,4],transition_policy=None)
    p['E2'].update(high_zone_week_radius=2,scores=[0,4])
    p['E3'].update(damping_small_move_pct=0.05,small_move_fraction_min=0.80,minimum_group=3,scores=[0,2,3])
    p['F1-T'].update(open_board_ratio=0.98,scores=[0,8])
    p['F1-O'].update(one_word_pre_volume_ratio=1.20,one_word_max_turnover_pct=5.0,price_tolerance=0.002,one_line_range_max=0.005,one_t_low_ratio=0.98,one_t_turnover_max=10,volume_ratio_max=1.5,pre_days=3,scores=[0,2,5,6])
    p['F1-Y'].update(dragon_gate_confluence_pct=0.03,search_days=60,strong_start_policy=None,scores=[0,8])
    p['F3'].update(search_days=20,rise_reference_days=3,scores_by_days={2:8,3:7,4:7,5:6,6:6},candidate_score=3)
    p['R7'].update(should_rise_score_threshold=80,should_rise_observation_days=3,should_rise_min_upside_pct=0.03,penalty_policy=None,penalties=[6,10])
    p['R8'].update(penalties={'D':6,'W':10,'M':12})
    p['R12'].update(turnover_threshold=15,volume_threshold=3.0,penalties=[0,5,10])
    p['B3'].update(minimum_constituents=10,scores=[0,3])
    p['R4']['alert_text']='检测到双子顶卖出风险信号，请重点关注顶部结构及破位风险。'
    obsolete={'C5':['near_m60_upper_pct','platform_width_max','washout_reclaim_days_max','recent_end_days'],
              'E1':['small_negative_abs_max','big_bull_body_min'],
              'E2':['high_zone_price_ratio'],
              'E3':['daily_scan_days_min','daily_scan_days_max','weekly_scan_weeks_min','weekly_scan_weeks_max','range_width_max','avg_abs_return_max'],
              'F1-T':['close_position_min','lower_shadow_body_ratio_min','lower_shadow_prev_close_min'],
              'R7':['signal_positive_score_min','signal_coverage_min','signal_risk_penalty_max_exclusive','observation_days']}
    for rid,keys in obsolete.items():
        for key in keys: p[rid].pop(key,None)
    for rid in ('C2','D3'): p[rid].pop('ambiguous_boundaries',None)
    (ROOT/'config/parameters.yaml').write_text(yaml.safe_dump(p,allow_unicode=True,sort_keys=False),encoding='utf-8')
    registry=yaml.safe_load((ROOT/'config/scoring_rules.yaml').read_text(encoding='utf-8'))
    registry['spec_version']='1.2'
    for r in registry['rules']:
        r['spec_version']='1.2'; r['spec_status']='FROZEN_V1_2'
        r.setdefault('inherited_source_text_v1_1',r['source_text'])
    sections=re.split(r'(?m)^([一二三四五六七八九十]+、[^\n]+)\n',text)
    amendments=[]
    for i in range(1,len(sections),2):
        title=sections[i].strip(); body=re.sub(r'(?m)^=+\s*$','',sections[i+1]).strip()
        if title.startswith(('一、','十七、','十八、','十九、','二十、')): continue
        if title.startswith('十六、'): continue
        amendments.append((title,body))
    assert len(amendments)==14 and all(body for _,body in amendments)
    (ROOT/'docs/V1_2_AMENDMENTS.json').write_text(json.dumps(amendments,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in registry['rules']:
        matching=[body for title,body in amendments if r['rule_id'] in title]
        if matching:
            r['v1_2_override']='\n\n'.join(matching)
            r['definition']=r['v1_2_override']
        r['interval_convention']='[a,b) for continuous score tiers; explicit structural inequalities unchanged'
    from tools.v12_contracts import apply_contracts
    apply_contracts(registry)
    (ROOT/'config/scoring_rules.yaml').write_text(yaml.safe_dump(registry,allow_unicode=True,sort_keys=False),encoding='utf-8')
    return registry,amendments

def build_document(registry,amendments):
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    ET.register_namespace('w',ns)
    def el(tag,**attrs): return ET.Element('{'+ns+'}'+tag,{'{'+ns+'}'+k:v for k,v in attrs.items()})
    with ZipFile(SRC) as z:
        contents={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(contents['word/document.xml']); body=root.find('{'+ns+'}body')
    # ElementTree renames namespace prefixes. The original mc:Ignorable value
    # references literal prefixes no longer present in a newly authored body.
    root.attrib.pop('{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable',None)
    sect=body.find('{'+ns+'}sectPr')
    for child in list(body): body.remove(child)
    def para(text,style=None):
        node=el('p'); props=el('pPr')
        if style: props.append(el('pStyle',val=style))
        spacing=el('spacing',after='100',line='260',lineRule='auto'); props.append(spacing)
        if style: props.append(el('keepNext'))
        node.append(props); run=el('r'); rp=el('rPr'); rp.append(el('rFonts',ascii='Calibri',eastAsia='微软雅黑'))
        rp.append(el('sz',val={'Title':'36','Subtitle':'24','Heading1':'28','Heading2':'24','Heading3':'23'}.get(style,'21')))
        rp.append(el('color',val='000000')); run.append(rp)
        t=el('t'); t.text=text; run.append(t); node.append(run); body.append(node)
    para('QuantScore V1.2 机器可执行评分规则规范','Title')
    para('歧义清零版  Stage 1.1','Subtitle')
    para('本文件为QuantScore V1.2唯一规则真源。第一部分逐字固化用户本轮确认的规则，优先替代后续继承条款中的冲突定义。未改动的阈值、权重和规则沿用V1.1。原V1.1文件保留不变。')
    para('第一部分 V1.2冻结修订','Heading1')
    for title,content in amendments:
        para(title,'Heading2')
        # Keep the user wording, but remove chat-style one-word blank lines.
        lines=[s.strip() for s in content.splitlines() if s.strip()]
        for start in range(0,len(lines),14): para(' '.join(lines[start:start+14]))
    para('统一工程执行约定','Heading2')
    para('连续数值评分档位统一左闭右开。结构条件中明确的<=、>=、>、<保持用户原意；例如平台8%距离、颈线严格跌破、N板Low<M5不因此改写。确定的无适用前置为FAIL/0；到期结构为INVALIDATED/0；未来观察不足为UNKNOWN并附等待原因，不增造正式状态。')
    para('Coverage以已判断规则的最大分值计算，F1贡献为已判断子项最大max_score且不超过10，再应用F类15及其他类别封顶；所有7种确定状态计入。风险分母为本次应执行的风险规则全集（包括前置已判断不成立者、缺数据与未实现者）；分母为空时返回1并标记empty_execution_set。')
    para('局部峰谷确认不得读未来。尚缺右侧确认的峰可保留CANDIDATE，不提前升级。多结构按最近合法完整结构优先；双顶按P2最近、绝对峰差最小排序，再以P1最近作完全同值工程稳定排序。')
    para('周/月输入必须声明已完成周期，或由评价日之前已明确结束的日历周期聚合；不得把未来周期完成标记带入历史评价。日线输入视为已完成交易日。缺历史交易日或复权口径未确认必须明确UNKNOWN。')
    para('压力线的重要高点沿用已冻结LOCAL_PEAK(k=2)，不增造显著性指标。S4真实封停以close_raw>=真实limit_up_price判断，NEAR_LIMIT_UP仅为其他明文允许代理的规则使用。')
    para('V1.2活动规则契约','Heading2')
    from tools.v12_contracts import CONTRACTS
    for rid,(fields,window,pre,levels) in CONTRACTS.items():
        para(rid+' 活动定义','Heading3')
        para('字段：'+fields+'。窗口：'+window+'。前置：'+pre+'。')
        for condition,award in levels: para(condition+' → '+award)
    para('第二部分 继承的48条规则及原始评分依据','Heading1')
    para('以下保留V1.1原文以追溯每条规则。遇到与第一部分修订冲突的旧定义、旧分档端点、旧状态或旧窗口，以第一部分为准；旧文不具有覆盖修订条款的效力。未修改规则继续适用。')
    inherited=(ROOT/'docs/SPEC_EXTRACTED.txt').read_text(encoding='utf-8')
    para('继承的总架构 数据契约与全局定义','Heading2')
    base=inherited[inherited.index('2. 评分总架构'):inherited.index('S1｜')]
    for chunk in re.split(r'\n\s*\n',base):
        if chunk.strip(): para(' | '.join(x for x in chunk.splitlines() if x.strip()))
    for r in registry['rules']:
        para(r['rule_id']+' '+r['name_cn'],'Heading2')
        source=r['inherited_source_text_v1_1']
        chunks=re.split(r'(?m)^(?=\d+）)',source)
        for chunk in chunks:
            text=' | '.join(x.strip() for x in chunk.splitlines() if x.strip())
            if text: para(text)
    para('继承的风险等级 汇总和版本约束','Heading2')
    base=inherited[inherited.index('7. 去重、互斥与类别封顶'):]
    for chunk in re.split(r'\n\s*\n',base):
        if chunk.strip(): para(' | '.join(x for x in chunk.splitlines() if x.strip()))
    para('风险等级保持：RiskPenalty 0–7为LOW，8–19为MEDIUM，>=20为HIGH。高位换手>=30%、明显高位出货板、CONFIRMED双子顶同时出现高位异常量或换手，直接触发HIGH。风险分不占正向100分。')
    decisions=ROOT/'docs/USER_DECISIONS_REQUIRED.md'
    para('第三部分 待明确的交易语义与发布边界','Heading1')
    if decisions.exists():
        for line in decisions.read_text(encoding='utf-8').splitlines():
            if line.startswith('| U'):
                cells=[cell.strip() for cell in line.strip('|').split('|')]
                para(cells[0]+' '+cells[1],'Heading2'); para('待确认：'+cells[2]); para('已实现：'+cells[3])
            elif line.strip() and not line.startswith(('|','#')): para(line)
    else: para('R7新触发条件的两档扣分映射、E1过渡阳线计数、F1-Y强势突破谓词等待确认。相关未决分支不得冒充完整实现。')
    if sect is not None: body.append(sect)
    contents['word/document.xml']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    styles=ET.fromstring(contents['word/styles.xml'])
    styles.attrib.pop('{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable',None)
    for st in styles.findall('{'+ns+'}style'):
        if st.get('{'+ns+'}styleId') in ('Title','Subtitle','Heading1','Heading2','Heading3'):
            for prop in st.findall('.//{'+ns+'}color'):
                prop.attrib.clear(); prop.set('{'+ns+'}val','000000')
            for prop in st.findall('{'+ns+'}pPr'):
                for border in prop.findall('{'+ns+'}pBdr'): prop.remove(border)
    contents['word/styles.xml']=ET.tostring(styles,encoding='utf-8',xml_declaration=True)
    for n in contents:
        if n.startswith('word/header') or n.startswith('word/footer'):
            contents[n]=contents[n].replace(b'v1.1',b'v1.2').replace(b'V1 ',b'V1.2 ')
    with ZipFile(DST,'w') as z:
        for n,data in contents.items(): z.writestr(n,data)
    print('V1.2 DOCX created',DST.name,hashlib.sha256(DST.read_bytes()).hexdigest())

if __name__=='__main__':
    if yaml.safe_load((ROOT/'config/parameters.yaml').read_text(encoding='utf-8'))['spec_version']!='1.2':
        raise SystemExit('Historical V1.2 migration is disabled for the V1.3 workspace; use archived baseline for reproduction.')
    registry,amendments=migrate()
    build_document(registry,amendments)
