# QuantScore Stage 4C.7 — Production Observability Closure

验收日期：2026-10-10（Asia/Shanghai）。本轮仅实现本地部署身份与请求诊断；没有 commit/push、发布操作、公网请求或 Stage5。

## Deployment Identity

正式基线 HEAD：`93e6eb2b883bebe54297a2be567a7af91d20153e`。

页面新增“部署版本 · 可核验”展开框：

- 在运行项目目录执行 Git 查询，先验证 Git toplevel 等于项目根目录，避免误报父仓库 SHA；不硬编码 SHA、不读取远程认证配置、不输出 Git 错误正文。
- 展示实际 `git_commit` 与 `source_modified`。本地为上述 HEAD、`source_modified=true`，明确当前代码包含尚未提交的修改；不能把 HEAD 本身当成全部运行源码的身份。
- 无 Git、Git 查询失败/超时或不是独立仓库时，SHA 显示 `UNKNOWN`。
- 始终计算可复核 `code_fingerprint`，算法 `sha256-path-content-lf-v1`。覆盖 app 的 Python/CSS、config YAML、requirements.txt、pyproject.toml 和 .streamlit/config.toml；相对路径和内容带长度编码，CRLF 规范为 LF，使 Windows/Linux 可比较。源文件缺失/逃逸/读取失败时不声称完整指纹。
- 排除 .env、secrets.toml、环境变量、缓存、日志和输出。只展示哈希及文件数量，不输出文件内容或绝对路径。日期/快照状态另外记录，不以源码指纹代替数据有效性。

最终本地 smoke 的 87 个源码/配置文件指纹：

`de594340a4e9bcc97e7fb2221ac2633545b00910d0491bf7383b345f7f54c0b7`

指纹反映运行目录文件；与 Git SHA、修改标记一起使用，不代表公网已经加载此代码。最终 WEB 终态日志也包含安全的 SHA/指纹/修改标记，便于关联版本和请求。

## Logging Level Diagnosis

旧实现对 START/OK 使用 INFO，对 FAILED/UNAVAILABLE/TIMEOUT 使用 WARNING。最终本地独立 smoke 中该 logger 的有效级别是 **30 / WARNING**；在 WARNING 阈值下，旧 INFO 事件会被过滤。新增测试验证 START、OK、FAILED、TIMEOUT 都能在这一阈值被捕获。

因此，日志级别过滤是**已验证的本地可复现可观测性缺口**；没有直接读取 Cloud logger 配置，不能宣称它已被证明是此前 Cloud 所有缺失事件的唯一原因。

所有白名单阶段事件和 `event_type=REQUEST_COMPLETE` 摘要现在使用 WARNING 传输级别、固定前缀 `QUANTSCORE_WEB_DIAGNOSTIC`；`status/outcome` 才表示业务成功/失败，WARNING 不等于数据故障。未修改全局/root 日志级别。sink 或日志 handler 出错不决定分析成败。

## Request Contract

每次有效单股提交在 Streamlit cache 外生成新 request_id，并以 ContextVar 和显式 spawn 参数关联 UI、父进程与 worker。WORKER 与 WEB 摘要共享 ID，但层级与耗时范围不同；不是两次分析提交。

