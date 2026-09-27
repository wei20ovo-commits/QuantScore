# QuantScore V1.3 歧义结案

No unresolved user-defined trading semantics remain in V1.3.

A类规则语义已经冻结。B类数据不可得仍可UNKNOWN；C类未实现规则仍为NOT_IMPLEMENTED，不能冒充语义歧义。以下追加结案，不删除历史。

| ID | resolution_status | resolution_source | 最终规则 |
|---|---|---|---|
| A01 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 所有连续评分区间左闭右开；0、0.5%、1.10等得到明确分档。 |
| A02 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 所有7种确定状态均计入已判断。 |
| A03 | RESOLVED_IN_V1_3 | USER_CONFIRMED | F1有效上限10，全部类别先封顶再除以100。 |
| A04 | RESOLVED_IN_V1_3 | USER_CONFIRMED | C4满3日仍未确认且无有效其他事件：FAIL/0。 |
| A05 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 确认期为突破后的第1~3日；快速收复为共同位置前置且(>=7%或接近涨停)。 |
| A06 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 右侧不足2根的P2仅CANDIDATE；不能提前确认。 |
| A07 | RESOLVED_IN_V1_3 | USER_CONFIRMED | R4选P2最近、同P2绝对高差最小；完全同值再以P1最近作稳定排序。 |
| A08 | RESOLVED_IN_V1_3 | USER_CONFIRMED | failed_breakout仅是P2未有效突破的说明字段，不新增阈值或扣分。 |
| A09 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 输入契约明确同一复权口径，缺该数据声明属于数据不足。 |
| A10 | RESOLVED_IN_V1_3 | USER_CONFIRMED | R9完整历史依赖33根收盘；不会以短均线替代。 |
| A11 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 过期为INVALIDATED；明确不适用为FAIL；等待未来数据为UNKNOWN加等待原因。 |
| A12 | RESOLVED_IN_V1_3 | USER_CONFIRMED | N多起点最近完整合法结构优先，不因候选个数返回UNKNOWN。 |
| A13 | RESOLVED_IN_V1_3 | USER_CONFIRMED | C5任何收盘跌破立即终止；收复归C4，新平台重新连续累计5日；旧T02被T02_NEW替代。 |
| A14 | RESOLVED_IN_V1_3 | USER_CONFIRMED | T板继承V1.2；一字板/一字T执行V1.3完整换手分档，R12成立清零。 |
| A15 | RESOLVED_IN_V1_3 | USER_CONFIRMED | E2最近已结束高点±2周；E3本轮明确的日收益检测按日线实现，原振幅收敛假设删除。 |
| A16 | RESOLVED_IN_V1_3 | USER_CONFIRMED | F1-Y收盘同时越过共振压力线和M60即突破；不设涨幅、量比或近涨停门槛；假摔恢复另判。 |
| A17 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 风险分母为本次应执行全部风险，前置不成立为已判断；空集合覆盖率1并标记。 |
| A18 | RESOLVED_IN_V1_3 | USER_CONFIRMED | S4仅登记，真实封停仍由真实涨停价判定，不以统一固定涨幅替代；尚未执行。 |
| U01 | RESOLVED_IN_V1_3 | USER_CONFIRMED | R7触发内<=0扣10，其余0~3%扣6；High达到3%失效。 |
| U02 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 1根过渡阳计入7日，独立于1根小阴/十字星槽位。 |
| U03 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 仅Close严格越过共振区两线，无强势涨幅/量能门槛。 |
| U04 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 5%<换手<15%部分2分，R12成立清零。 |
| C5_T02 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 旧洗盘同平台逻辑SUPERSEDED_BY_V1_3；重建必须重新5日。 |

## 历史台账 原文保留 不代表当前未决状态

# QuantScore V1.2 歧义处理台账

历史记录完整保留。状态表示原条目已通过统一原则或新定义处置；新的真正交易语义缺口集中在USER_DECISIONS_REQUIRED.md。

