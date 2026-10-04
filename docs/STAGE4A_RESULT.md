# QuantScore Stage 4A Web App Productization Result

## Status

**PASS — 2026-10-04。** 五个核心页面、真实单股流程、正式后台结果读取、候选空状态、ACTIVE 规则、数据状态、Light/Dark、390px 布局及完整回归通过。本轮不 commit/push，不进入 Stage 4B；当前公网版本没有自动更新。

## Current Audit / Existing Work Preserved

执行 git fetch origin 后，HEAD = origin/main = `956c5aaa35b69a6b32bc9b2e3f7b87a504c49547`。未 reset/rebase/恢复旧版。初始未跟踪的 `docs/STAGE26_FINAL_VERIFICATION.md`、`tools/stage26_public_smoke.py` 原样保留。Stage 0–3C.1 核心成果、正式原始输出、既有测试均保留。

最终 git diff 验证：RuleEngine、ScoreEngine、rules、sector、screening、评分权重/参数和候选配置无修改。此次是 Web 结果消费与展示层扩展。

## Page Structure / Source Mapping

| 页面 | 来源 | 展示与行为 |
|---|---|---|
| 首页 Dashboard | 正式 screening_details.json 的 stats/date/end_time/provenance | 行业总数、可评分行业、合格行业、候选、不可评行业/股票、批次状态、历史日期与生成时间。保留原有首页及会话最近分析。指数通过单独按钮真实加载，避免慢请求阻塞导航。 |
| 单股分析 | 原有 app/web_backend.py → StockAnalysisService | 真实 raw/qfq、基准、原 RuleEngine/ScoreEngine；保留 K 线、均线、成交量、评分卡及解释，新增行业标签、Primary Industry、SectorHeat、B1/B2 展示；逐条保留原始值、状态、分数、原因与适用性。 |
| 板块热度 | 正式 screening_details.json 的 sectors/context/sector_heat | 全部行业、Heat、S1–S7、数据状态、成员数量、交易日；支持 Heat 展示排序、名称/代码搜索、行业原始输入与来源详情。 |
| 策略匹配候选 | 同一正式批次的 candidates/stats | 原样消费后台成员和排列，不重做门槛/风险判断、不添加 Coverage 门槛、不限制 TopN。无候选时正常显示 0。 |
| 规则中心 | 当前 config/scoring_rules.yaml + RULE_IMPLEMENTATION_MATRIX.md + STAGE3B_RULE_FREEZE.md | 48 条 ACTIVE V1.4 A/B/C/D/E/F/R/S，含作用、实现状态、最高得分/扣分及必要字段。44 IMPLEMENTED，4 NOT_IMPLEMENTED。S1–S7 的独立实现采用矩阵与当前冻结条款，避免单股登记的占位状态和历史 S4/S7 定义误导。 |

## Backend Read Contract / No Full Market Scan

`app/web_results.py` 只读文件，不导入 Provider、ScreeningService、SectorHeatEngine，不创建缓存或目录、不联网、不评分。`config/web.yaml` 使用项目内相对路径，默认读取 `outputs/runtime/daily/screening_details.json` 或 `outputs/stage3c/full_market/screening_details.json`，按数据交易日及生成时间选择最新合法结果，不按文件 mtime 选择。

读入审计包括真实 live 来源标记、SH/SZ 完整 Universe、已结束批次、日期、带时区生成时间、身份字段、统计及候选一致性。拒绝 mock、archive 性能回放、限制行业的子集、RUNNING/STOPPED/complete=false、重复身份、损坏文件和越界/Windows 绝对路径。候选是否 MATCHED 沿用后台判定；传输校验不实现另一套候选阈值。

PARTIAL 表示后台批次已结束但部分对象有数据问题，可以展示；各对象的 DATA_INCOMPLETE/DATA_ERROR 等仍保留。缺项使用空值/—，合法 0 分仍保留 0。可用分诊断不会替代完整 Heat。全站数据状态说明区分 VALID、UNKNOWN、NOT_APPLICABLE、DATA_INCOMPLETE、DATA_ERROR、DATA_STALE、DATA_INCONSISTENT；不可评不等于不匹配。

## Formal Data Verification

读取 Stage 3C 正式全市场结果，未重新启动扫描：

- trade_date：2026-09-30；generated_at：2026-10-02T17:02:30.835920+00:00；provider：baostock。
- 83 个行业：40 个可评分，43 个不可评，后台认定 2 个合格行业。
- 78 只预期股票全部完成分析；真实候选 **0**，没有制造展示股票。
- 对正式 sector_scan.csv 的 83 行逐项独立核对行业身份、成员数、Heat、数据状态，全部一致；空分未变成 0。
- 正式 JSON SHA256：`95395e29e900b98d71bdded84e7c1f1dbbff6b0fd99ae972d2457e49f27423b3`。

