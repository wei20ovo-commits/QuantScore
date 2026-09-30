# Stage 3B S1–S7正式规则冻结（编码前）

基线：fecf1a87ef1a7559e7f5c9b194fc1f6a8a244b63，HEAD=origin/main。版本1.4，assumption_version=v1.3。

优先级：本轮用户明确要求 > V1.4活动修订 > 继承的V1.3/V1.2活动修订 > 未被修改的V1.1条款。docs/SPEC_EXTRACTED.txt是V1.1历史抽取；当前依据为docs/SPEC_V1_4_EXTRACTED.txt。未用历史标题否定继承有效条款。

V1.4第91行统一所有连续分档为[a,b)，覆盖继承表格的旧>、<=端点；S1的0得5、2%得20，S2的0得6、6%得20。S4第145行取消旧0.995容差，必须真实收盘封停。S7 expected分母由本轮用户及Stage3A.5明确指定，覆盖旧valid_components；其余权重和阈值不变。

| Rule ID | Rule Name | Input | Prerequisite | Threshold Bands / Score | Max Score | Coverage Rule | Data Error Behavior | Explanation Template | SSOT Location |
|---|---|---|---|---|---:|---|---|---|---|
| S1 | 板块1日相对强度 | sector_return_1d, benchmark_return_1d, excess, coverage | coverage>=80% | x<0:0; [0,.005):5; [.005,.01):10; [.01,.02):16; [.02,+∞):20 | 20 | >=80% | 非VALID/前置不足→score=None；详见下节 | 行业1日收益{sector}，基准{benchmark}，超额{x}，区间{band}，得{score}/20 | SPEC_V1_4_EXTRACTED.txt:231–242 |
| S2 | 板块5日相对强度 | sector_return_5d, benchmark_return_5d, excess, 5 intervals | 5日数据完整 | x<0:0; [0,.02):6; [.02,.04):12; [.04,.06):16; [.06,+∞):20 | 20 | 5日完整，不另加80% | 非VALID/前置不足→score=None；详见下节 | 行业5日收益{sector}，基准{benchmark}，超额{x}，区间{band}，得{score}/20 | SPEC_V1_4_EXTRACTED.txt:243–254 |
| S3 | 上涨广度 | advancing, valid, expected, breadth, coverage | valid>=10; coverage>=80% | x<.5:0; [.5,.6):4; [.6,.7):8; [.7,.8):12; [.8,1]:15 | 15 | >=80% | 非VALID/前置不足→score=None；详见下节 | 上涨{advancing}/{valid}，广度{x}，得{score}/15 | SPEC_V1_4_EXTRACTED.txt:255–266 |
| S4 | 涨停联动密度 | verified limits, closed count, valid limit count, ratio | 真实涨停价；valid>=10 | count>=5 AND ratio>=.05:15; 否则count>=3:12; count=2:6; count=1:3; count=0:0 | 15 | 无额外比例门槛；按数据层VALID | 非VALID/前置不足→score=None；详见下节 | 收盘封停{count}/{valid}，占比{ratio}，得{score}/15 | SPEC_V1_4_EXTRACTED.txt:145、267–278 |
| S5 | 板块成交活跃度 | today amount, prior20 mean, ratio, daily evidence | 前20交易日；不含当日；coverage>=80% | x<.9:0; [.9,1.15):4; [1.15,1.4):8; [1.4,1.8):12; [1.8,+∞):15 | 15 | 成交额>=80% | 非VALID/前置不足→score=None；详见下节 | 当日额{today}，前20日均额{mean}，比值{x}，得{score}/15 | SPEC_V1_4_EXTRACTED.txt:279–290 |
| S6 | 强势持续性 | 5日日历及逐日行业/基准收益、win | 5日完整，每日coverage>=80% | 0–1日:0; 2日:2; 3日:5; 4日:8; 5日:10 | 10 | 逐日>=80%；不以4日代5日 | 非VALID/前置不足→score=None；详见下节 | 过去5日逐日跑赢{wins}日，得{score}/10 | SPEC_V1_4_EXTRACTED.txt:291–302 |
| S7 | 强势股深度 | strong_count, expected_count, valid_return_count, ratio | valid>=10；强势return>=5% | x<.05:0; [.05,.10):2; [.10,.15):4; [.15,1]:5 | 5 | 无额外80%门槛；expected分母 | 非VALID/前置不足→score=None；详见下节 | 强势{strong}/{expected}，比例{x}，得{score}/5 | SPEC_V1_4_EXTRACTED.txt:303–314 |

## Data Error Behavior（每条规则适用）

DataStatus与评分状态分开：只有VALID输入经过字段/日期/比率/前置校验才可评分。DATA_ERROR、DATA_STALE、DATA_INCONSISTENT、NOT_APPLICABLE等均score=null，status=UNKNOWN，保留data_status及原因。样本少于10也不是零分。完整但不命中时score=0/status=FAIL；部分分PARTIAL、满分PASS。

S6的“5日完整”前置与“覆盖<80%则UNKNOWN”共同满足：不将缺失日当输、不补旧日；逐日覆盖不足不评分。输入提供恰好5个已验证交易日及逐日比较，不能只给累计收益。

## 总分及接口

最大分20+20+15+15+15+10+5=100，直接求和，不重新归一化。无缺项总分=七项和；任一不能评分则total_score=null/overall_status=DATA_INCOMPLETE。available_score是已判定分的诊断和，available_max_score是已判定规则最大值和，score_coverage=available_max_score/100。该缺项默认由本轮用户明确要求。

S4 ratio依据活动规范=count/有效成分（valid_limit_count）；Stage35完整输入的valid=expected，因此与存档ratio一致。S7始终expected分母。B1/B2只准备读取契约，不连接单股ScoreEngine。

SEMANTIC_GAP：未发现阻塞上述当前实现的未决定义。H61仅5成员时S3/S4/S7合法返回空分，这属于样本前置不足，不属于语义未决。