| ID | Status | V1.2冻结处理 |
|---|---|---|
| A01 | RESOLVED_IN_V1_2 | 所有连续评分区间左闭右开；0、0.5%、1.10等得到明确分档。 |
| A02 | RESOLVED_IN_V1_2 | 所有7种确定状态均计入已判断。 |
| A03 | RESOLVED_IN_V1_2 | F1有效上限10，全部类别先封顶再除以100。 |
| A04 | RESOLVED_IN_V1_2 | C4满3日仍未确认且无有效其他事件：FAIL/0。 |
| A05 | RESOLVED_IN_V1_2 | 确认期为突破后的第1~3日；快速收复为共同位置前置且(>=7%或接近涨停)。 |
| A06 | RESOLVED_IN_V1_2 | 右侧不足2根的P2仅CANDIDATE；不能提前确认。 |
| A07 | RESOLVED_IN_V1_2 | R4选P2最近、同P2绝对高差最小；完全同值再以P1最近作稳定排序。 |
| A08 | RESOLVED_IN_V1_2 | failed_breakout仅是P2未有效突破的说明字段，不新增阈值或扣分。 |
| A09 | RESOLVED_IN_V1_2 | 输入契约明确同一复权口径，缺该数据声明属于数据不足。 |
| A10 | RESOLVED_IN_V1_2 | R9完整历史依赖33根收盘；不会以短均线替代。 |
| A11 | RESOLVED_IN_V1_2 | 过期为INVALIDATED；明确不适用为FAIL；等待未来数据为UNKNOWN加等待原因。 |
| A12 | RESOLVED_IN_V1_2 | N多起点最近完整合法结构优先，不因候选个数返回UNKNOWN。 |
| A13 | RESOLVED_IN_V1_2 | C5的5日、80%、0~8%和全部收盘>=M60已冻结；跌破回收归C4。 |
| A14 | RESOLVED_IN_V1_2 | T完整形状已明确；一字价格接近沿用0.2%，旧几何模糊不再使用。新换手分值问题另列U04。 |
| A15 | RESOLVED_IN_V1_2 | E2最近已结束高点±2周；E3本轮明确的日收益检测按日线实现，原振幅收敛假设删除。 |
| A16 | RESOLVED_IN_V1_2 | 龙门共同区和单日假摔已定义；非涨停强势突破引用选择另列U03，不伪称完整。 |
| A17 | RESOLVED_IN_V1_2 | 风险分母为本次应执行全部风险，前置不成立为已判断；空集合覆盖率1并标记。 |
| A18 | RESOLVED_IN_V1_2 | S4仅登记，真实封停仍由真实涨停价判定，不以统一固定涨幅替代；尚未执行。 |

## V1.1历史原文

# QuantScore v1.1 规则歧义与保守处理

唯一真源为同目录 Word，本文是实现审计，不修改规范。以下未决条件不得凭经验补齐。`UNKNOWN` 的 score/penalty 均为 null；未实现规则也返回 UNKNOWN，但 reason_code 单独标识 NOT_IMPLEMENTED。

