# Stage 4B — AI Explanation Layer

2026-10-04。工作区以当前 GitHub main 为基线；`git fetch origin` 完成，HEAD = origin/main = `35af44f396e8effb21a50328fab9d3e721af10e7`。没有 reset/rebase/旧版本 checkout、commit 或 push。入场未跟踪的 `docs/STAGE26_FINAL_VERIFICATION.md` 与 `tools/stage26_public_smoke.py` 保留未改。

## Architecture

`app/explanation.py` 提供独立 `ExplanationProvider`、OpenAI-compatible Provider、`ExplanationService`、`ExplanationConfig` 和不可变 `ExplanationResult`。`app/web_explanation.py` 为轻量 Streamlit 适配层；原 `app/web.py` 只新增两行解释面板入口。无新增运行依赖，使用已有 httpx。

评分引擎、RuleEngine、ScoreEngine、SectorHeat、B1/B2、候选策略与 BaoStock 核心文件均未修改。解释层不导入这些执行器，不获取行情，也不读取原始 K 线或重新打分。不能创建候选结论、股票排名、新阈值或交易建议。

## Input contract

`ExplanationService.explain(analysis_result, mode, triggered)` 接受已经完成的 dict / AnalysisResult，构造独立 JSON 上下文 `contract_version=stage4b.1`：

- 股票代码/名称、evaluation_date → trade_date，原规范版本。
- 原 QuantScore、Risk、正向分/扣分、评分状态与覆盖率。
- Primary Industry、SectorHeat 既有总分/状态/日期与 B1/B2 既有结果。
- 当前 ACTIVE 规则的原 status、score/max_score、penalty/max_penalty、raw_values 或 raw_inputs、conditions、threshold_band、explanation、适用性与原因。存在行业结果时同时消费 S1–S7；不伪造缺失的行业规则结果。
- 行情和行业数据状态、来源、日期；不发送任意 metadata、chart、bars、用户自定义 prompt、API 配置或候选判断字段。

ACTIVE 注册表复用现有规则中心审计接口。只复制已有计算字段，不使用继承的历史规则来重新推导事实。上下文明确过滤敏感字段、常见密钥模式与 Windows 本机路径；上限 200KB，超限回退，不静默删掉规则证据。指纹包含规则值、得分和日期等整个白名单上下文，不以股票代码简单复用旧解释。

真实 Stage 3C 600519 存档的只读核验：48 条 ACTIVE 结果，JSON 上下文 125834 bytes；Standard Rules 原样引用 QuantScore 0、Risk HIGH、SectorHeat 70、B1 6、B2 1。此项是存档回放，不称为本轮真实网络请求。

## Output contract and grounding

Provider 只返回严格 JSON Schema 的证据组织计划：`positive_rule_ids`、`risk_rule_ids`、`unmet_rule_ids`。只允许已存在的规则 ID，拒绝重复、未知 ID、错误分组、新评分字段、自由文本、建议与预测。规则原有正分/扣分/状态决定分组，模型不能改变它们。即使模型遗漏风险或不可评规则，本地也补齐全部证据。

`ExplanationResult` 包含 source、status、reason_code、context_fingerprint、五个 sections、disclaimer；不提供新分数、风险或候选字段。五部分为当前策略匹配概况、主要正向因素、主要风险因素、未满足/不可评规则、数据状态说明。正文由本地模板填入引擎的原值与原解释，不直接采用模型生成的自由事实。第三方 Provider 只收到 disposable deepcopy，篡改其输入也无法修改原分析或本地事实。

额外限制投资建议/预测用语（含 Unicode 规范化与零宽字符处理），包括来源说明中的不允许措辞；界面以纯文本渲染，不执行模型 HTML/Markdown。UNKNOWN 不等于 FAIL，数据异常不等于 0；NOT_APPLICABLE 单独说明。始终显示：“这是对既有规则结果的解释，不构成投资建议。”

本版 AI 能力是选取解释重点、组织既有证据顺序；没有自由改写事实的能力。这一限制用于明确保证解释层不能扩展规则、制造新结论或隐藏风险，不把模板渲染本身宣称为模型推理。

## Modes / fallback

- Standard Rules：默认模式，不读取解释服务配置、不创建模型 Provider、零 LLM 调用。
- AI Explanation：仅“生成 AI 解释”按钮触发；未配置时禁用按钮并保留标准解释。
- Auto：配置有效时对当前结果一次调用；无配置自动回退 Standard Rules。

没有 Key/Model、超时、429、Provider/网络错误、重定向、截断、refusal、非 JSON、超大响应、非法证据或不安全输出，统一回退原始规则解释。异常、响应正文和 Key 不进入页面错误提示。失败也缓存当前回退结果，不在 Streamlit 重跑、导航或主题切换时形成重试循环。新结果/模式/配置有效性变化清除对应旧解释；手动再次点击可以重试。

配置来自 `QUANTSCORE_EXPLANATION_API_KEY / BASE_URL / MODEL / TIMEOUT_SECONDS` 环境变量或 Streamlit 同名 secrets，环境变量优先。`config/explanation.env.example` 为无真实 Key、无默认模型的模板；原 `.env.example` 与凭据保护测试保留。默认 URL 为 `https://api.openai.com/v1`，模型必须显式填写。没有 BYOK 输入框，Key 不存于 session state/缓存结果，不写日志、Git 或截图。

