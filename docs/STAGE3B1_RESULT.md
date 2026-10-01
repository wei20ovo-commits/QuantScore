> 历史首次验收记录：当时PARTIAL。现已由STAGE3B1_LIVE_RECOVERY.md的真实E2E验收PASS取代；以下失败记录保留。

# QuantScore Stage 3B.1 B1/B2 Integration Result

## Current Audit
基线HEAD=origin/main=8df39e4775a18fca11547959df1bf57c9fcf31bc。保留既有Stage 3B成果及Stage26未跟踪文件；未reset、rebase、commit或push。

## SSOT Audit
活动V1.4统一左闭右开端点优先于历史摘录；详见STAGE3B1_RULE_FREEZE.md。无语义猜测。规范1.4、assumption v1.3保持不变。

## Primary Industry Context
新增PrimaryIndustryService，一次获取当前真实BaoStock primary industry、成分股raw/qfq、真实交易日历和上证基准，再复用SectorHeatEngine。每份结果保留provider/as_of、请求记录和缓存来源。当前归属不冒充历史point-in-time归属；不混用概念或多行业。

## B1 Implementation
完整同日VALID Heat映射：<50=0、[50,60)=2、[60,70)=4、[70,75)=6、[75,85)=7、>=85=8。缺完整Heat时UNKNOWN/None，绝不使用available_score替代。

## B2 Implementation
股票与行业同六个交易日端点、同qfq收益口径；个股五日收益减行业五日收益。<0=0、[0,1%)=1、[1%,4%)=2、[4%,8%)=3、>=8%=4。边界、缺失及错配已测试。

## Data Quality Handling
DATA_ERROR/STALE/INCONSISTENT、缺归属、缺窗口或缺完整Heat均保留None及原因；未知不作业务0分。B1不可用时，若行业收益完整，B2仍可独立评分。新增适配层兼容缓存与实时日期存储精度；非有限原始值序列化为null。

## RuleEngine Integration
B1/B2正式注册，规则配置evaluator/code_status一致。RuleResult保留raw_values并提供primary industry、收益、分档、data_status和provenance。

## ScoreEngine Integration
ScoreEngine与冲突/Coverage算法未修改。B类上限15保持；S1–S7不重复进入个股总分。重复Rule ID去重测试通过。服务新增industry_context字段；旧JSON字段保留。

## Replay
Stage35真实存档、完全离线：600506.SH/C25 B1=0 B2=0；600107.SH/C18 B1=0 B2=1；600258.SH/H61 B1=None B2=0。C25 Heat=25、C18=18、H61 DATA_INCOMPLETE。行业上下文重建也与Stage3B一致。

## Manual Crosscheck
人工按已读取数值和冻结区间独立判档：B2相对收益约-3.4093574%、+0.1530466%、-0.0679165%，对应0/1/0；B1为0/0/None。六项均一致，见manual_crosscheck.csv。

## Live Smoke
尚未通过。最新完整三股票请求均因BaoStock日线10002007、备用源超时/连接失败而降级为UNKNOWN；证券资料定向核验成功。初轮三只股票真实请求均已尝试；首轮600688证券列表失败、600258历史分页不完整、600519行业请求错误及日期精度问题。精度问题已修复并增加测试；后续网络仍返回10001001/10002007。失败记录与原始JSON全部保留，未以mock代替真实结果。

## 600519 Regression
曾真实取得贵州茅台2026-09-29数据，并成功输出CLI JSON；但行业上下文当时失败，B1/B2为UNKNOWN，因此不算完整B1/B2真实验收。最新CLI已核验代码，但日线请求失败。原规则专项回归及完整pytest已通过；完整真实集成仍待网络恢复后重跑。

## CLI
真实命令python -m app.cli analyze 600519 --json已执行。早期一次exit=0但行业失败；最新exit=1。600519_cli*.json及error文件保留实际输出，不将有效JSON等同于评分成功。

## FastAPI
真实StockAnalysisService通过TestClient调用既有/api/analyze/{symbol}，没有mock。初轮HTTP 200包含行情不可用降级结果，并非真实分析通过。旧接口及新增字段离线集成测试通过；真实三股票完整验收尚未完成。

## Implementation Matrix
B1/B2已标IMPLEMENTED/PASS，PASS指执行器测试，不代表live验收通过。阶段状态以本报告为准。

## Tests
723项：722 PASS / 0 FAIL / 0 ERROR / 1 SKIP。原665项全部保留，新增58项。SKIP为阶段外自动选股；一条第三方弃用警告。证据pytest.xml、pytest.txt。

## Evidence Files
outputs/stage3b1/包含b1_replay.csv、b2_replay.csv、single_stock_integration.csv、manual_crosscheck.csv、replay_details.json、context_replay.json、live_smoke.csv、600519_analysis.json、600519_cli*.json、run_metadata.json、pytest.xml/txt、初轮失败记录和历史重新获取日志。

## Files Added / Updated
新增app/rules/trend/industry.py、app/sector/industry_context.py、tests/test_b1_b2_integration.py、tools/stage3b1_replay.py、tools/stage3b1_live.py、tools/stage3b1_refresh_history.py、本报告和规则冻结文档。
更新RuleEngine、schemas、StockAnalysisService、两份规则配置、BaoStockProvider、ProviderManager、SymbolResolver、BaoStock测试、实现矩阵及TEST_REPORT。
未修改UI、ScoreEngine、SectorHeat阈值、权重或既有股票规则语义。

## Remaining Issues
真实三股票/CLI/API尚未全部通过，不能宣称Stage 3B.1 PASS。网络中断可导致SDK返回不完整分页：已加入拒绝检测、证券列表重试与当前日期缓存，避免将半份数据当作有效列表。定向证券查询核验两交易所真实返回，保留既有Provider fallback；无需为单代码查询依赖全量分页列表。三只股票单证券资料探测均成功，见network_probe.json，不能据此宣称日线分析成功。BaoStock请求上限150秒，首次全行业分析延迟较高。部分旧失败缓存与历史响应仅作诊断证据；不据此补值或降低质量要求。范围仍限当前SH/SZ行业归属；历史归属及可靠历史涨跌停数据缺失仍可UNKNOWN。

## Status
PARTIAL
