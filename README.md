# QuantScore

QuantScore 是可解释的股票技术面策略匹配评分系统：回答“当前股票符合这套规则的程度，以及为什么得到这个分数”。它不预测涨跌，不给买卖推荐，不声称回测收益。

评分规范先于代码。唯一规则真源为 `docs/QuantScore_V1.4_机器可执行评分规则规范_真实数据接入版.docx`。V1.1/V1.2/V1.3 原件保留并校验 SHA256。V1.4 继承 V1.3 冻结评分语义，只补充数据契约和统一基准 `000001.SH / 上证指数`；所有新结果 `spec_version=1.4`，`assumption_version=v1.3` 表示评分语义来源。

V1.4 不存在未解决的用户交易规则含义问题。UNKNOWN 表示必要数据缺失或无效、历史不足、确认期未完成、未实现规则或人工证据缺失，不等于 FAIL。

## Stage 4B AI Explanation

单股分析新增 `Standard Rules / AI Explanation / Auto`。默认 Standard Rules 完全不读取解释 API 配置或调用模型；AI Explanation 仅由“生成 AI 解释”按钮触发；Auto 在配置有效时对当前结果调用一次。切换主题、展开规则或页面重跑不会重复调用；结果指纹改变后清除旧解释。无配置、超时、限流、无效或不安全响应都回退标准规则解释，评分与分析仍正常。

AI 是只读解释层：输入来自现有引擎的股票、交易日、QuantScore、Risk、行业、SectorHeat、B1/B2、ACTIVE 规则状态/原始值/条件/解释和数据状态，不发送原始 K 线、任意 metadata 或候选判定指令。模型只选择、组织既有证据 ID，不能返回新分数或自由事实；本地模板填入原始事实，且不能隐藏风险或 UNKNOWN。不会改变评分、风险、行业热度或策略匹配候选。页面明确标注：“这是对既有规则结果的解释，不构成投资建议。”

可选环境变量或 Streamlit secrets（同名顶层键）：

```toml
# 本地 .streamlit/secrets.toml；已被 .gitignore 忽略。不要提交实际密钥。
QUANTSCORE_EXPLANATION_API_KEY = "<你的解释服务密钥>"
QUANTSCORE_EXPLANATION_BASE_URL = "https://api.openai.com/v1"
QUANTSCORE_EXPLANATION_MODEL = "<支持 Chat Completions 严格 JSON Schema 的模型 ID>"
QUANTSCORE_EXPLANATION_TIMEOUT_SECONDS = 20
```

环境变量优先；`config/explanation.env.example` 仅为模板，程序不会自动加载 `.env`。模型没有默认值，需显式指定；核心功能不需要任何 LLM 密钥。调用为 OpenAI-compatible `/chat/completions`，HTTPS、严格 JSON Schema、`store=false`、单次请求、1–60 秒超时，无自动重试或重定向，不继承本机代理。兼容服务不支持该契约时安全回退，不偷偷切换为自由文本。请求上下文上限 200KB，响应上限 64KB。密钥不进入页面、session state、日志、异常说明或 Git；本阶段没有 BYOK、聊天、RAG 或用户系统。

确定性 HTTP mock 与 Streamlit AppTest 验证独立记录，**真实付费 API 未验证**，不将 mock 称为在线成功。实际 Web smoke 与测试见 [Stage 4B 报告](docs/STAGE4B_RESULT.md)。本阶段不 commit/push，不进入 Stage 5。

### Stage 4C.1 DeepSeek 配置