机器记录：`outputs/stage4a/source_verification.json`。

## Real Single-Stock / Browser Smoke

实际运行 Streamlit `app/web.py`，以真实 Edge 浏览器填写 600519 并分析；没有路由 mock、结果注入或保存结果冒充新网络请求。冷链路完成后再次验证沿用真实分析缓存。

实际页面：**贵州茅台 / 600519.SH / baostock / 2026-09-30**。未复权收盘 1258.62，涨幅 +1.86%；QuantScore **0**，正向分 **15**，风险扣分 **20**，Risk **HIGH**。该低分是引擎真实输出，不为了展示效果改分。所属行业 C15酒、饮料和精制茶制造业，完整 Heat **70**，B1 **6**，B2 **1**；行业数据状态 VALID。

K 线、M5/M30/M60、成交量共五条真实图层，各 120 个数据点。41 条单股规则明细保持原始解释。桌面 1440px、手机宽 390px、Light/Dark 切换及单股/板块/候选导航检查通过，页面级横向溢出为 false。宽表使用表格内滚动。规则/板块/候选不会因已有单股会话而误跳回分析页。

初次浏览器等待超时、诊断启动尝试和修正前的截图/记录保留；不计入最终成功。首次首页自动指数请求可能阻塞导航，因此改成显式加载。单股冷链路仍可能耗时数分钟，评分和数据算法未改。最终标准 Streamlit 启动与完整渲染检查通过，最终证据为 `outputs/stage4a/web_smoke.json`（PASS），不是首次失败报告。

## Screenshots

真实运行视口截图保存在 `outputs/stage4a/`：

- home_light.png / home_dark.png / home_mobile.png
- analysis_light.png / analysis_dark.png / analysis_mobile.png
- sector_dark.png / sector_detail_dark.png / sector_mobile.png
- candidates_dark.png / candidates_mobile.png
- rules_light.png / rules_dark.png

另有只读页面 Light/Dark/390px 的独立检查与截图，记录于 read_only_smoke.json。最终截图等待 `.stApp` notRunning、无 stale 元素以及画布完成绘制；早期截图出现的切页残影不作为最终验收。深色控件文本可读，原生表格保留 Streamlit 自身表头/画布风格。

## Tests

完整实跑 **840 项：839 PASS / 0 FAIL / 0 ERROR / 1 SKIP**，143.38s。原 788 项全部保留，新增 52 项 Web 产品测试，覆盖读入统计、最新批次选择、缺文件/只读/坏文件、mock/子集/未完成结果拒绝、路径保护、候选空/有结果、错误空分、搜索排序、ACTIVE 规则、会话导航、暗色表格和 Web 不调用扫描/自动单股分析。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=outputs/tmp/pytest/stage4a-final-3 --junitxml=outputs/stage4a/pytest_final.xml --tb=short
```

Windows 临时目录权限错误通过项目内独立 basetemp 与允许运行环境解决，未修改业务逻辑或删测试。唯一 SKIP 为历史 T20 / SUPERSEDED_BY_STAGE3C；既有 FastAPI/Starlette 弃用警告不影响结果。JUnit 与实际输出：outputs/stage4a/pytest_final.xml、pytest_final.txt。

## Cloud Compatibility / Remaining Limits

运行依赖无新增，入口仍 app/web.py，Python 3.11，不需要新 Secrets。结果读取完全使用项目内相对路径，可在只读目录下工作。公网没有预计算文件时展示“暂无最新筛选结果”，不崩溃、不现场扫描。单股网络或写缓存权限失败保留清晰错误，不展示假评分。

outputs 继续被忽略；当前公网不会因本地完成而自动获得这些文件。本轮没有发布、调度器或远程同步；后续后台需要提供真实完整发布文件，并原子替换它。结果不是实时行情，全部标记历史数据/非实时与真实交易日。单股请求仍依赖实际数据源和既有缓存，冷请求可较慢。

## Files Added / Updated

新增：app/web_results.py、app/web_pages.py、config/web.yaml、tests/test_web_product.py、tools/stage4a_web_smoke.py、docs/STAGE4A_RESULT.md。

更新：app/web.py、app/web_visuals.py、app/web_style.css、README.md、docs/TEST_REPORT.md。

本轮只做 Stage 4A，完成后停止，不 commit/push，不进入 Stage 4B。
