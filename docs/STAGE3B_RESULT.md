# QuantScore Stage 3B SectorHeat Result

## Current Audit

实际 git fetch origin、git status、git log -5、rev-parse 校验：HEAD=origin/main=fecf1a87ef1a7559e7f5c9b194fc1f6a8a244b63。保留原有未跟踪 docs/STAGE26_FINAL_VERIFICATION.md、tools/stage26_public_smoke.py。无reset/checkout/rebase，无commit/push。

## SSOT Freeze

编码前生成 STAGE3B_RULE_FREEZE.md，逐项记录前置、分档、分数、覆盖、错误行为和当前规范位置。SPEC_EXTRACTED.txt是V1.1历史抽取；CURRENT依据V1.4继承的活动修订。统一左闭右开优先于历史表格端点，因此S1=0得5、S2=0得6，2%/6%分别进最高档。这是活动统一规则，不是新增阈值。S7使用本轮用户明确要求的expected名单分母。没有未决SEMANTIC_GAP。

## SectorHeat Architecture

app/sector/models.py定义标准输入、逐规则结果及SectorHeatResult；scoring.py纯评分，无网络或行情Provider调用；replay.py只读Stage35存档；readiness.py只准备下游数据。执行分档放在config/sector_heat.yaml并逐条链接SSOT，未改原权重配置。现有Stage3A数据层、单股RuleEngine/ScoreEngine和UI未改动。

每个结果包含七项明细、raw_inputs、分档、score/max_score、评分status、data_status、原因、解释、source_date，及版本、provenance、完整/可用分和覆盖。

## S1

满分20；覆盖>=80%，按1日相对收益分档。边界及错误输入测试已覆盖。

## S2

满分20；五个真实交易日收益区间，按5日相对收益分档；不足窗口不评分。

## S3

满分15；有效成员>=10且覆盖>=80%，以valid成员为广度分母；缺数据不是0分。

## S4

满分15；有效真实涨停价成员>=10，逐条检查真实limit证据、日期、收盘价格与closed状态。按count与ratio组合分档；count>=5但ratio<5%落入12分档，不冒充15。非盘中触及，不用近涨停代理。比例为count/valid_limit_count，遵守未修改的活动S4定义。

## S5

满分15；21行证据分离当日与此前20交易日，核验平均值和比值；不把成交活跃度解释为资金净流入。

## S6

满分10；恰好五个已验证交易日逐日比较，核验每一天的sector_win与实际收益关系；0/1/2/3/4/5胜分别0/0/2/5/8/10分，不用累计收益替代。

## S7

满分5；有效成员>=10，强势定义return>=5%，分母expected成员，不因数据缺失缩小分母。

## Total Score

七项最大分自然合计100，直接相加，没有重新归一化。全部可评分才生成total_score；任一项不可评分则total_score=null、overall_status=DATA_INCOMPLETE。available_score仅诊断，不冒充正式分。

## Data Quality Handling

DATA_ERROR、DATA_STALE、DATA_INCONSISTENT、NOT_APPLICABLE一律score=None，保留原因，available_max_score排除该项；完整且未命中才得0。日期不一致、非有限数、比率与计数矛盾、重复/缺少日期或涨停证据均不自动评分。

## Stage35 Replay

完全离线读取现有2026-09-28存档，没有修改Stage35证据或重新联网。

| 行业 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | total | available/max | status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| C18纺织服装、服饰业 | 0 | 12 | 0 | 0 | 4 | 2 | 0 | 18 | 18/100 | VALID |
| C25石油、煤炭及其他燃料加工业 | 5 | 12 | 0 | 0 | 0 | 8 | 0 | 25 | 25/100 | VALID |
| H61住宿业 | 0 | 0 | null | null | 0 | 0 | null | null | 0/65 | DATA_INCOMPLETE |

H61仅5成员，S3/S4/S7样本门槛未满足。这是规范正确执行，不是引擎失败，也不能把它写成完整0分。表按行业代码展示，不构成热度排名。

## Manual Crosscheck

独立读取C25 Stage35 CSV手算：1日超额0.203746%→5；5日超额2.016126%→12；广度4/17→0；封停0/17→0；金额比0.808071→0；五日逐日胜4天→8；强势0/17→0；总和25。固定手算表不调用评分函数生成期望值，逐项与引擎相等。保存manual_crosscheck.csv，可通过tools/stage3b_replay.py重复核验。

## Live Smoke

PASS：真实BaoStockIndustryProvider → C25完整17成员 → 17份raw + 17份qfq → 真实上证指数/日历/IPO元数据 → S1–S7 → SectorHeat。

行情日2026-09-29；七项分数依序为[0, 0, 4, 0, 0, 5, 0]，总分9/100，score_coverage=100%，overall_status=VALID。最后取数时间2026-09-29T16:05:54.400682+00:00。日期不同于Stage35，因此9分不要求等于旧快照25分。

首次40秒证券元数据请求三次超时；延长等待成功后发现全量metadata仅4000行，缺7只目标代码，逐股真实补查补全。1990起全量日历也只返回4000行、截至2001-11-30；改为5年一段真实请求，合并并校验每日连续覆盖至评价日。单只行情瞬时失败亦重试成功。保留全部原响应、失败日志、补充元数据和分段日历，不掩盖Provider返回成功但数据不完整的问题；未修改Provider核心。

支持--resume继续同一次live成功响应，只补缺项，不以Stage35数据冒充live。保存原窗口，跨午夜后仍使用本轮已验证的2026-09-29收盘数据。

## B1 Readiness

B1_READY=true：对已有primary industry及完整SectorHeat的样本，准备SectorHeatScore与score_coverage读取接口。C25实值25可用；H61完整Heat为空时B1不可用。未实现B1分档写入单股ScoreEngine。

## B2 Readiness

B2_READY=true：已用600688.SH与其C25行业的同日5日收益准备差值输入；检查行业标识、日期与DataStatus。仅输出数据契约，不将B2加入QuantScore。

## Tests

完整665项：664 PASS、0 FAIL、0 ERROR、1 SKIP；新增139项。保留原526项。1 SKIP仍为本阶段不实施的自动选股排名。Windows临时目录使用项目内outputs/tmp/pytest。原始pytest.xml/pytest.txt保存在outputs/stage3b/。

## Files Added / Updated

新增：app/sector/{models,scoring,replay,readiness}.py；config/sector_heat.yaml；docs/STAGE3B_RULE_FREEZE.md、STAGE3B_RESULT.md；tests/test_sector_heat.py、tests/fixtures/stage3b_c25_inputs.json；tools/stage3b_replay.py、stage3b_live.py。

更新：docs/RULE_IMPLEMENTATION_MATRIX.md、TEST_REPORT.md。输出：outputs/stage3b/sector_heat_results.csv、sector_heat_details.json、manual_crosscheck.csv、b1_b2_readiness.json、replay_source_hashes.json、run_metadata.json及live/。

## Remaining Issues

无阻塞本轮验收的问题。BaoStock长区间/全量请求可能返回不完整分页，使用前必须验证实际目标覆盖；本轮live脚本已补查并检查。Stage3A原有范围限制继续有效：当前行业归属不是历史时点归属，特殊交易事件需要可靠元数据。输出证据受现有.gitignore排除，不表示已经上传GitHub；本轮不commit/push。

## Status

PASS（SSOT冻结、七项评分、离线回放、独立手算、live及完整回归均通过）。未进入Stage3C，没有排名、自动筛股、UI、LLM或回测。