支持环境变量或 Streamlit secrets 顶层键 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_TIMEOUT_SECONDS`。只在实际运行环境中安全填写Key，不粘贴到源码、配置样例、聊天或Git。模板中的Key保持为空，程序不自动读取 `.env`。

```toml
# 在 Streamlit Cloud 的 App Settings → Secrets 中配置，勿提交实际值。
DEEPSEEK_API_KEY = "<仅在秘密配置中填写>"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"
DEEPSEEK_TIMEOUT_SECONDS = 20
```

同名环境变量优先于secrets。已有 `QUANTSCORE_EXPLANATION_API_KEY` 若非空，整套通用配置优先；不会混用两个服务的Key/URL。DeepSeek默认官方HTTPS地址、`deepseek-flash`、20秒超时；可显式指定模型。DeepSeek专用配置只允许官方域名，路径为空或 `/v1`。默认模型与请求参数依据[官方当前API文档](https://api-docs.deepseek.com/api/create-chat-completion/)与[JSON模式说明](https://api-docs.deepseek.com/guides/json_mode/)核验，不沿用已退出的历史模型名。

DeepSeek使用 `json_object`、`max_tokens=1200`、非思考模式，仍只返回三个已有规则ID列表。JSON模式不保证Schema，因此本地严格验证字段、ID、分组及禁止措辞；空、非法、截断响应均回退，不自动重试，不回退成自由文本。DeepSeek请求不发送OpenAI专属 `store` / `max_completion_tokens`；其余安全限制不变。

可运行 `python tools/stage4c1_deepseek_smoke.py --allow-real-api`：只读取环境/secrets，使用真实600519历史引擎结果，最多AI Explanation一次、Auto一次；首次失败即停止后续真实调用。无配置记录 `REAL_API_CONFIGURATION_REQUIRED`，不联网调用模型。证据只含状态、请求模型、HTTP状态与耗时，不保存Key/请求体/模型原文。此脚本不是新行情请求或公网新版部署验收；本轮无commit/push，云端不会因此自动升级。见 [Stage 4C.1 报告](docs/STAGE4C1_RESULT.md)。

## Stage 4A Web App

Web 提供首页 Dashboard、单股分析、板块热度、策略匹配候选、规则中心五个页面，保留 Light/Dark 与移动端布局。单股分析继续调用现有 `StockAnalysisService`，展示所属行业、SectorHeat、B1/B2 和逐条原始证据；页面不重新计算评分或候选条件。

板块与候选页面只读取后台正式 `screening_details.json`，**打开页面与切换导航不会启动全市场扫描**。读取路径配置于 `config/web.yaml`，默认依次审计 `outputs/runtime/daily/` 和 Stage 3C 正式 `outputs/stage3c/full_market/`，按交易日、生成时间选择最新合法完整 Universe 结果。不会读取 Stage 3C.1 性能子集、mock、RUNNING/STOPPED 或未完成输出。PARTIAL 后台结果仍可展示，但保留各行业的数据异常与空分。界面沿用后台候选成员及顺序，不追加 Coverage 门槛或 TopN 限制。

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/web.py
```

后台发布到 Web 的结果必须包含完整行业/股票/候选列表、统计、真实来源标记和带时区生成时间；Web 服务只需要读权限。后台应原子替换完整发布文件，不要让 Web 读取写到一半的文件。`config/web.yaml` 只接受项目内相对路径。每次页面重新运行都会读发布结果；指数日线通过独立按钮加载，避免慢数据源阻塞首页。

Streamlit Cloud 入口仍为 `app/web.py`，Python 3.11，无新增运行依赖或 Secrets。`outputs/` 保持忽略，部署包没有后台结果时显示“暂无最新筛选结果”，不会尝试扫描或依赖本机缓存。上线展示正式结果需要另行提供上述发布文件；本阶段没有添加后台调度器、远程结果同步或自动部署。单股行情失败也不会以假数据替代。

页面始终标明历史日线 / 非实时、数据交易日、生成时间、来源与数据状态。数据错误不等于 0 分，不可评不等于不匹配；0 候选正常展示空状态。策略匹配候选不构成股票推荐或投资建议。当前 ACTIVE 规则共 48 条，44 IMPLEMENTED、4 NOT_IMPLEMENTED（E4/E5/R6/R10）；S1–S7 的独立实现状态来自实现矩阵与当前 Stage 3B 冻结条款，不使用单股登记中的旧占位状态。

实际测试与浏览器证据见 [Stage 4A 报告](docs/STAGE4A_RESULT.md)。以下较早阶段段落保留为历史验收记录，当前运行环境为项目 `.venv`，不需要 `.deps` 或设置 `PYTHONPATH`。本阶段不 commit/push，不进入 Stage 4B。

## Stage 3C.1 Performance & Runtime Optimization

**PASS（2026-10-03）**：仅优化后端运行与缓存，评分规范、权重、候选门槛及 SH/SZ Universe 不变。固定真实 BaoStock 存档基准：3 个行业、406 个预期成分股、47 只合格行业股票；基线 3248.499s，最终冷回放 871.855s，热回放 235.550s。传输调用 797 → 685 → 9；这些是标准化数据回放调用数，不是在线 SDK 分页请求数，也不能外推为全市场运行承诺。冷运行比率包含主机调度差异；完整规则算法没有改变。

