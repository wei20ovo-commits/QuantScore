# Stage 4C.5 — Public Data Failure Diagnosis

验收日期：2026-10-09（Asia/Shanghai）。状态：**PARTIAL**。

## Root Cause

必须区分“已证明的本地失败出口”和“此前 Cloud 约 180 秒失败的根因”。后者尚未取得对应请求的结构化 Cloud 日志，不能用本地现象代替证明。

1. **真实本地失败已定位到股票行情获取，而非行业扫描或评分。** 本轮以独立空缓存执行真实 Web 后端 600519：证券查询成功；BaoStock raw 历史行情两次尝试分别发生请求截止；fallback AKShare raw 成功、qfq 在 Provider 的数据校验中失败。最终 `_load()` 返回 `UNAVAILABLE`。没有进入行业上下文加载、规则 `evaluate()` 或图表构建。
2. **缓存警告已复现为 spawn 导入副作用。** 在不调用任何行情接口的情况下，用 `runpy.run_path('app/web.py', run_name='__mp_main__')` 导入原入口，出现两条 `No runtime found, using MemoryCacheStorageManager`，随后正常完成。安装的 Streamlit 1.64.0 的 `cache_data_api.py:get_storage_manager()` 在没有 Runtime 时警告并返回内存 storage，不抛出请求异常；`script_runner.py` 将应用注册为 `sys.modules['__main__']` 并设置其 script `__file__`，与 spawn 重导入入口机制一致。原入口的两个顶层 cache decorator 在 spawn 导入时执行。该警告本身不是 `UNAVAILABLE` 的充分原因；未取得 Cloud 日志的 PID/调用栈，不能把每一条公网警告都逐条归属到某个子进程。
3. **此前公网失败未复现。** 本轮公网两次真实 600519 分析分别完成于 219.093 秒、28.875 秒，没有页面脚本错误。因而不能声称公网失败已修复，也不能把不稳定性唯一归因于 BaoStock、Cloud 出站限制、代理、或某个 SDK 页。Cloud 具体 SHA 仍未公开；用户报告的重新拉取成功与当前页面行为分别记录，不混同版本证明。

### 已审计的失败传播链

`app/web.py:load_analysis` → `analyze_stock` → `bounded_web_call` → spawn `_worker` → `_analyze_inprocess` → `StockAnalysisService._load` → `SymbolResolver` / `ProviderManager.fetch` → `BatchBaoStockProvider` / fallback → 日期/OHLC/raw-qfq 校验 → `build_context`。

- Provider 或校验错误被 `_load` 捕获，输出 `data_status.status=UNAVAILABLE`；Web 检查该状态并抛出展示错误，不展示内部 aggregate 的占位分数/Risk。
- worker 异常、退出/响应错误、240 秒截止原先只留下通用页面错误，具体阶段被丢弃。本轮补齐安全诊断，不改变这些数据状态或评分含义。
- 行业快照由 `SnapshotIndustryService` 只读加载；指数由 `WebMarketCache` 按股票实际日期校验。缺失/过期不会触发全行业补抓，指数也不允许在线替代。

## Evidence

以下都是本轮真实观察；离线 pytest 夹具只作为回归，不作为行情成功证据。

| 证据 | 路径（项目相对路径） | 结果 |
|---|---|---|
| 真实本地 Web 路径，空缓存 | `outputs/stage4c5/20261009T152646Z/local_live.json` | 135.500 秒，UNAVAILABLE；BaoStock timeout + AKShare qfq 校验失败 |
| 公网首次本轮提交 | `outputs/stage4c5/20261009T152640Z/public.json`、`public.png` | HTTP 200；219.093 秒完成；真实 BaoStock 2026-10-09 贵州茅台 / K 线 |
| 公网第二次独立浏览器提交 | `outputs/stage4c5/20261009T153624Z/public.json`、`public.png` | HTTP 200；28.875 秒完成；股票日期 2026-10-09；行业 DATA_STALE；B1/B2 UNKNOWN |
| 单次 fallback 前复权校验探测 | `outputs/stage4c5/20261009T153442Z/adjustment_validation.json` | 2.813 秒，PROVIDER_PROXY_ERROR；未获得可供独立核验的 qfq 响应；未评分 |
| spawn 与受保护代码审计 | `outputs/stage4c5/audit.json` | 见最终审计结果 |
| 最终完整 pytest | `outputs/stage4c5/pytest-final.xml`、`test_summary.json` | 见 Tests |
| 新增文件/差异的安全扫描 | `outputs/stage4c5/security_scan.json` | 见最终扫描结果 |

