# QuantScore Stage 4C.1 — Real API Completion & Public Latency Diagnosis

当前验收日期：2026-10-05。正式基线：`main @ 34bf472fba7bacb1eccfa8c13b8bea7b0dc3373c`。以下为本次有效结论；文末保留此前无API配置的历史报告，不将其误认为当前状态。

## Current Scope / Existing Work Preserved

HEAD与origin/main保持指定基线。保留此前DeepSeek Provider、fallback、配置样例、测试和未提交成果；本次只新增诊断工具、更新本报告，没有commit/push，没有进入Stage 5，没有改变评分规则、QuantScore、Risk、SectorHeat、B1/B2或Candidate。

临时凭据仅通过私有stdin和经过认证的本机回环内存连接传入验证进程，短暂注入该进程的DEEPSEEK_API_KEY，调用后移除。没有写入.env、config、Streamlit secrets、源码、Git或验收证据。测试、行情诊断进程与公网浏览器均未获得临时凭据。

## Real API Status — PASS

使用现有DeepSeekExplanationProvider / ExplanationService及官方HTTPS接口。请求模型：deepseek-flash；[官方请求契约](https://api-docs.deepseek.com/api/create-chat-completion/)及[JSON模式](https://api-docs.deepseek.com/guides/json_mode/)已核验。没有额外付费重试。

| Mode | HTTP | Result | Latency | Fallback |
|---|---:|---|---:|---|
| AI Explanation | 200 | OK / AI Explanation | 1.917 s | false |
| Auto | 200 | OK / AI Explanation | 1.379 s | false |
| Auto，无Key | 无HTTP请求 | Standard Rules / NO_CONFIGURATION | 本地回退 | true |

此前一次沙箱内尝试在DNS解析阶段失败，没有收到HTTP响应，0.320 s后正确降级。无凭据对照确认沙箱getaddrinfo失败，而正常运行环境能访问官方接口；随后在允许联网的进程完成上述两次请求。两次真实API成功，不把DNS失败或离线mock算成成功。

证据：outputs/stage4c1/completion/real_api.json。仅保存provider、请求模型、HTTP状态、结果、耗时、fallback、安全断言和原分析文件SHA256；不保存请求/响应原文、请求头、异常原文、Key或Key哈希。

## 600519 Explanation Verification

输入为Stage3C存档的真实600519.SH / 贵州茅台既有引擎结果，交易日2026-09-30，is_mock=false；这部分是规则结果重放，不声称是本次新抓取行情。本次真实新抓取另见本地延迟诊断。

既有值：QuantScore=0、Risk=HIGH、SectorHeat=70、B1=6/PARTIAL、B2=1/PARTIAL；含16条UNKNOWN，零条DATA_ERROR规则。两次解释前后完整原对象一致，五个解释分区的事实集合与Standard Rules完全一致。

模型只返回三组既有ACTIVE Rule ID，本地从原结果生成说明。不发送chart/bars/完整K线，不重新评分，不新增或隐藏风险、未知状态或数据事实。原存档没有candidate_status字段，解释层不生成它、不调用Candidate判断；既有回归另覆盖Candidate字段不变和DATA_ERROR/STALE/INCONSISTENT场景，不把离线错误场景宣称为真实行情错误样本。

两次解释没有投资建议或收益预测输出，均保留：**“这是对既有规则结果的解释，不构成投资建议。”**

## Public Deployment / Cold / Warm Latency

公网：[QuantScore](https://quantscore-grrgr4oqy5pfhfqnyp9q9b.streamlit.app/)。使用真实浏览器，无mock、路由替换或数据注入。未配置公网Key，未触发公网付费AI请求或Full Market Scan。

首页HTTP 200；首次导航DOM ready为6.031 s。实际检测并唤醒休眠应用，首页可用累计70.781 s，包括导航、Cloud唤醒及页面等待，**不是精确Streamlit进程启动时间**。

超时后另做一次只读首页检查，没有再次点击股票分析：HTTP 200，首页可用15.000 s，Light/Dark切换PASS，390px无横向溢出PASS。真实截图：outputs/stage4c1/completion/public/home_checks/home_light.png、home_dark.png、home_mobile.png；对应public_latency.json记录stock_analysis_triggered=false。这不代表600519分析页或Warm分析已成功。

本次公网600519首次分析在1200秒预算内未返回完整结果，最后轮询1199.812 s，结果为PARTIAL / ANALYSIS_TIMEOUT。Cold click-to-result没有完成值；只能报告等待至少1200秒。Warm为NOT_MEASURED，不能因旧界面、超时请求或本地缓存成功伪造Warm值。没有再启动第二次长时间股票分析。证据：outputs/stage4c1/completion/public/public_latency.json与真实home_light.png截图。

Cold定义为新浏览器首次分析，服务器进程/cache是否冷为UNVERIFIED；Warm定义为同会话即时重复分析。公网没有server spans/cache events，也未提供Cloud服务器日志，provider init、benchmark/raw/qfq、industry/B1/B2、scoring、render、retry/timeout的公网内部精确时间均未观测，证据保留null。不能从浏览器wall time倒推出它们。

## Controlled Local Cold / Warm Breakdown

使用独立新SQLite诊断缓存，不清空生产缓存。只调用现有600519单股及其所属行业链路，不扫描全市场。插桩仅在诊断进程中，不改生产代码、窗口、重试、超时或业务语义。

| Component | Local cache-cold | Local cache-warm | Meaning |
|---|---:|---:|---|
| Provider / service init | 0.3616 s | 0.0082 s | 服务对象初始化，不含后续SDK login |
| 单股raw + qfq fetch | 67.4837 s | 无SDK请求 | 冷运行两个fetch合计 |
| 单股benchmark fetch | 28.9930 s | 无SDK请求 | 冷运行benchmark fetch |
| Industry / B1/B2输入 | 349.6407 s | 5.3581 s | 成分股、metadata、calendar、行业benchmark及计算 |
| Rule scoring | 17.5968 s | 17.6924 s | 原ScoreEngine，含B1/B2 |
| 图表数据/特征 | 1.6715 s | 1.4864 s | 缓存行情生成120交易日图表 |
| Plotly figure build | 1.0110 s | 0.0460 s | 本地构图，不含浏览器实际渲染 |
| Complete analysis，含嵌套阶段 | 471.5417 s | 27.7135 s | 不得再与行业/评分相加 |
| Total local wall time | **474.609 s** | **29.285 s** | 两次正常真实分析 |
| Cache hits / misses | 5 / 111 | 116 / 0 | 实际DataCache事件 |
| SDK queries / errors | 118 / 0 | 0 / 0 | 无失败请求或失败重试 |

两次均取得真实贵州茅台、2026-09-30、BaoStock、120交易日图表、行业VALID和相同QuantScore/Risk。整体DataStatus=PARTIAL遵循现有缺字段语义，不改为假数据或无风险。

SDK worker总时间411.2236 s：单股加载96.3925 s/13次、行业314.8311 s/105次。worker含启动子进程、SDK login/query/logout和传输，不等于纯网络RTT。排队计时和并发fetch耗时有重叠，不能累加为wall time。

本地DataCache热运行仍执行评分；Web的st.cache_data(ttl=300)命中可跳过后端，两者不是同层缓存。完整pytest曾与本地诊断部分时间重叠，此结果用于瓶颈定位，不是隔离机器负载后的性能基准。证据：outputs/stage4c1/completion/local/local_latency.json及latency_diagnosis.json。

## 740s Root Cause

历史outputs/stage4c/public/public_smoke.json的740 s是点击分析后按10秒轮询记录的结果等待时间，当时cloud_configuration_present=false、ai_attempts=0，首页先已完成。因此AI与首页唤醒均不在该740 s内。

本次已复现的主瓶颈为**同步数据获取，特别是所属行业/B1/B2的成分股请求扇出**：

1. PrimaryIndustryService.build获取全部所属行业raw/qfq、metadata与calendar。本地行业输入占总wall time **73.67%**；94次行业raw/qfq fetch对应47个成分股，不是Full Market Scan。
2. ThreadPoolExecutor(3)受BaoStock全进程_REQUEST_LOCK约束，SDK实际串行。每次查询启动worker并login/logout，成功请求间隔0.3秒。
3. 单股及benchmark默认从2000-01-01取完整历史，超过120天按三列payload拆分请求，增加查询/分页。单股raw/qfq与benchmark另耗时约96.48秒。
4. 热缓存消除全部118次SDK请求，wall time由474.61降至29.29秒。原规则评分约17.6秒、真实AI约1.4–1.9秒，不是该数据冷启动主耗时。

这是主瓶颈的真实复现与路径定位，**不是过去740 s逐秒还原**。历史云端缺逐阶段和失败计时，无法确定其重试/超时占比；本地无失败不表示历史云端无失败。机器性能/路由不同，本地时间不能替代云端各阶段时间。

路径：app/web.py::load_analysis → app/web_backend.py::analyze_stock → ProviderManager::_fetch_from_provider → BaoStockProvider::_history/_call/_call_once；StockAnalysisService同步PrimaryIndustryService.build后再评分。

## Tests — PASS

完整实际结果：**938 total / 937 PASS / 0 FAIL / 0 ERROR / 1 SKIP**，158.53 s。唯一SKIP为旧T20 HISTORICAL/SUPERSEDED_BY_STAGE3C；一条既有FastAPI/Starlette弃用警告。原测试全部保留。

沙箱首次回归在FastAPI TestClient停滞，正常环境核验同一原测试后通过（1.24 s），停止已定位的停滞进程并正常完整回归。没有修改业务逻辑规避环境限制。测试无临时Key，TMP/TEMP/TMPDIR均在项目D盘。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=outputs/tmp/pytest/stage4c1-completion-final --junitxml=outputs/stage4c1/completion/pytest.xml --tb=short
```

## Current Security Scan

最终扫描结果：PASS。扫描项目文件8665个，命中0项，不可读文件0个。扫描git diff、staged diff/blobs以及最终报告/输出，未写入或回显凭据；凭据已从环境移除，联网验证进程已退出。证据：outputs/stage4c1/completion/security_final.json。本地依赖虚拟环境、.git对象与Python缓存排除，Git工作/暂存内容单独检查。范围：项目文件、git diff、staged diff/blobs、docs、outputs、logs及截图二进制。检查临时Key完整值、主体、大小写、UTF16、Base64、hex、百分号/Unicode转义及组合形式，匹配仅输出路径/类型，不输出内容。截图前检查可见文字，临时Key从未送入浏览器；二进制扫描不是像素OCR，不声称穷尽所有隐写/编码形式。

## Files Added / Updated This Completion

- tools/stage4c1_completion.py：最小真实调用、无Key fallback与内存凭据扫描。
- tools/stage4c1_public_latency.py：真实公网首访/重复分析诊断，明确可见性边界。
- tools/stage4c1_local_latency.py：真实单股冷/热缓存分阶段计时。
- docs/STAGE4C1_RESULT.md：当前结果与历史边界。
- outputs/stage4c1/completion/：脱敏API元数据、诊断、截图、JUnit、安全报告；gitignore排除。

## Current Remaining Limitations / Status

**PARTIAL — Real API完成及完整回归PASS，Public Cold/Warm未闭环。** 公网首页可访问，但本次600519冷分析1200秒超时，Warm未测；公网内部阶段及历史740秒精确拆分需要云端日志/计时证据。已明确复现本地主要数据获取瓶颈，不把本地测量冒充云端验证。禁止commit/push，因此本地DeepSeek适配未发布到公网，临时Key未配置至公网；无Key公网仍沿用已有Standard Rules路径。最终安全检查结果另见上方Security Scan；不进入Stage 5。

---

## Historical Report — Prior Configuration-Free Verification

**以下保留原报告原文作为历史对照；REAL_API_CONFIGURATION_REQUIRED与937 PASS/169.43 s是此前验收，已由本报告上方本次真实API/回归结果替代。以下“本轮”指此前阶段，不指2026-10-05临时授权。**

# Stage 4C.1 — DeepSeek Explanation Provider Verification

## Scope / Baseline

基线为 `main @ 34bf472fba7bacb1eccfa8c13b8bea7b0dc3373c`。本轮只补充解释服务配置/API兼容、测试、smoke与说明；没有改评分规则、QuantScore、Risk、SectorHeat、B1/B2或Candidate。没有commit/push，没有进入Stage 5；之前未提交的Stage26/Stage4C文件原样保留。

## DeepSeek Configuration

环境变量或Streamlit secrets同名顶层键：

| Key | Behavior |
|---|---|
| DEEPSEEK_API_KEY | 仅运行时读取，配置样例为空，repr隐藏，不导出到证据 |
| DEEPSEEK_BASE_URL | 默认 https://api.deepseek.com，只接受官方HTTPS域名与空路径或 /v1 |
| DEEPSEEK_MODEL | 默认 deepseek-flash，可显式覆盖 |
| DEEPSEEK_TIMEOUT_SECONDS | 默认20秒，允许1–60秒 |

同名环境变量优先于secrets。已有QUANTSCORE_EXPLANATION_API_KEY非空时，整套通用配置优先，不把其Key与DeepSeek URL混用。通用配置显式指向官方DeepSeek时，也采用DeepSeek请求契约。Standard Rules不读取解释配置、不调用模型。

## API Contract / Safety

本轮查验[官方Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)和[JSON模式说明](https://api-docs.deepseek.com/guides/json_mode/)。采用 `/chat/completions`、`json_object`、明确JSON示例、`max_tokens=1200`、`thinking.type=disabled`；不向DeepSeek发送OpenAI专属store/max_completion_tokens。使用当前文档模型名，未凭旧记忆沿用历史deepseek-chat。

DeepSeekExplanationProvider复用既有ExplanationProvider/Service的HTTP安全限制、读取完整结果的白名单与本地渲染。模型仍只输出positive_rule_ids/risk_rule_ids/unmet_rule_ids三组已有规则ID；JSON Object不保证Schema，必须再通过既有严格字段、ID、分组、重复与禁止措辞校验。不能写入新分数、事实、候选判断或投资建议，不能隐藏风险与UNKNOWN。输入为已完成引擎结果，不发送完整原始K线。

单次请求，无重试/重定向，不继承代理凭据，200KB上下文/64KB响应限制不变。非200、超时、限流、空/非法/截断/不安全响应均降级到Standard Rules。仅新增HTTP状态整数与耗时诊断，不保存请求头、请求体、响应原文或异常原文。页面始终保留“这是对既有规则结果的解释，不构成投资建议。”

## Real API Status

**REAL_API_CONFIGURATION_REQUIRED**。实际生产配置读取路径检查当前Python环境和Streamlit secrets后，config_valid=false；没有注入可用的DeepSeek配置，真实模型调用数为 **0**。

用户聊天中出现的密钥未被使用、保存、复述或写入文件；应撤销并更换，再仅注入实际运行服务器的环境变量/Streamlit秘密配置。本轮不以聊天文本自动创建环境变量，也不要求把真实Key粘贴到代码。

`tools/stage4c1_deepseek_smoke.py --allow-real-api`已实际执行。无配置按要求停止真实API部分；证据 `outputs/stage4c1/deepseek_smoke.json`。未来有配置时该脚本至多手动AI一次、Auto一次；首次失败即停止后续真实调用，没有额外付费重试。仅记录请求模型名、状态/原因、HTTP状态和耗时，不保存Key或模型内容。

## Smoke / Fallback / Web

输入是Stage3C存档的真实600519.SH既有结果，交易日2026-09-30，is_mock=false；本轮为**历史结果重放**，没有重新请求行情，也不是新版公网部署证明。完整原对象前后相同，解释上下文无chart/bars/candidate_status。

无Key Auto返回NO_CONFIGURATION；模拟HTTP503返回PROVIDER_ERROR，两项回退通过。503为明确标注的离线MockTransport测试，不冒充真实API成功。

新增Web AppTest确认DeepSeek环境变量经现有配置入口选择正确Provider；成功与失败情况下页面均不崩溃，重跑不重复调用，原分析不变。这些是离线Web/模型fixture，不是真实模型或公网成功。Stage4C已经完成的公网600519/Light/Dark/Mobile证据保留在原报告；本轮禁止push，所以公网不会自动获得本地适配。

## Tests

定向测试实际结果：**98 PASS / 0 FAIL**。新增26项，覆盖DeepSeek环境/secrets优先级、配置家族隔离、官方端点限制、JSON请求契约、AI/Auto选择、非法/不安全输出、HTTP失败、单次调用、既有事实不变与Web失败降级。原测试均保留。

完整回归实际结果：**938 total / 937 PASS / 0 FAIL / 0 ERROR / 1 SKIP**，169.43秒。唯一SKIP为原有T20 HISTORICAL / SUPERSEDED_BY_STAGE3C，1条既有FastAPI/Starlette弃用警告。没有删除或跳过实现失败的测试。

实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=outputs/tmp/pytest/stage4c1-final --junitxml=outputs/stage4c1/pytest_final.xml --tb=short
```

原始证据：`outputs/stage4c1/pytest_final.xml`。

## Security Audit

已检查git diff与整个outputs文本目录，并纳入已跟踪/未忽略新文本文件。初次扫描4888个文本文件，完整测试与报告完成后重新扫描4931个文本文件，常见长sk格式Key/私钥标记均无命中，git diff无命中且diff --check通过；证据 `outputs/stage4c1/security_audit.json`。不扫描或复制合法本地secrets内容，不扫描二进制图像；这是范围明确的模式审计，不声称穷尽所有秘密格式。配置样例Key为空，无真实凭据被写入证据。最终HEAD与origin/main仍匹配正式基线。

## Files Added / Updated

- app/explanation.py：DeepSeek配置、Provider适配与安全诊断。
- config/explanation.env.example：空Key模板。
- tests/test_deepseek_explanation.py、tests/test_web_explanation.py：新增离线契约与Web回归。
- tools/stage4c1_deepseek_smoke.py：最多两次真实调用的安全验收入口。
- README.md、docs/STAGE4C1_RESULT.md：使用方式与实际验收状态。

## Remaining Limitations / Status

**PARTIAL — REAL_API_CONFIGURATION_REQUIRED**。

适配与离线回退已验证；真实认证、真实模型响应、AI Explanation一次成功及Auto一次成功尚未验证。密钥安全注入后方可做最小真实验收。本轮没有部署、commit/push或Stage 5操作。