单次 `/chat/completions` HTTPS 请求、严格 JSON Schema、`store=false`、1200 输出 token 上限、1–60 秒请求超时（默认20）、64KB 响应上限；不自动重试/重定向，不继承环境代理。若兼容服务不支持此结构化协议，安全回退，不改用不受约束的文本。参考官方 [Structured Outputs 文档](https://developers.openai.com/api/docs/guides/structured-outputs)，处理拒绝与未完成响应。

## Web smoke

确定性离线 Streamlit AppTest 已验证默认标准模式、显式触发、Auto、无配置按钮禁用、Provider/非法输出回退、完整页面评分/规则仍可用、主题切换不重复调用、同股票新结果指纹失效。这些是明确标注的 offline fixture，不冒充真实模型服务。

实际 production Streamlit 浏览器 smoke **PASS**，使用本轮启动的 `app/web.py` / 8506 和真实 BaoStock 分析，未注入行情或分析结果，零付费模型调用。600519 / 贵州茅台，数据交易日 2026-09-30，原收盘1258.62、QuantScore0、Risk HIGH、SectorHeat70、B1=6、B2=1；图表与解释概况一致。Light/Dark 和 390px 均无横向页面溢出或 browser pageerror。

截图为实际运行的新解释面板：`outputs/stage4b/standard_light.png`、`standard_dark.png`、`standard_mobile.png`；JSON 为 `web_smoke.json`。Streamlit 在 main 容器内部滚动，因此截图明确滚到解释面板，避免只拍到旧头部。实际截图复核发现新面板暗色标题/正文对比度不足，已在适配层添加仅作用于该面板的样式；重启本轮常驻进程加载新模块后，实际 DOM 验证正文 rgb(217,231,251)、标题背景 rgb(22,36,59)，截图复核可读。没有改既有整体 UI 设计或 CSS 文件。

初次受限运行环境中的行情等待中断后记录为 `web_smoke_restricted_attempt.json`；随后在获准联网环境中用原业务代码完成真实分析，再用正常真实缓存复核最终面板，没有修改全局代理/Provider。模型成功与失败另由 `offline_explanation_smoke.json` / JUnit 中72项明确 offline 测试证明；不把这些 mock 当成真实 API 成功。

## Tests

完整执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=outputs/tmp/pytest/stage4b-final-4 --junitxml=outputs/stage4b/pytest_final.xml --tb=short
```

**912 total / 911 PASS / 0 FAIL / 0 ERROR / 1 SKIP**，126.55s。原840项全部保留，新增72项。唯一 SKIP 是原 T20 HISTORICAL/SUPERSEDED_BY_STAGE3C；一个既有 FastAPI/Starlette 弃用警告。Windows 使用项目内独立 basetemp。原始 XML/文本在 `outputs/stage4b/pytest_final.xml` / `pytest_final.txt`。

覆盖评分不可变、第三方 Provider 篡改隔离、已有结果白名单/ACTIVE、原 K 线排除、数据异常/不适用、完整解释、指纹、没有 Key、配置/secrets、禁止措辞、未知规则/新评分拒绝、严格 HTTP contract、timeout/限流/重定向/refusal/截断/响应过大/JSON错误、Web fallback 等。

首轮全量发现 `.env.example` 精确保护测试冲突，已恢复原模板并移入独立可选模板，未删除或放松原测试。第二轮完整回归通过；面板暗色样式修复后再次执行最终第四轮完整回归，仍0 FAIL/ERROR。

## Known limitations

**真实 API 未验证；本轮零付费模型调用。** AI 成功与失败分支均为明确标注的确定性 mock / HTTP MockTransport 验收。没有真实供应商登录/模型兼容性/费用/延迟/可用性证明；需配置兼容服务后另行做少量真实验收。

本版不接受自由生成的金融解释正文；模型只组织既有证据，原始事实由本地模板填入。第三方不支持严格结构化协议时只能回退。配置有效表示配置结构完整，不代表已验证供应商认证或模型兼容性；失败仍安全回退。没有后台解释任务、跨用户共享 LLM 缓存、聊天、RAG、用户系统、交易或 Stage 5；本轮没有 commit/push。

## Files

新增：`app/explanation.py`、`app/web_explanation.py`、`config/explanation.env.example`、`tests/test_explanation.py`、`tests/test_web_explanation.py`、`tools/stage4b_web_smoke.py`、本报告。

更新：`app/web.py`（两行解释面板入口）、`README.md`、`docs/TEST_REPORT.md`。配置模板没有真实凭据。`outputs/stage4b/` 为忽略的本地验收证据；无规范/权重/核心评分/Provider 或现有测试修改。

## Status

**PASS** — 按用户允许的无 API 确定性验收：解释架构/模式/约束/回退及全部测试通过，真实股票 Web 和最终主题/手机截图通过。真实 AI API 未验证，未将该限制描述成线上模型成功。