新增范围缓存与跨日重叠校验、复权变化回退完整刷新、完整评分输入指纹缓存、校验版本/日期/Universe 的 checkpoint/resume，以及请求、行业、股票、整轮期限。独立真实网络验证已取得 600519 raw/qfq 和上证指数；同日复用 0 次请求，跨日仅补重叠与新增日期。真实存档断点恢复只补剩余 46 只股票，全部业务结果一致。

完整回归 **788 项：787 PASS / 0 FAIL / 0 ERROR / 1 历史 SKIP**，原测试保留。证据和限制见 [Stage 3C.1 报告](docs/STAGE3C1_RESULT.md) 与 `outputs/stage3c1/`。没有重新跑全市场、提高 Provider 并发、改 UI、进入 Stage 4 或 commit/push。

```powershell
.\.venv\Scripts\python.exe -m app.cli screen --json --output-dir outputs/runtime/daily
# 同日期、同版本、同范围中断后恢复；保留原 industry / limit 参数
.\.venv\Scripts\python.exe -m app.cli screen --json --output-dir outputs/runtime/daily --resume
```

可设置 `--request-timeout 60 --sector-timeout 1800 --stock-timeout 300 --run-timeout 43200`。整轮期限到达返回 STOPPED 与未完成标记，保存断点并以非零退出码结束；单对象错误保持 NOT_EVALUABLE，不能作 0 分。跨交易日须另建输出目录。`--refresh` 完整刷新行情；Python/pandas/numpy 升级后清理派生评分缓存 `data/cache/screening_scores.sqlite3`，保留原始行情和历史冻结快照。当前测量支持后台批处理方向，不支持交互式全市场冷扫描的承诺。

## Stage 2 状态

**Stage 2.2 / Stage 2 = PASS**：BaoStock真实取得贵州茅台、平安银行的raw/qfq/volume/turnover和上证指数；CLI与FastAPI成功，三种证券共45项M5/M30/M60手工均值比对通过。417项测试：416 PASS / 0 FAIL / 1 SKIP；原400项全部保留。首轮指数超时后真实复测成功，失败证据未删除。未进入Stage 3。

实际测试数量见 [测试报告](docs/TEST_REPORT.md)，真实请求证据见 [Smoke Report](docs/STAGE2_DATA_SMOKE_REPORT.md)，入场审计见 [Current State Audit](docs/STAGE2_CURRENT_STATE_AUDIT.md)。离线通过不代表真实行情分析已成功。

## 运行

Python 3.11 及以上，在本项目创建独立环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
python -m app.cli analyze 600519
python -m app.cli analyze 600519 --json
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

交互文档：`http://127.0.0.1:8000/docs`。

| 路由 | 功能 |
|---|---|
| GET /api/health | 版本、基准、未主动探测的 Provider 状态 |
| GET /api/rules | 48 条规则、实现状态、来源与权重 |
| GET /api/analyze/{symbol} | 单股完整解释，支持 as_of、refresh |
| GET /api/data/status/{symbol} | 历史长度、字段覆盖、基准与错误 |

当前工作区的依赖位于 `.deps`，复现时先设置：

```powershell
$env:PYTHONPATH = ((Join-Path (Get-Location) '.deps') + ';' + (Get-Location).Path)
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest --junitxml=outputs/pytest-results.xml
python -m tools.stage22_smoke
python -m tools.generate_reports
```

真实 smoke 自动按数据源最近已完成日线分析，不写死历史验收日；真实数据可用时执行五个日期的 M5/M30/M60 独立均值核验。网络不可用时记录 NOT_EXECUTED，不计通过。CLI 数据不可用返回退出码 1，JSON 仍合法；非法输入返回 2。

## 数据流程

SymbolResolver → ProviderManager → raw/qfq 与上证指数 → 涨跌停解析 → 数据验证 → 统一特征和周/月聚合 → RuleEngine → ScoreEngine → AnalysisResult。

