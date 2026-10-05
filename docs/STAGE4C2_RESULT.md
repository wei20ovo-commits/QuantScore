# QuantScore Stage 4C.2 Public Single-Stock Latency Result

验收日期：2026-10-05。基线：`main @ 34bf472fba7bacb1eccfa8c13b8bea7b0dc3373c`。HEAD与origin/main保持该提交；本轮没有commit/push，没有进入Stage5。

**Stage 4C.2 = PARTIAL；Stage 4C尚不能标PASS。** 本地优化、真实行情、实际Web页面、语义等价性和回归均已通过。优化代码仍未发布，公网优化版Cold/Warm尚未验收；不能用localhost代替公网成绩。

## Root Cause

旧Web链路每次构造默认StockAnalysisService，默认PrimaryIndustryService同步获取所属行业全体成分股raw/qfq、行业成员、元数据、交易日历及行业benchmark，然后重新生成SectorHeat和B1/B2输入。单股benchmark另取2000年以来完整历史；图表适配器随后再次调用manager.fetch。

Stage4C.1真实诊断：本地冷运行474.609秒，其中行业输入349.6407秒，约73.67%；118次BaoStock SDK查询，其中行业105次、行业raw/qfq94次对应47个成员。全局SDK锁使线程池请求实际串行，每次旧SDK worker启动及login/query/logout又增加成本。旧公网600519在1200秒期限内未完成，最后一次轮询1199.812秒。原证据完整保留：

- outputs/stage4c1/completion/local/local_latency.json
- outputs/stage4c1/completion/public/public_latency.json
- docs/STAGE4C1_RESULT.md

这些证据解释已复现的瓶颈，不把本地阶段计时称作云服务器逐阶段日志，也不声称精确还原历史740秒。

## Architecture Change

仅修改Web获取层，不修改RuleEngine、ScoreEngine、StockAnalysisService、规则实现、参数、权重、B1/B2或Candidate判定，也不修改AI解释层及UI设计。

新路径：

1. `app/web_backend.py::create_web_service`构造Web专用服务。
2. 通过原ProviderManager、SymbolResolver、字段分组、校验和fallback获取当前股票自身必要元数据与完整raw/qfq；历史窗口没有截短。
3. `WebContextSnapshots`只读正式行业上下文及同日期上证指数快照。
4. `SnapshotIndustryService`将上下文交给原StockAnalysisService和B1/B2实现，不重新算行业、不联网补行业。
5. `WebMarketCache`在任何旧benchmark TTL命中之前校验快照日期与股票实际评价日；同请求股票/图表使用RequestCache复用。
6. SDK采用已有Stage3C.1 BatchBaoStockProvider减少重复Python worker启动，继承原BaoStock查询、字段、校验及login/finally-logout机制；provider顺序未改变。
7. 保留既有Streamlit结果缓存：ttl=300秒。Standard Rules仍不调用LLM。

运行时限制为工程超时，不是评分条件：BaoStock单请求30秒，Web worker整体240秒硬截止。Windows私有kill-on-close Job / POSIX独立process group只管理本次请求及SDK子进程。超时停止请求、清理自有临时目录并返回固定中文错误，不无限等待，不暴露原始异常或凭据。其他Provider故障也受整体截止约束。无需修改Windows全局代理。

## Snapshot Reuse

行业来源：config/web.yaml既有正式发布路径，以现有load_screening_snapshot校验并选择最新完整SH/SZ行业结果。目前有效文件为`outputs/stage3c/full_market/screening_details.json`，交易日2026-09-30，完整83行业。额外检查现行spec_version=1.4、assumption_version=v1.3、data_contract_version=1.4。

行业归属从正式股票primary_industry及S4存档expected成员limit_details建立映射，不能只依据已扫描的达标行业股票。重复行业映射不可用。适配器仅将已验证成员对应上下文的primary_industry.symbol绑定到请求股票；Heat、收益窗口、状态、日期和原来源证据均保留。