本地失败证据中的 `quant_score=0` / `risk=LOW` 是既有不可用分支的内部 aggregate 占位值，**不是合法分析结果**；Web 抛错后不展示它们。没有为了处理失败更改 ScoreEngine。

安装的 BaoStock 0.9.4 源码确认普通服务使用 `public-api.baostock.com:10030` 的 TCP socket，而非 HTTP 行情 endpoint。SDK 接收数据时循环 `recv`，部分接收异常被 SDK 打印/吞掉；项目的子进程 poll 截止用于限制这类等待。仅凭 HTTP_PROXY 环境或 Streamlit cache warning，无法证明此 TCP 请求的 Cloud 根因。本轮没有修改 Windows 代理/VPN，没有注入 Key 或执行 AI 调用；既有页面配置读取行为未改动。

## Fix

仅修改 Web 运行与诊断边界，未修改 ProviderManager、BaoStock、数据校验器、规则、权重、Risk、B1/B2、Candidate 或 AI 解释逻辑。

- `app/web.py`：spawn 名称 `__mp_main__` 下不注册 UI cache；服务进程仍保留原指数 900 秒、单股 300 秒 TTL 和 max_entries。无全局关闭缓存或更改评分 cache 语义。
- `app/web_diagnostics.py`：阶段、Provider、method、adjustment、reason_code 白名单；只分类异常，绝不序列化异常正文、URL、Key、个人路径或 traceback。失败日志使用 `QUANTSCORE_WEB_DIAGNOSTIC` JSON，诊断失败不改变正常数据结果。
- `app/web_backend.py`：在现有调用外记录证券解析、列表、股票 raw/qfq、Provider query、市场读取、行业上下文、规则评分耗时；保留异常传播及原重试。不可用结果附失败类别、快照日期、cache hit/miss、请求数、超时数。
- `app/web_runtime.py`：仅在本次 owned worker 目录保存白名单阶段进度。worker 错误/截止/响应错误时保留安全诊断，随后按原范围清理自身目录和进程树。成功响应附总耗时和预算。没有放宽 240 秒截止。
- `app/web_snapshots.py`：额外读取 manifest 的发布日期用于诊断；原日期/hash/OHLC 校验保持不变。这一字段不是可用性证明，不能使过期 snapshot 变 VALID。
- 失败页面可展开查看上述诊断，仍不展示评分。新增 pytest 验证这一行为。

本轮没有 commit/push，所以这些诊断修复**仅在本地**；当前公网成功不是这些未部署改动的效果。

## Latency

| 请求 | 总耗时 | 关键拆分 | 缓存/重试可观察性 |
|---|---:|---|---|
| 本地独立空缓存失败 | 135.500s | service init 0.408s；证券解析 2.754s；股票 raw/qfq 130.703s；市场 fetch 130.769s | 0 hit / 5 miss；9 次 wrapped Provider calls；2 次 BaoStock timeout；2 次 SDK worker starts |
| 公网首次本轮请求 | 219.093s | 首页到可提交约 28.312s；stock 分析到完成 ack + 可见 K 线 219.093s | 未部署诊断；server cache、Provider retry/timeout 均不可观察 |
| 公网第二次本轮请求 | 28.875s | 首页约 13.969s；stock 分析完成 28.875s | 不宣称 server cache hit；不是已控制缓存的 Cold/Warm benchmark |

本地嵌套阶段耗时重叠，不能相加。9 次 wrapped calls = 7 次 BaoStock SDK queries（含证券查询与失败/重试）+ 2 次 AKShare calls；不等于 HTTP/socket 底层请求次数。SDK 分页 continuation 与 AKShare 内部 HTTP/代理回退并未独立计数。

本地 BaoStock raw 的第一轮约 31.304s；第二轮约 90.890s，其中三个字段组分别约 27.673s、22.477s、9.314s 后，下一组约 31.300s 超时。重试会重新进入完整 raw fetch；没有部分字段被当成完整行情缓存。AKShare raw 约 6.360s，qfq 约 2.121s 后校验失败。未能独立保留/复核该响应，故不猜测是非正价格还是 OHLC 关系等具体违规。

### 截止/重试核验