- BaoStock 0.9.4 为默认源，不需要 Token；保留 AKShare 1.18.97，随后为有 Token 的 Tushare。顺序由 config/data_providers.yaml 配置。
- 裸代码按真实证券表解析；`000001` 为 `000001.SZ / 平安银行`，显式 `000001.SH` 或 `SSE_COMPOSITE` 为指数。所有股票的 A1/A2/A3 均使用上证指数。
- raw/qfq 分开获取、按日期严格合并；均线、趋势用 `*_adj`，涨跌停、T/一字板用 `*_raw`。成交量统一为股，换手保留百分点（5 表示 5%）。
- Tushare 是可选回退及增强源；另行安装 `tushare` 并在环境中配置 TUSHARE_TOKEN 后才启用 stk_limit / daily_basic。无 Token 或无权限时继续默认流程。
- 涨跌停优先 Provider 历史报告值，其次带日期、规则和证券状态证据的计算值。默认 AKShare 未提供可靠历史 ST/特殊上市期/参考价证据时，输出 LIMIT_PRICE_UNRELIABLE，绝不把全市场写死 10%。
- SQLite 缓存支持 TTL、last_updated 和 refresh；AKShare 无 timeout 的接口由独立子进程硬截止。单项获取最多尝试 3 次。
- 股票失败返回数据不可用；基准失败只影响基准规则；涨跌停价缺失只影响相应规则。结果保留来源、原始值、条件、说明和客观 UNKNOWN 原因。

详细字段见 [数据契约](docs/DATA_CONTRACT.md) 和 [Provider 设计](docs/DATA_PROVIDER_DESIGN.md)。

## 已实现规则

48 条登记规则中：35 IMPLEMENTED、0 PARTIAL、13 NOT_IMPLEMENTED。实现状态 PARTIAL 与执行结果中的部分得分状态不同。

已实现：A1–A3、B3、C1–C6、D1–D5、E1–E3、F1-N/F1-T/F1-O/F1-X/F1-Y、F2/F3、R1–R5、R7–R9、R11/R12。Stage 2 新增 D2、F1-X、F2、R3、R5。

未实现：S1–S7、B1/B2（后续板块模块）；E4/E5/R10（筹码分布）；R6（分钟数据）。B3 已有离线执行器，但常规单股接入不提供完整板块成员历史，其结果仍可 UNKNOWN。完整证据见 [实现矩阵](docs/RULE_IMPLEMENTATION_MATRIX.md)。

## 评分与 Coverage

正向 A/B/C/D/E/F 分类封顶为 10/15/25/20/15/15，总分不超过 100；F1 只取最高单项，F2 依赖有效 F1。冲突先取消正向分，风险每条只扣最高严重度。FinalQuantScore=max(0,PositiveScore−RiskPenalty)，不按已知规则重新归一化。

Coverage 衡量是否能判断，FAIL/INVALIDATED 等确定状态也计入；UNKNOWN/未实现不计。低于70%不显示完整匹配等级，70%至90%为 PARTIAL，90%及以上为 FULL。风险等级仅描述已观测规则。完全缺行情时聚合的0仅是已知贡献为空，必须与 UNAVAILABLE/INSUFFICIENT 一起理解。

## 时间与限制

as_of 先截断股票、基准，再计算均线、峰谷、平台与形态；当前未收盘日线不进入确认。周/月自行从日线聚合，只有已完成周期参与；没有完整交易所日历时保守排除缺工作日周期，可能减少周/月覆盖。

R7 只消费不可变快照，不用未来数据重算信号日。历史 as_of 请求不会新建历史快照；已有快照的后续三日确认单独放在 r7_forward_confirmation，不回写历史分数。V1.3 兼容快照保留显式原版本与价格校验。获取时 qfq 不是历史复权快照，除权口径改变时 R7 可能返回 INVALID_SNAPSHOT。

原295项测试保留；T20自动排名仍是唯一排除场景。Stage 2 历史验收时尚无 Git；Stage 2.6 已初始化独立 main 分支，远程仓库待用户确认。`.env`、凭据和缓存由忽略规则保护。

## Future Work

Sector Heat Score、风口板块识别、成分股筛选、自动排名、用户反馈、分钟/筹码数据与真实回测均未完成。本轮停止在 Stage 2，不进入 Stage 3。

## Stage 2.1 历史一致性与网络复核（已由Stage 2.2接续）

新结果版本统一为 spec_version=1.4、assumption_version=v1.3、data_contract_version=1.4。C5活动验收为T02_NEW，R7保持80分/非HIGH/后3完整日/+3%高价失效规则；旧T02及70分/2%文本仅保留历史标记。没有调整评分权重。

Provider在独立子进程遇ProxyError时临时直连一次并恢复代理读取函数，不修改Windows代理。真实日线端点在代理与直连路径均失败，CLI/API返回UNAVAILABLE；Stage 2.1仍为PARTIAL。见docs/STAGE2_NETWORK_DIAGNOSIS.md及docs/STAGE2_DATA_SMOKE_REPORT.md。