600519.SH读取C15上下文：Heat=70，B1=6/PARTIAL，B2=1/PARTIAL。行业5日收益、六个交易日窗口和qfq口径原样复用。Heat状态及returns状态独立，Heat缺项不能自动取消合法B2。

指数来源：Stage3C.1正式`outputs/stage3c1/final_history.sqlite3`中经过校验的baostock / 000001.SH / NONE历史。`tools/stage4c2_publish_benchmark.py`只读导出便携CSV及manifest，不联网、不生成价格、不改历史缓存。

| Publication | Value |
|---|---|
| Benchmark | 000001.SH / BaoStock / NONE |
| Trade date | 2026-09-30 |
| Rows | 6482 |
| CSV | data/published/market_context/benchmark.csv |
| Size | 1,213,485 bytes |
| SHA256 | 20b0aee8396a4986db35ee162995f420e9c76b7837a3733bd10103f340d7af5b |

manifest包含原获取时间、来源相对路径、来源payload SHA256、原验证记录。运行时无需原SQLite或任何D盘绝对路径。校验CSV哈希、provider、symbol、NONE口径、最大日期、行数及原DataValidator。CSV round-trip保留原数值；导出时独立逐数值列精确比对，原路径完整指数OHLC也逐值一致。

缺失、损坏、版本不一致或日期不匹配的快照不能作为VALID，不会触发实时整行业或benchmark抓取。新交易日需后台发布同日正式行业结果及benchmark；这不是Web自动扫描功能。

## Semantic Equivalence

两层验证均通过：

1. **真实存档重放**：复制Stage4C.1完整真实缓存到两个隔离诊断数据库；原路径从同一真实成员raw/qfq、元数据、日历重算行业，新路径读正式快照。网络明确禁用，双方使用相同股票/指数历史及冻结R7快照。逐字段严格比较41条规则、全score对象、industry_context、价格、指标、大盘、coverage和解释。
2. **自动测试**：人工离线夹具经两个获取接口送入未修改的同一引擎，连同原始来源记录完整比较全部41条规则、score和行业上下文，不用该夹具冒充真实行情。

真实重放结果：QuantScore=0、Risk=HIGH、SectorHeat=70、B1=6、B2=1，41/41规则业务字段相同。status、score、penalty、raw数值、conditions、reason_code、explanation、版本及风险提示没有差异。不缩放、不重加权，不调用Candidate判断。

唯一允许不同的是实际采集来源字段：data_provenance、provenance、primary_industry_provenance；新路径应诚实记录快照来源，不能冒充本次行业网络请求。这些采集证据保留在原、新完整JSON中，比较时仅排除这三个明确字段，没有忽略数值误差或解释差异。

源真实缓存SHA256运行前后均为`a73693eada1564893a43f7bcfb6ccd10019c0ce993992391554f8fb60d6eb324`。没有修改历史证据。

证据：outputs/stage4c2/equivalence.json、replay_original.json、replay_optimized.json。重放不是live测试，不将22.66/21.30秒重放时间作为冷启动改善。

## Cold / Warm Latency

### Controlled local genuine backend

使用空诊断缓存，再用同一持久缓存。真实获取600519.SH / 贵州茅台 / BaoStock，交易日2026-09-30，is_mock=false，41条规则、120日图表；两次行业/benchmark快照有效，QuantScore=0、Risk=HIGH、Heat=70。DataStatus=PARTIAL沿用可靠历史涨跌停等缺数据语义，不能改成虚假AVAILABLE。

