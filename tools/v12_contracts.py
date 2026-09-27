"""Active V1.2 contracts. Legacy prose is retained only under inherited_* keys."""
CONTRACTS={
 'C5':('close_adj、high_adj、low_adj、M60','当前结尾至少5个完整交易日；最多250日工程搜索','至少5日，全部close>=M60且至少80%日0<=close/M60-1<=8%',[
     ('完整平台条件满足','+4'),('最近5日内任一close<M60或无有效平台','0'),('M60历史不足','UNKNOWN')]),
 'C6':('daily close_adj；已完成weekly/monthly close_adj','D120/W52/M36工程窗口；三周期均前后2根确认','最近两个严格收盘波谷已确认且第二波谷高于第一波谷',[
     ('日线安全带未被周期收盘跌破','+1'),('完整周线安全带未被周期收盘跌破','+1'),('完整月线安全带未被周期收盘跌破','+1'),('对应周期收盘跌破','0 / INVALIDATED'),('数据或完整周期不足','UNKNOWN')]),
 'E1':('open_adj、high_adj、low_adj、close_adj、M60、C5平台、position_120','最近60日工程扫描；连续至少7日','开始于LOW_ZONE；未同时突破M60与起飞平台',[
     ('连续>=7日；小阳0<日收益<4%；小阴/十字星合计<=1；无>=5%大阳','+4'),('尚未满7日，未破坏','CANDIDATE 0'),('出现>=5%大阳、<=-3%大跌或第2根例外','0 / INVALIDATED'),('4%~5%过渡阳线计数待用户确认','UNKNOWN')]),
 'E2':('完整weekly high_adj/low_adj/close_adj/volume','最近52周，至少20周','最近已结束且已确认局部高点；高点后底部位置<=35%',[
     ('底部完整周成交量>高点前后各2周最大周量','+4 / CONFIRMED'),('底部但周量未超过参考量','CANDIDATE 0'),('非底部或没有前轮高点','0'),('完整周数据不足','UNKNOWN')]),
 'E3':('close_adj、volume','全部已有可用日线；不设固定持续天数','至少3上涨日和3下跌日，至少80%日abs(return)<=5%',[
     ('小幅波动且上涨均量/下跌均量>=1.15','+3'),('小幅波动且1<上涨均量/下跌均量<1.15','+2'),('样本充分但价格/量价方向不成立','0'),('上涨/下跌各3日证据不足','UNKNOWN')]),
 'F1-N':('close_adj/high_adj/low_adj、M5、volume、close_raw、limit_up_price','最近20日候选；换手2~6日','按first_start由近到远；优先最近完整合法结构',[
     ('合法启动后2~6日换手low始终>=M5且二次启动','+10 / CONFIRMED'),('合法换手>=2日且尚未再启动','CANDIDATE +4'),('任一换手日low<M5','0 / INVALIDATED'),('超过6日仍未再启动','0 / INVALIDATED'),('关键数据/后续观察不足','UNKNOWN')]),
 'F1-T':('open_raw/high_raw/low_raw/close_raw、limit_up_price','当前完整交易日','真实涨停价可用；Open无涨停前置',[
     ('close和high达到涨停范围且low<=limit_up*0.98','+8'),('完整T形或收盘封停不成立','0'),('价格/涨停价缺失','UNKNOWN')]),
 'F1-O':('raw OHLC、limit_up_price、volume、turnover_rate、HIGH_ZONE','前3日与前20日均量均不含当日','非高位；沿用一字/一字T价格结构',[
     ('一字板；前3日均量<=前20日1.2倍；换手<=5%；当前量比<=1.5','+6'),('一字T；此前无放量且换手<=5%','+5'),('形态成立但此前已明显放量；无异常成交','PARTIAL +2'),('R12异常成交或价格结构不成立','0'),('此前量干净但5%<换手<15%的分值待明确','UNKNOWN')]),
 'F3':('daily OHLCV、M5、limit_up_price、HIGH_ZONE','涨停后2~6日整理','低量涨停后高位；整理均量/此前3日拉升均量>=1.2；盘中M5不破',[
     ('2日整理后明确继续上涨','+8'),('3~4日整理后明确继续上涨','+7'),('5~6日整理后明确继续上涨','+6'),('合法整理尚未确认上涨','CANDIDATE +3'),('盘中M5破位或超过6日未再启动','0 / INVALIDATED')]),
 'F1-Y':('raw/adjusted OHLCV、M5/M60、真实limit_up/limit_down','突破后紧随1日假摔，再观察最多3日恢复','已确认最近合法两高点压力线与M60距离<=3%；close同时越过两线且强势',[
     ('共同龙门强势突破、次日近涨停开近跌停收巨量、3日内恢复M5及实体50%','+8 / CONFIRMED'),('假摔已发生且等待恢复','CANDIDATE 0'),('3日未恢复','0 / INVALIDATED'),('非涨停强势突破量能定义待明确或关键数据不足','UNKNOWN')]),
 'R7':('冻结V1.2评分快照、信号日close、之后3日high_adj/close_adj','历史信号后3个完整交易日','冻结QuantScore>=80且Risk Level!=HIGH',[
     ('未来3日最高价<信号close*1.03且最大收盘收益<=0','-10'),('触发风险且0<最大收盘收益<2%（继承明确分档）','-6'),('达到信号close*1.03','0 / INVALIDATED'),('触发但最大收盘收益>=2%的扣分映射待明确','UNKNOWN'),('未来3日未完成','UNKNOWN / AWAITING_FORWARD_CONFIRMATION')]),
 'R8':('C6分周期收盘波谷支撑与完整周期close','已完成日/周/月周期','对应周期已形成上升收盘安全带',[
     ('日线收盘跌破','-6'),('周线收盘跌破','-10'),('月线收盘跌破','-12'),('多周期破位','只取最高档'),('Low破但Close收回','0')])}


def apply_contracts(registry):
    for r in registry['rules']:
        if r['rule_id']=='S4':
            r['definition']='limit_count = count(close_raw >= limit_up_price)\nlimit_ratio = limit_count / valid_components'
            r['v1_2_override']='V1.2统一工程执行约定：S4真实封停以close_raw>=真实limit_up_price判断；NEAR_LIMIT_UP仅用于明文允许代理的其他规则。'
            r['source_text']=r['v1_2_override']
        if r['rule_id'] not in CONTRACTS: continue
        fields,window,pre,levels=CONTRACTS[r['rule_id']]
        r['required_fields']=[fields]; r['lookback']=window; r['prerequisites']=[pre]
        r['scoring_levels']['inherited_spec_text_v1_1']=r['scoring_levels'].get('inherited_spec_text_v1_1',r['scoring_levels']['spec_text'])
        r['scoring_levels']['spec_text']='条件\n得分/扣分\n'+'\n'.join(x for pair in levels for x in pair)
        r['source_text']=r.get('v1_2_override',r['definition'])