## Stage 2.2 当前限制

实际行情最新日为2026-09-24。真实数据分析可用，但可靠历史涨跌停价、筹码/分钟等字段仍可能缺失，data_status=PARTIAL与规则UNKNOWN不等于网络不可用。前复权不是历史时点快照。评分规则与权重未改；35条已实现、13条未实现状态保留。BaoStock源代码/日期/原始字段与provider/data_provenance均可追溯。

## Stage 2.5 · Public Single-Stock Web MVP

**本地验收PASS**：真实600519页面分析成功，桌面/手机浏览器检查通过；433项测试，432 PASS / 0 FAIL / 1 SKIP。具备公开部署配置，尚未实际公开上线。详见docs/STAGE25_WEB_REPORT.md。

Streamlit页面直接调用现有StockAnalysisService，未复制或修改评分规则。提供单股输入、真实行情分析、QuantScore/Risk Level、正向及风险Coverage、Positive Score、Risk Penalty、主要原因与全部规则明细（含可展开raw_values）。页面明确显示：QuantScore 是策略匹配分析工具，不构成投资建议。

### 本地运行

在QuantScore项目根目录、已安装requirements.txt的虚拟环境中执行：

```powershell
streamlit run app/web.py
```

浏览器打开 http://localhost:8501 。当前工作区使用项目本地依赖时：

```powershell
$env:PYTHONPATH = '.deps;.'
$env:PYTHONIOENCODING = 'utf-8'
python -m streamlit run app/web.py
```

只分析股票；600519为贵州茅台、000001为平安银行。初次完整历史分析可能需要数分钟。页面采用桌面双栏金融仪表盘、五张评分卡和响应式移动布局，支持Light/Dark切换。结果缓存最多5分钟，原有行情缓存保持核心服务的TTL；每次都显示数据日期和真实Provider，源数据日期可能落后于当前日期。失败结果不缓存，重新提交失败会清除旧分析。

### Streamlit Community Cloud部署

1. 将本项目作为独立GitHub仓库上传，保留app、config、requirements.txt和.streamlit/config.toml等运行文件；不要上传.deps、.venv、数据缓存、secrets、Token或本地运行日志。Stage 2.6 已准备独立本地 Git，目标仓库为 https://github.com/wei20ovo-commits/QuantScore 。
2. 在 https://share.streamlit.io 登录，选择Create app，选择仓库及分支，Main file path填写 `app/web.py`。
3. 在Advanced settings选择Python 3.11，与本地验收版本一致。Cloud按根目录requirements.txt安装依赖，并读取.streamlit/config.toml。
4. 默认BaoStock不需要密钥，不需要额外启动FastAPI。部署后用600519检查名称、数据日期、真实来源和规则展开；确认云端可以连接BaoStock服务器。
5. 如云端行情网络受限，页面诚实报错，不会用示例数据补造分析。云端出站连通性必须在实际部署环境另行确认；本轮不声称已取得公网地址。

官方参考：[依赖声明](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)、[部署流程](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)。

Web只复用现有核心的本地行情缓存与冻结快照，没有新增数据库、账号或用户数据存储。Cloud本地文件不是持久存储承诺，重启可能清空缓存/快照。公开MVP尚未做高并发容量验证；不要将其描述为已验证的大规模生产服务。本轮没有自动选股、SectorHeat、AI API、登录、微信或回测功能。

Web离线测试使用人工夹具；真实验收使用tools/stage25_web_smoke.py操作实际浏览器，证据位于outputs/web。浏览器验收工具需要另外安装playwright和本机Edge，不属于云端运行依赖。

## Stage 2.5 UI Final Redesign

基于当前WorkBuddy首页与分析页增量优化，保留真实行情、评分规则与Provider核心。首页指数为真实BaoStock日线，仅成功且身份核验通过的指数才展示；科创50无有效数据时隐藏。小走势图来自实际收盘序列，日线不标为LIVE。评分预览和最近分析只引用当前会话已完成的真实结果，没有热门榜单或示例分数。

首页/单股分析/规则导航与Light/Dark切换可实际使用；自选股与板块功能保持未开放。图表支持暗色背景，综合结论下增加原引擎评分构成和数据说明。原始WorkBuddy文件已归档；详见docs/UI_FINAL_CURRENT_AUDIT.md与docs/UI_REDESIGN_REPORT.md。Stage 2.6、Stage 3未进入。