| Metric | Old local cold | Optimized local cold | Optimized local warm |
|---|---:|---:|---:|
| Total wall | 474.609 s | **56.3085 s** | **22.1128 s** |
| Stock raw/qfq fetch | 67.4837 s | 30.7835 s | 0 SDK fetches |
| Formal market context init | N/A | 0.3262 s | 0.3521 s |
| Industry context | 349.6407 s | 0.0022 s | 0.0018 s |
| B1/B2 rule evaluation | Within scoring | 0.0358 s | 0.0849 s |
| Rule scoring | 17.5968 s | 16.3441 s | 16.1147 s |
| Chart data/features | 1.6715 s | 1.2374 s | 1.2203 s |
| Plotly figure construction | 1.0110 s | 0.2645 s | 0.0405 s |
| AI call | 0 | 0 | 0 |
| Cache hit / miss | 5 / 111 | 6 / 5 | 11 / 0 |
| BaoStock SDK requests | 118 | **10** | **0** |
| Industry online requests | 105 | **0** | **0** |
| Benchmark online requests | Present | **0** | **0** |

SDK时间31.9078秒为嵌套查询计时，不能与raw/qfq及total再累加。B1/B2计时包含于Rule scoring，chart取数也包含benchmark本地读取；各阶段不是互斥分区。最终代码另输出benchmark_snapshot_load、SDK事件/超时/worker数，方便发布后的同口径诊断；上表该次真实运行没有单独记录benchmark读盘耗时，不补造数字。

SDK数量指BaoStock查询，包含重试尝试，不是HTTP连接数；其他fallback Provider内部HTTP数量不能从此计数推断。真实冷运行使用BaoStock，10次为2次股票身份查询及8次当前股票raw/qfq字段分组查询。没有新增行业网络请求。冷运行SDK数量下降91.53%；本地wall下降88.14%。环境、网络及进程封装不同，这些不是公网改善百分比。

证据：outputs/stage4c2/local_latency.json、live_cold.json、live_warm.json。所有临时文件在项目D盘。没有付费AI调用。

### Actual local Web browser

真实启动`streamlit run app/web.py --server.port=8503`，没有mock或路由替换。浏览器首次点击至真实结果、Plotly图表和脚本完成为**76.219秒**；同会话再次点击为**0.531秒**，命中既有Streamlit结果缓存。此处首次是新浏览器首次点击，不声称强制了持久行情缓存冷状态。

真实浏览器验证：贵州茅台、600519.SH、BaoStock、2026-09-30、Standard Rules、120点日K/M5/M30/M60/成交量、行业/B1/B2与规则展示、Light/Dark切换通过；390px无横向溢出通过。构图与浏览器展示时间不同，不把单独Plotly构图时间伪装成云端render span。

真实截图：

- outputs/stage4c2/web/analysis_light.png
- outputs/stage4c2/web/analysis_dark.png
- outputs/stage4c2/web/analysis_mobile.png

证据：outputs/stage4c2/web/web_smoke.json。Local verification=PASS，aggregate deployment status=PARTIAL。

### Cold Public Latency / Warm Public Latency

公网URL：https://quantscore-grrgr4oqy5pfhfqnyp9q9b.streamlit.app/

本轮实际只读首页：HTTP200，首页可用10.516秒；没有启动第二次旧版本长时间股票分析。截图：outputs/stage4c2/web/public_home_read_only.png。

| Public build | Cold 600519 | Warm 600519 |
|---|---|---|
| Previous Stage4C.1 | 1200秒期限内未完成 | NOT_MEASURED |
| Optimized Stage4C.2 | **NOT_DEPLOYED / NOT_MEASURED** | **NOT_DEPLOYED / NOT_MEASURED** |

用户明确禁止commit/push；Community Cloud不能自动获得未提交的本地文件。没有擅自发布，也没有把旧公网首页、本地56秒或本地76秒记为优化版公网成绩。Stage4C整体必须继续PARTIAL，直到获得优化版真实Cold/Warm结果且不再出现1200秒等待。

## Fallback Behavior

- 行业快照不存在/成员未知：DATA_ERROR，B1/B2由原规则返回UNKNOWN / score=None。
- 股票评价日与行业日期不一致：DATA_STALE；primary日期不同也不可评。
- 版本、行业ID或成员映射矛盾：DATA_INCONSISTENT，不猜行业、不使用旧值。
- Heat不可评与收益不可评分别处理；合法收益窗口仍可供B2使用。
- benchmark manifest缺失/损坏/哈希或身份不符：不可用；date不匹配为DATA_STALE。忽略旧benchmark TTL缓存，原大盘规则按缺数据语义处理。
- 股票Provider失败、无完整股票行情：原服务返回UNAVAILABLE，Web不展示新评分。
- 整体超时/worker错误：固定解释性提示，终止自有进程树并清理临时目录；错误不转成“零分”，不回显原始异常。

