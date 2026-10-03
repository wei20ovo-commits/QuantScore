# Rule Implementation Matrix

## Stage 3C orchestration

Candidate semantics ACTIVE / USER_CONFIRMED 2026-10-02, see
STAGE3C_RULE_FREEZE.md and STAGE3C_SPEC_INDEX.md. Existing 44 implemented and
4 unimplemented scoring rules are unchanged. Screening reuses existing
SectorHeat, B1/B2 and full stock scoring; it introduces no new rule ID.
32 dedicated offline screening tests cover gates, failure isolation, order,
metadata denominator preservation, request reuse, worker lifecycle and core
scoring equivalence. Live acceptance status is recorded in STAGE3C_RESULT.md;
offline test PASS must not be interpreted as full-market live acceptance.

Spec Status=FROZEN_V1_4表示定义来自冻结Word，不代表代码完成。用户语义已冻结；IMPLEMENTED为完整执行器，UNKNOWN仍可由客观数据条件产生。
Test Status只针对评分执行器：未实现规则的UNKNOWN守卫测试即使通过，仍标NOT_TESTED，不冒充业务验收通过。Code Status与规则返回的PARTIAL分档状态是不同维度。

| Rule ID | 名称 | Source Type | Spec Status | Code Status | Test Status |
|---|---|---|---|---|---|
| S1 | 板块1日相对强度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| S2 | 板块5日相对强度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| S3 | 上涨广度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| S4 | 涨停联动密度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| S5 | 板块成交活跃度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| S6 | 强势持续性 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| S7 | 强势股深度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| A1 | 大盘短期趋势 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| A2 | 大盘中期结构 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| A3 | 大盘5日动能 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| B1 | 所属板块热度映射 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| B2 | 个股相对板块5日强度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| B3 | 板块内龙头代理 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| C1 | 站稳M60 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| C2 | M60方向 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| C3 | 均线多头结构 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| C4 | M60有效突破/快速收复 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| C5 | M60起飞平台 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| C6 | 上升安全带完整 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| D1 | 关键突破放量 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| D2 | 突破后缩量回踩 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| D3 | 上涨量强于下跌量 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| D4 | 整理期成交量收缩 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| D5 | 换手率健康度 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| E1 | 底部小连阳 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| E2 | 周线成交量反转 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| E3 | 日/周线阻尼收敛 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| E4 | 低位筹码峰 | AUTO_IF_DATA | FROZEN_V1_4 | NOT_IMPLEMENTED | NOT_TESTED |
| E5 | 筹码集中度改善 | AUTO_IF_DATA | FROZEN_V1_4 | NOT_IMPLEMENTED | NOT_TESTED |
| F1-N | N板启动 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| F1-T | T板启动 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| F1-O | 一字板/一字T干净启动 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| F1-X | 仙人指路 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| F1-Y | 鲤鱼跃龙门 + 假摔 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| F2 | 启动位置质量 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| F3 | 空中加油（高位中继） | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R1 | 高位异常换手 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R2 | 高位异常放量 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R3 | 高位涨停出货/烂板 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R4 | 双子顶 Double-Top Risk | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R5 | 三K高位反转组合 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R6 | 分时缩量诱多 | AUTO_IF_DATA | FROZEN_V1_4 | NOT_IMPLEMENTED | NOT_TESTED |
| R7 | 该涨不涨/关键位突破失败 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R8 | 安全带跌破 | AUTO_PROXY | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R9 | M30有效跌破 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R10 | 筹码由低位向高位迁移 | AUTO_IF_DATA | FROZEN_V1_4 | NOT_IMPLEMENTED | NOT_TESTED |
| R11 | N板换手期失效 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |
| R12 | T板/一字板异常成交 | AUTO | FROZEN_V1_4 | IMPLEMENTED | PASS |

## 数量

- IMPLEMENTED: 44 — S1, S2, S3, S4, S5, S6, S7, A1, A2, A3, B1, B2, B3, C1, C2, C3, C4, C5, C6, D1, D2, D3, D4, D5, E1, E2, E3, F1-N, F1-T, F1-O, F1-X, F1-Y, F2, F3, R1, R2, R3, R4, R5, R7, R8, R9, R11, R12
- PARTIAL: 0 — 
- NOT_IMPLEMENTED: 4 — E4, E5, R6, R10

R6原文source_type=AUTO_IF_MINUTE_DATA，注册时规范化为AUTO_IF_DATA并保留source_type_in_spec。
均线/量比等派生变量不新增评分Rule ID。MANUAL和SYSTEM受Schema支持，但不凭空增加规范中没有的规则。

## Stage 3B 独立SectorHeat执行器（历史阶段记录）

S1–S7 IMPLEMENTED指app/sector/scoring.py的独立评分层，尚未连接单股RuleEngine/ScoreEngine。当时B1/B2未接入；此状态已由下方Stage 3B.1记录取代。阈值及优先级见STAGE3B_RULE_FREEZE.md；住宿业样本不足返回空分不构成实现失败。完整回归665项：664 PASS / 0 FAIL / 0 ERROR / 1 SKIP。Live验收见STAGE3B_RESULT.md，不能用离线测试代替。

## Stage 3B.1 B1/B2 integration

B1/B2评分执行器和服务接入已实现，专项与全量离线测试通过；真实live验收状态以STAGE3B1_RESULT.md为准。数据错误、完整Heat缺失、归属/日期/复权窗口不一致返回UNKNOWN/None。旧阶段尚未接入的说明仅为历史记录。

Stage 3B.1 Live Recovery：真实三股票、CLI与API完整B1/B2验收PASS，见STAGE3B1_LIVE_RECOVERY.md。