- Web 工作预算仍为 240s；内部 RunControl 的 run budget 为 230s。
- BaoStock SDK request poll 为最多 30s；socket 默认超时同样不超过 30s；进程关闭可增加约 1s。本地 31.3s 是含 cleanup 的调用耗时，不是偷偷放宽 poll。
- ProviderManager 默认 fetch attempts 为 2，硬上限 3；DataError 不重试；`retryable=False` 不继续循环。AKShare 的每次 isolated call 为 20s；其中代理回退也受这一截止约束。
- 缩短预算的实际 spawn 测试验证等待截止、失败不缓存、诊断保留与 owned 进程/目录清理；没有用一个真实 240s hang 测试冒充公网截止证据。
- 公网实测 219.093s 完成，但仍接近预算；一次成功不证明以后稳定完成。没有自动循环测试、延长截止或按成功结果挑选统计。

## Data Status

正式行业与指数 snapshot 日期均为 **2026-09-30**。本轮实际公网股票日期为 **2026-10-09**。

- 行业：`DATA_STALE / SNAPSHOT_TRADE_DATE_MISMATCH`；页面显示 Primary Industry 暂无数据、SectorHeat `—`。
- B1/B2：原规则返回 `UNKNOWN / score=None`，没有把 SectorHeat 70 或旧行业 5d return 套到 10 月 9 日。
- 指数：原 `benchmark()` 按股票评价日期拒绝 9 月 30 日 publication，不能从旧缓存绕过日期检查，也不允许自动在线获取指数。缺 benchmark 按既有缺数据语义处理。
- 本地不可用失败发生在市场 fetch，没有有效股票评价日期，因此并未执行同日行业/指数评分；这与“过期快照导致股票 UNAVAILABLE”不是一回事。

未更新正式行业/指数数据，也未以旧行情替代当天数据。本轮 scope 不包括重新跑 full-market 或发布新 snapshot。

## Tests

定向回归：69 PASS，0 FAIL，0 ERROR。最终完整回归（含本轮新增 20 个测试项）：**总计 992 项，991 PASS，0 FAIL，0 ERROR，1 SKIP**，pytest 显示耗时 **129.11 秒**。`test_web_instrumentation_keeps_all_41_rule_results_identical` 通过，全部 41 条规则、score、Risk、行业上下文在相同输入下逐字段一致。

受保护的 `app/engine`、`app/rules`、`app/sector`、`app/data`、`app/features`、`app/services`、AI 解释与 `config` 对 HEAD 没有差异。离线基线/修改版入口导入审计分别记录 2 / 0 条 cache warning。新增代码、证据和完整 working/staged diff 的凭据扫描 **0 命中**；没有把完整 Key 或异常正文记录到报告。

使用 `.venv/Scripts/python.exe -m pytest`，TMP/TEMP/TMPDIR 和 basetemp 均在项目 `outputs/tmp/pytest`。保留全部旧测试。原 T20 HISTORICAL / SUPERSEDED_BY_STAGE3C 的既有 skip 未修改。

第一轮受限执行的 AppTest 卡在 Python Windows `socketpair → accept`；faulthandler 栈证明尚未执行 Web 请求。只停止本轮两个 owned pytest 进程，随后在允许 loopback 的执行环境重新运行，未增加 skip、未更改 asyncio 或业务逻辑绕过。

新增覆盖：异常链分类、脱敏日志、恶意字段过滤、sink 写入失败、spawn 不注册 cache、worker 失败/截止诊断与 cleanup、过期快照拒绝、有限 retry、失败页面无评分、同输入下诊断前后全部 41 条规则与 QuantScore/Risk/行业上下文完全相同。

## Remaining Issues

1. 此前 Cloud 约 180 秒失败的对应 Provider/worker 日志仍未取得，无法唯一证明原请求根因。需要本地诊断改动未来经用户授权上线后，收集同一个失败请求的 `QUANTSCORE_WEB_DIAGNOSTIC`、reason_code、快照日期、最后阶段。当前禁止 commit/push，故本轮止于本地准备。
2. 公网两次成功只证明当前可以完成真实分析，不证明稳定 latency、精准 SHA、Cold/Warm cache 或所有网络条件下可用。
3. 9 月 30 日市场 publication 已不适用于 10 月 9 日；B1/B2 缺项是诚实降级，不能人为放宽。后续正式同日 publication 更新是独立数据维护工作，本轮未自动执行。
4. 26 年历史的多个字段组及有限整体 fetch 重试可能消耗大量预算；本轮没有缩短历史、增大 timeout、改变复权或接入其他数据源。
5. 未执行 AI API 调用；没有 Key 注入、输出、持久化或截图。审计工具不读取 Key；既有页面配置读取行为不属于新增诊断。没有新增产品功能、提交、推送或进入 Stage5。

**Status = PARTIAL**。已证明并修复诊断信息丢失/spawn cache 注册副作用；已真实观察公网成功和本地失败，但原 Cloud 失败根因未闭合。