### UI 最终验收（2026-09-27）

Stage 2.5 UI Final Redesign：PASS。真实 600519、四项真实指数、双主题、390px 手机及浏览器截图已验证；完整测试 437 passed / 0 failed / 1 skipped。原核心评分与 Provider 文件未改。报告见 [UI_REDESIGN_REPORT](docs/UI_REDESIGN_REPORT.md)，截图见 `outputs/web/*_final.png`。本轮本地验收服务使用 http://127.0.0.1:8502/；未进行公网部署或 Stage 3。

## Online Demo

尚未获得公网 URL。Stage 2.6 当前为部署准备阶段，不将 localhost 或历史本地验收作为云端通过证据。

## Local Run

使用 Python 3.11，在仓库根目录：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app/web.py
```

常规安装不依赖 `.deps`、本机代理或自定义 PYTHONPATH。默认 BaoStock 无需 API Key，不需要 OpenAI / GPT / 腾讯 MCP，也不需要额外启动 FastAPI。

## Deployment

1. 登录 GitHub，先确认账号中是否已有本项目仓库；有则使用原仓库，无则创建 `QuantScore`。不要上传整个工作目录，请使用已审计的 Git 文件列表。
2. 将本地 `main` 分支提交并推送到该仓库（具体步骤见 [部署指南](docs/STAGE26_DEPLOYMENT.md)）。
3. 登录 [Streamlit Community Cloud](https://share.streamlit.io/)，选择 **Create app → Yup, I have an app**。
4. Repository：`wei20ovo-commits/QuantScore`；Branch：`main`；Main file path：`app/web.py`。
5. **Advanced settings → Python version：3.11**；Secrets 留空；保存后点击 **Deploy**。依赖来自根目录 `requirements.txt`，配置来自 `.streamlit/config.toml`。
6. 部署完成后用实际公网 URL 检查首页、Light/Dark、600519真实分析、K线、规则和390px手机。BaoStock在云端的出站连接尚未验证；连接失败不能宣称部署PASS。

Cloud本地缓存为空也可启动，缓存由现有服务按需创建；重启后的缓存及冻结快照不保证持久保存。默认不设置 TUSHARE_TOKEN；可选 Tushare 回退需要另装SDK并通过 Cloud Secrets配置，不应写入仓库。

官方流程：[部署说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)。

## Stage 3C — Backend Strategy Match Screening

新增后台扫描入口；真实全市场验收状态见
[Stage 3C报告](docs/STAGE3C_RESULT.md)，不要把离线测试通过视作全市场验收通过。
本轮用户冻结的候选语义见[活动规范](docs/STAGE3C_RULE_FREEZE.md)：所有可评
SectorHeat>=70的行业进入股票扫描；完整QuantScore>=80且Risk非HIGH才可匹配。
不新增全局Coverage门槛，不设Top5业务限制，不使用旧AutoScreenScore。
数据错误/过期/不一致及样本不足独立记录为NOT_EVALUABLE。

```powershell
python -m app.cli screen --industry C15 --industry C25 --industry H61 --json --output-dir outputs/stage3c/smoke
python -m app.cli screen --json --output-dir outputs/stage3c/full_market
python tools/stage3c_replay.py
python tools/stage3c_live.py --full
```

FastAPI提供`GET /api/screen`，可使用`industry_id`或`limit_industries`进行有限范围
验证。这些参数是运行范围控制，不是业务TopN。扫描同步运行，可能耗时较长；
请求串行化并使用现有Provider互斥、节流、字段分组与有限重试。
同一行业Heat只计算一次，基准与相同查询结果在本次请求中复用。

输出顺序为QuantScore降序、Heat降序、代码升序，标为
ENGINEERING_DISPLAY_ORDER；不影响候选资格，也不表示投资优先级。
策略匹配候选不是收益预测或投资建议。Web页面未接入此功能。


## Stage 3C Environment & Reproducibility

Stage 3C was revalidated in an isolated Python 3.11 `.venv` installed from the root `requirements.txt`. PyYAML is declared in both dependency manifests. Do not use an unrelated global interpreter; activate the project `.venv` before running `python -m app.cli` or `python -m pytest`. The current full-market acceptance, data-quality counts, and clean-environment test evidence are recorded in [Stage 3C result](docs/STAGE3C_RESULT.md).