错误降级改变可用数据及覆盖信息是诚实缺证据行为；同一有效输入的业务规则完全一致。不会把不可评数据当FAIL或伪装VALID。

## Tests

实际完整回归：**972 total / 971 PASS / 0 FAIL / 0 ERROR / 1 SKIP**，176.62秒。原937个通过用例保留，新增34个快照/运行时/接口等价性用例。唯一SKIP仍为原T20 HISTORICAL / SUPERSEDED_BY_STAGE3C；一项原FastAPI/Starlette弃用警告。

新增覆盖：同日真实输入复用接口、源对象不变、缺失/陈旧/错误/矛盾状态、版本、行业成员、损坏OHLC/哈希/身份/越界路径、过期benchmark绕过旧TTL、Heat与returns独立、41条结果精确相同、禁止网络补行业/benchmark、worker成功/失败/超时和自有目录清理、禁止延长截止。

首次定向回归发现mock拒绝测试的None industry_service插桩问题，已修复，没有删除旧测试；随后50个定向用例及完整回归通过。沙箱AppTest停滞后使用正常本机执行环境，未修改业务逻辑规避环境权限。TMP/TEMP/TMPDIR使用项目outputs/tmp/pytest/stage4c2-final。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=outputs/tmp/pytest/stage4c2-final --junitxml=outputs/stage4c2/pytest.xml --tb=short
```

证据：outputs/stage4c2/pytest.xml。

## Files Added / Updated

本轮更新：app/web_backend.py。

本轮新增：

- app/web_snapshots.py
- app/web_runtime.py
- data/published/market_context/benchmark.csv
- data/published/market_context/manifest.json
- tests/test_web_snapshots.py
- tools/stage4c2_publish_benchmark.py
- tools/stage4c2_verify.py
- tools/stage4c2_web_smoke.py
- docs/STAGE4C2_RESULT.md
- outputs/stage4c2/实际诊断、逐规则比较、pytest及截图证据（本地保留，遵守原.gitignore）

Stage4C.1的README、DeepSeek组件、测试及报告等既有未提交成果全部保留，未被旧版本覆盖；app/web.py、web_visuals.py、web_style.css、AI实现和所有评分文件在本轮均未修改。Git暂存区未改动。

## Security / Remaining Limitations / Status

本轮未注入、复用或调用任何AI凭据。项目文件、Git work/staged diff、docs、outputs、logs与截图二进制完成凭据模式检查，无命中、无不可读文件。浏览器截图前另检查可见文字。模式检查不是穷尽所有可恢复编码或图像OCR，不冒充Stage4C.1的精确临时Key扫描。最终扫描证据：outputs/stage4c2/security_scan.json。

剩余事项：

1. **发布并验收优化版公网Cold/Warm**。受本轮明确禁止commit/push约束，当前未发布；不得提前宣称Stage4C=PASS。
2. 后台正式行业与benchmark快照需按交易日更新。当前冻结发布为2026-09-30，未来新交易日无同日快照时必须诚实降级，不能退回昂贵实时整行业抓取。
3. 股票自身完整raw/qfq仍依赖真实Provider和网络，评分约16秒；240秒截止保证停止等待，不保证故障时也成功生成分析。
4. 公网服务器内部cold-start、cache和render span未观测，尚不能报告优化后的公网请求数与分阶段时间。最终Web后端已提供安全诊断字段，便于实际发布后的验证。

**Status：PARTIAL（LOCAL HARDENING PASS / PUBLIC OPTIMIZED ACCEPTANCE PENDING）。** 完成后停止，没有commit/push，没有进入Stage5。