| 字段 | 含义 |
|---|---|
| request_id / layer | 每次提交的新 ID；WEB 或 WORKER |
| outcome / reason_code | SUCCESS / FAILURE / TIMEOUT；白名单原因，不包含异常正文 |
| total_latency_seconds / latency_scope | WEB 为 loader（含缓存/worker）耗时；WORKER 为启动/后端等待耗时；不是浏览器完整渲染时间 |
| last_completed_stage / last_observed_stage | 已成功完成阶段与最后观察事件分别记录；START 不冒充完成 |
| provider_error_categories / data_error_categories | 网络/Provider 类别与 benchmark 快照不可用/过期原因分开；Web 截止不冒充 BaoStock 超时 |
| raw_seconds / qfq_seconds / measurement | 原 _fetch 组耗时，包含该组原有缓存、尝试及重试；中断时标 PARTIAL，未取得则 UNKNOWN |
| provider_retry_count / retry_scope | 原 ProviderManager._fetch callback 的实际重试次数；证券查询/SDK 内部重试仍 UNKNOWN |
| provider_timeout_count / timeout_count_scope | 已分类的 wrapped Provider 调用超时；socket/SDK 内部不可观察。中断或事件截断时不伪装完整计数 |
| sdk_poll_timeout_count | 原 Provider 暴露的 SDK poll 计数，独立展示，避免与 wrapper 层重复相加 |
| web_cache / cached_origin_request_id | 本次 HIT/MISS；无法判断时 UNKNOWN；命中时可单独标识缓存原请求 ID |
| data_cache_hits / data_cache_misses | 既有请求缓存计数；缺少观测时 UNKNOWN，不默认 0 |
| provider_requests / counter_scope | 本次 wrapped Provider 调用计数，不等于底层 socket/HTTP 请求数 |
| stock_trade_date / industry_snapshot_date / benchmark_snapshot_date | 实际评价日与出版快照日分开；缺失用 UNKNOWN，不据此修正数据状态 |
| industry_data_status / benchmark_data_status | 已有数据状态，只用于解释 |
| partial_events | worker 中断或事件窗口可能不完整，计数/耗时按部分证据处理 |

成功页面同样展示“请求诊断 · 不含凭据”；失败/超时页面保留可展开诊断且不展示新评分。只展示白名单，未知字段、路径、URL、认证值、traceback、原始行情、评分结果全文均不进入诊断日志。

## Cache Attribution / Semantics Preserved

执行标记放在既有 load_analysis 函数体内；观察器在缓存外。cache key 仍只有 code，request_id 未加入 key。命中时函数体不执行，因此本次标 HIT、新建 request_id，既有缓存原始结果不变；本次没有后端工作时 Provider 调用、raw/qfq 等为 0 / NOT_EXECUTED，而不是复制旧请求耗时。无法观察缓存的非 Streamlit loader 标 UNKNOWN。

未修改单股 TTL 300s、指数 TTL 900s、max_entries、刷新参数、缓存数据校验或过期策略。_fetch wrapper 仅代理原 callback；所有次数、终止条件和校验仍由原 ProviderManager 执行。Web 240s 硬预算、内部 230s 和 Provider 有限重试保持不变。

未修改 RuleEngine、ScoreEngine、Provider 核心、QuantScore/Risk、SectorHeat、B1/B2、Candidate 或 AI 解释逻辑。已有 41 条规则逐字段等价测试保留。

## Local Verification

最终受控 smoke 使用真实 spawn/父进程监督，但目标函数为明确标记的**离线可观测性夹具**，不是 BaoStock/600519 真实行情成功证据：

| 本地受控路径 | 实测 wall time | outcome / reason |
|---|---:|---|
| 成功 | 1.1187s | SUCCESS / NONE |
| 人工连接失败 | 0.9261s | FAILURE / PROVIDER_CONNECTION_ERROR |
| 人工阻塞，8 秒测试预算 | 8.0145s | TIMEOUT / WEB_DEADLINE_EXCEEDED |

三条路径均有匹配 request_id 的父进程终态日志；worker 中断保留已有阶段、快照日期与正在进行的 raw/qfq 部分耗时，随后清理本次 owned 目录/进程。8 秒只用于受控测试，未改变正式 240 秒预算。

AppTest 验证成功页部署/诊断框、连续提交 MISS→HIT、新 ID、同一分析仅执行一次、原 41 条规则和输入不变。既有无 Key、AI provider 失败及 Auto fallback 测试保持；导航仍不启动股票分析或 Full Market Scan。

过期快照拒绝测试保持：本地正式行业/指数仍为 2026-09-30，不可用于 2026-10-09 股票评价；DATA_STALE 和 B1/B2 UNKNOWN 未被放宽。

## Tests

