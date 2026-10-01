# Stage 3B.1 B1/B2 活动定义冻结

基线8df39e4775a18fca11547959df1bf57c9fcf31bc，HEAD=origin/main。当前规范SPEC_V1_4_EXTRACTED.txt第91/141行统一连续分档左闭右开，覆盖SPEC_EXTRACTED.txt中的旧端点；第351–374行定义B1/B2。STAGE3B_RULE_FREEZE/RESULT与RULE_AMBIGUITIES的活动结案规则共同审计。

| 规则 | 前置 | 分档 | 最大分 | 无法评分 |
|---|---|---|---|---|
| B1 | primary industry明确；同日完整SectorHeatResult VALID；coverage>=80% | <50:0；[50,60):2；[60,70):4；[70,75):6；[75,85):7；>=85:8 | 8 | UNKNOWN / score=None，保留具体数据状态 |
| B2 | primary industry明确；股票与行业qfq五日数据完整；同六个端点交易日、相同起止和评价日 | <0:0；[0,.01):1；[.01,.04):2；[.04,.08):3；>=.08:4 | 4 | UNKNOWN / score=None，保留具体数据状态 |

B2公式stock_return_5d-sector_return_5d；0得1、8%得4来自活动统一端点，不采用旧<=0或>8%端点。无SEMANTIC_GAP。

V1只取BaoStock当前primary industry，概念及多行业最大/平均不参与。映射含provider/as_of/provenance；当前归属无法证明历史归属，对历史请求不假造point-in-time映射。离线存档回放仅使用该存档声明的归属时点，标注archived-current-snapshot。

B1不把available_score当完整Heat，H61等样本不足必须None。B2可以在B1不可用但行业五日收益本身完整时独立评分。RuleResult继续用既有UNKNOWN，raw_values记录DataStatus及失败原因，不增加新评分枚举。

ScoreEngine保持原算法、B类15分上限、风险与Coverage定义；S1–S7不进入个股总分，只映射B1一次。请求中构建一次行业上下文供B1/B2共享。CLI/API增加industry_context字段，旧字段不删除。