| ID | 原文位置与问题 | Stage 1 处理 |
|---|---|---|
| A01 | A3 的“-3%~0”和“0~+3%”同时包含0；C2的“-1%~0/0~+0.5%/+0.5%~+2%”端点重叠；D3的“0.90~1.10/1.10~1.30”重叠 | A3=0、C2=0或0.5%、D3=1.10返回 UNKNOWN / AMBIGUOUS_SPEC。相邻档明确使用>=或>的端点按明文处理。其他未实现规则的模糊区间原样保留。比较中的1e-12仅识别浮点端点，不是交易容差。 |
| A02 | 8.1 PositiveCoverage只列PASS/PARTIAL/FAIL，未列得分的CANDIDATE及CONFIRMED等状态 | 严格按列出的三种状态计算；不把形态状态改名计入。报告状态计数及已判定最大分值。 |
| A03 | F1各子项最大分值相加超过主启动上限；F3使F类潜在最大值进一步增加，但8.1未规定Coverage组内封顶 | 原文公式分母仍为100；若分子超过100，精确Coverage返回null并附歧义，不暗中换分母或截断。评分本身仍执行F1互斥与F类15分封顶。 |
| A04 | C4只给“confirmed/reclaim/仅cross_up且尚未确认/无事件”；未说明3日已结束且不足2日站上的假突破得分 | 若无另一个明确满分事件覆盖该歧义，返回UNKNOWN，不奖励为有效突破。记录过期未确认事件与原始价格。 |
| A05 | C4“cross_up后3日内”未说明是否包含穿越当日；reclaim的“且…或”缺括号 | 按“后”读取之后第1~3日，穿越日不计入；按共同前置位置条件且(强势日涨幅或接近涨停)处理。此为语法解析，不添加阈值；写入测试和解释。 |
| A06 | R4要求LOCAL_PEAK右侧2日确认，同时明确最新日P2可CANDIDATE；没有规定只有1根右侧K线时状态 | 最新日按明确例外给候选峰，不能标确认；有1根右侧K线而未满2根时UNKNOWN。满2根后才按状态机判定。 |
| A07 | R4未规定同一窗口多组有效P1/P2的选择、事件过期、平顶的唯一峰选择 | 所有符合结构的组均保留证据；若多组可能影响结果则UNKNOWN，不自行取最新、最高或叠加。同一Rule ID只接受一个评价日结果；完全重复结果去重，冲突重复拒绝。 |
| A08 | R4正文没有单独定义名为failed breakout的附加条件或扣分 | 输出failed_breakout仅表示原文P2“未有效突破”的否定条件；不引入冲高回落比例或独立扣分。P2收盘>第一峰103%时按明文失效；在合法OHLC下该条件通常同时超出3%峰高差门槛，后续连续两日突破失效仍独立执行。 |
| A09 | R4写daily OHLC，又要求与M5/复权口径一致，未提供复权标记字段 | 接口要求显式metadata.adjustment_consistent=True并使用一致的*_adj序列。标记缺失/不一致均UNKNOWN。调用方必须提供同一口径且按评价日截断的数据。 |
| A10 | R9写不足30日UNKNOWN，但连续两日与2日内原单日事件恢复需要更早M30 | 完整判断需要33根收盘数据，以证明更早事件确为单日；不足不以短均线替代，返回UNKNOWN。连续两日破位不会冒充单日事件失效。 |
| A11 | 第3.4状态枚举未含EXPIRED/TERMINATED/PENDING/NOT_APPLICABLE，具体规则中却使用这些词 | 保留8种正式状态；尚不能可靠判断的分支状态UNKNOWN，补充reason_code（如EXPIRED/NOT_APPLICABLE），不擅自扩充正式状态或变为FAIL。 |
| A12 | F1-N最近20日可能存在多个first_start，未规定同一波段主启动选择与已确认事件有效期 | F1-N整体标PARTIAL。多起点默认UNKNOWN；可提供n_first_start_date指定要审计的事件，该起点仍必须通过自动公式验证。任何换手low<M5立即失效，不可恢复。该日期仅定位事件，不是人工PASS。 |
| A13 | C5“多数日”“部分阈值处工程边界”未量化；平台历史保留时长未定义 | C5 NOT_IMPLEMENTED；依赖其完整结构的规则不以简化平台替代。 |
| A14 | F1-T“几何仅部分满足”和“无明显T形”之间无明确分界；F1-O“接近涨停”分支细节不足 | F1-T/F1-O NOT_IMPLEMENTED；不自行规定+3/+2分的条件。 |
| A15 | E2存在多个上一轮局部高点时未给选择法；E3日周两个独立结果如何映射单项最大3分未明确 | E2/E3 NOT_IMPLEMENTED。已保存完整v1.1定义，绝不使用旧版固定缩量或逐级缩幅条件。 |
| A16 | F1-Y“强势突破日”没有完整谓词；large_drop被定义但未列入fake_fall_signature，且有实际跌停较小例外 | F1-Y NOT_IMPLEMENTED，不把普通小阴回踩当假摔。 |
| A17 | RiskCoverage的“当前应适用风险规则”在缺少前置数据时分母不可确定；无适用风险时0/0未定义 | applicable采用true/false/null。存在未决适用性或无分母时risk_coverage=null，同时给适用数量、未决数量、可确定的上下界。不把UNKNOWN踢出分母获得100%。 |
| A18 | S4公式使用0.995容差但冲突条款又禁止NEAR_LIMIT_UP当真实封板 | S4仅登记、未执行；板块模块未提前开发。 |

实现范围之外的规则均未声称完成。所有工程参数仍使用文档值。进一步补全需要明确上述歧义或新规范版本，不能由代码自行“优化”。