首轮定向验证：102 PASS / 0 FAIL / 0 ERROR；这是后续补充测试前的阶段记录，不替代最终回归。

首轮完整回归：1015 项，1013 PASS / 1 FAIL / 0 ERROR / 1 SKIP；唯一失败为规则页展开框总数旧断言（新增部署版本框后 49→50）。保留原测试，分别断言原 48 条规则 + 状态说明及唯一版本框，没有删测试、增加 skip 或改变业务实现来规避。

最终正式运行完整 pytest：**1017 项，1016 PASS / 0 FAIL / 0 ERROR / 1 SKIP，237.98s**。相比基线新增 25 项可观测性测试，旧测试全部保留；唯一 skip 仍为历史 T20 / SUPERSEDED_BY_STAGE3C。

结果记录于 `outputs/stage4c7/closure_checks.json` 与 `pytest-final-v2.xml`。首次失败证据保留在 `pytest-final.xml`，仅将其中项目绝对路径替换为 PROJECT_ROOT，失败断言与计数未改动。最终 XML 中另有一处参数化测试名称携带用户目录前缀，已替换为 PRIVATE_USER_ROOT；测试结果与计数不变，脱敏操作记录于 closure_checks.json。

## Evidence / Files

- 修改：app/web.py、app/web_backend.py、app/web_runtime.py、app/web_diagnostics.py。
- 新增：app/web_deployment.py、app/web_observability.py、tests/test_web_observability.py、tools/stage4c7_local_verify.py。
- 测试断言兼容更新：tests/test_web_product.py；原规则数量及禁止自动扫描/分析断言保留。
- 报告：docs/STAGE4C7_RESULT.md。
- 证据：outputs/stage4c7/local_smoke_final.json、pytest-final-v2.xml、closure_checks.json。早期 smoke/定向/失败回归证据另存保留。

既有 README、Stage4C1/2 报告及 Stage4C6 等未提交成果未覆盖。本轮没有删除历史模型、缓存或其他项目文件。

## Security

本轮无 Key 注入、API 请求或真实公网分析。Git 子进程输出仅用于校验 SHA/状态；错误正文不显示。诊断事件和终态在 logger 边界再次重建，不接受任意 extra 字段。失败页面不展示原始 Provider 错误、私人路径或 traceback。

最终凭据/隐私扫描范围及结果见 `outputs/stage4c7/security_scan.json`：本轮修改/新增文本、stage4c7 输出、working diff、staged diff。测试中使用明确的人工 sentinel 检查字段过滤，不使用真实密钥。没有新截图或原始浏览器/network 日志。既有历史输出不重写以掩盖记录。

最终扫描 **18 个文本文件，凭据命中 0、个人/服务端路径命中 0**；working/staged diff 两类扫描也均为 0。受保护业务/配置文件没有差异，`git diff --check` 通过。

## Publish-Then-Public Verification

当前改动**只在本地**，受“不 commit/push”约束，本轮不升级任何公网验收结论。需后续获授权发布后，在现有 App：

1. 展开部署版本，核对实际 Git SHA、source_modified 与完整源码指纹；不能只看 GitHub。
2. 对最多约定数量的 600519 提交，取得页面 request_id 与同 ID 的 WEB REQUEST_COMPLETE 日志；成功、失败、timeout 都应有终态。
3. 同时记录外部浏览器耗时及本次 HIT/MISS，与诊断层级范围分开；确认 Cloud 实际保留 WARNING JSON。
4. 根据 stock_trade_date 核对行业/指数快照日期和数据状态；过期继续保持 DATA_STALE/B1/B2 UNKNOWN。
5. 若 Provider/worker 故障未复现，仍标 NOT_REPRODUCED，不能据本地 fixture 或一次成功证明此前 Cloud 根因。

**Stage4C.7 本地实现与验收 = PASS**。公网诊断仍为 PENDING_PUBLICATION_AND_VERIFICATION，此前 **Stage4C 总体仍为 PARTIAL**；不把本地验收冒充公网问题闭合。完成后停止，不进入 Stage5。
