# Stage 4A 最终回归（2026-10-04）

840 项：**839 PASS / 0 FAIL / 0 ERROR / 1 SKIP**，143.38s。原 788 项全部保留，新增 52 项 Web 产品测试，覆盖 Dashboard、只读正式结果、最新批次、数据错误/缺文件、候选空与有结果、ACTIVE 规则、原有单股功能、主题/导航、暗色表格以及 Web 不启动 Full Market Scan。

实际命令：`.venv/Scripts/python.exe -m pytest -q --basetemp=outputs/tmp/pytest/stage4a-final-3 --junitxml=outputs/stage4a/pytest_final.xml --tb=short`。Windows 默认临时目录权限错误通过项目内独立 basetemp 和允许的运行环境解决，未改业务规则或删测试。唯一 SKIP 仍为历史 T20 / SUPERSEDED_BY_STAGE3C，1 条既有 FastAPI/Starlette 弃用警告。实际 JUnit/输出见 outputs/stage4a/pytest_final.xml 与 pytest_final.txt。

另行实际浏览器验收通过：真实 600519/贵州茅台/BaoStock 分析、行业/B1/B2、图表、五页面、Light/Dark、390px。正式全市场预计算结果 83 个行业、78 只股票、0 候选；未再次扫描。浏览器 JSON 和截图位于 outputs/stage4a/，详情见 [Stage 4A 报告](STAGE4A_RESULT.md)。离线候选有结果用例为明确标注的测试 fixture，不是实际股票候选证据。以下历史测试报告原样保留。

# Stage 3C.1 最终回归（2026-10-03）

788 项：**787 PASS / 0 FAIL / 0 ERROR / 1 SKIP**。原 759 项全部保留，新增 29 项缓存、增量、复权保护、并发缓存一致性、checkpoint/resume、版本与日期拒绝、篡改拒绝、期限/失败隔离、真实进程终止及评分等价测试。

实际命令：`.venv/Scripts/python.exe -m pytest --junitxml=outputs/stage3c1/pytest_final.xml`；用时 116.82s。日志 `outputs/stage3c1/pytest_final.txt`。唯一 SKIP 仍为旧 T20 HISTORICAL/SUPERSEDED_BY_STAGE3C。一个既有 FastAPI/Starlette TestClient 弃用警告，无测试 ERROR。早期新增测试失败已修正，未删除原测试或将失败改为 SKIP。

固定真实数据回放、独立 BaoStock 真网冷/热/增量验证及结果等价证据单列在 [Stage 3C.1 报告](STAGE3C1_RESULT.md)。离线测试不冒充实时网络证明。以下保留历史阶段报告。

# Stage 3C Environment Closure (2026-10-03)

Clean `.venv` installed from `requirements.txt` with Python 3.11.0. PyYAML 6.0.3 imports from the isolated environment; `ScreeningPolicy.current()` and `app.cli screen --help` pass with no project `.deps` PYTHONPATH. Full suite: 759 total, 758 PASS / 0 FAIL / 0 ERROR / 1 historical SKIP. JUnit/text: `outputs/stage3c/pytest_clean_venv.xml` and `.txt`. Full-market evidence is separately audited in `docs/STAGE3C_RESULT.md`; no second scan was run.

# Stage 3C 最新回归

759项：758 PASS / 0 FAIL / 0 ERROR / 1 SKIP。
新增32项筛选测试，全部原测试保留。历史T20的旧AutoCoverage门槛已被Stage3C用户冻结语义替代，保留历史SKIP。
完整命令：python -m pytest -q --basetemp=outputs/tmp/pytest/stage3c_nullable_final --junitxml=outputs/stage3c/pytest.xml。
Windows临时目录权限失败已保留在outputs/stage3c/pytest_initial_permission_error.txt；未修改业务逻辑规避错误。
真实全市场验收独立记录于STAGE3C_RESULT.md，离线测试不代替Live。

# Stage 3B.1 Live Recovery 最新回归

727项：726 PASS / 0 FAIL / 0 ERROR / 1 SKIP。原有测试全部保留；本轮新增4项根因/传输保护测试。真实验收状态PASS，详见STAGE3B1_LIVE_RECOVERY.md。证据outputs/stage3b1_recovery/pytest.xml与pytest.txt。

# Stage 3B.1 最新完整回归

723项：722 PASS / 0 FAIL / 0 ERROR / 1 SKIP，新增58项；原665项全部保留。原始证据outputs/stage3b1/pytest.xml、pytest.txt。SKIP仍为本阶段范围外的自动选股排名；存在1条第三方弃用警告。真实网络验收另见STAGE3B1_RESULT.md，不以单元测试代替。

以下保留历史报告。

# Stage 3B 最新完整回归

665项：664 PASS / 0 FAIL / 0 ERROR / 1 SKIP，新增139项；原526项全部保留。原始结果outputs/stage3b/pytest.xml、pytest.txt。Windows使用项目内TMP/TEMP/TMPDIR。1条第三方弃用警告；SKIP仍为范围之外的自动选股排名。

以下保留历史报告。

# Stage 3A.5 最新完整测试（2026-09-29）

526项：525 PASS / 0 FAIL / 0 ERROR / 1 SKIP。新增58项，原471项全部保留。原始结果：outputs/stage35/pytest.xml、pytest_final.txt。命令：python -m pytest --basetemp=outputs/tmp/pytest/stage35-final --junitxml=outputs/stage35/pytest.xml。

下方为历史报告，保留供复现。

# 实际测试报告

- 总数：433
- PASS：432
- FAIL/ERROR：0
- SKIP：1
- 实际命令：`python -m pytest --junitxml=outputs/pytest-results.xml`
- 环境：Python 3.11.0；依赖版本见requirements.txt；人工构造OHLCV；核心测试不联网。
- Stage 1原182项场景全部保留；端点/状态等预期按用户V1.2明文迁移，原件归档。
- Stage 1.1的241项测试保留；本轮预期变更仅来自用户V1.3确认；基线归档。
- 原始结果：outputs/pytest-results.xml；跳过不等于通过。

## Active Acceptance Tests（旧第11章仅作HISTORICAL / SUPERSEDED对照）

| ID | 状态 | 证据/原因 |
|---|---|---|
| T01 | PASS | test_T01_short_M60_history |
| T02_NEW | PASS | 原平台跌破立即INVALIDATED；收复交C4；新平台重新累计5日。共6项生命周期断言。 |
| T03 | PASS | test_T03_n_intraday_break |
| T04 | PASS | test_T04_n_second_start |
| T05 | PASS | test_pending_spec_acceptance[T05-F1-T\u90e8\u5206T\u5f62\u51e0\u4f55\u672a\u5b9a\uff0c\u672a\u5b9e\u73b0] |
| T06 | PASS | test_T06_double_top_invalidated |
| T07 | PASS | test_T07_double_top_confirmed |
| T08 | PASS | test_pending_spec_acceptance[T08-C6/R8\u591a\u5468\u671f\u5b89\u5168\u5e26\u68c0\u6d4b\u672a\u5b9e\u73b0] |
| T09 | PASS | test_pending_spec_acceptance[T09-C6/R8\u591a\u5468\u671f\u5b89\u5168\u5e26\u68c0\u6d4b\u672a\u5b9e\u73b0] |
| T10 | PASS | test_pending_spec_acceptance[T10-E2\u4e0a\u4e00\u8f6e\u9ad8\u70b9\u9009\u62e9\u672a\u5b9a\uff0c\u672a\u5b9e\u73b0] |
| T11 | PASS | test_pending_spec_acceptance[T11-E3\u65e5\u5468\u4e24\u5957\u7ed3\u6784\u5408\u5e76\u672a\u5b9a\uff0c\u672a\u5b9e\u73b0] |
| T12 | PASS | test_pending_spec_acceptance[T12-B3\u677f\u5757\u5168\u91cf\u6210\u5206\u80a1\u63a5\u53e3\u672a\u5b9e\u73b0] |
| T13 | PASS | test_pending_spec_acceptance[T13-E1\u4f9d\u8d56\u5e73\u53f0/\u5e95\u90e8\u9636\u6bb5\uff0c\u672a\u5b9e\u73b0] |
| T14 | PASS | test_pending_spec_acceptance[T14-F3\u9ad8\u4f4d\u4e2d\u7ee7\u672a\u5b9e\u73b0] |
| T15 | PASS | test_pending_spec_acceptance[T15-F3\u9ad8\u4f4d\u4e2d\u7ee7\u672a\u5b9e\u73b0] |
| T16 | PASS | test_pending_spec_acceptance[T16-F1-Y\u9f99\u95e8\u5f3a\u52bf\u7a81\u7834\u5b9a\u4e49\u6709\u6b67\u4e49\uff0c\u672a\u5b9e\u73b0] |
| T17 | PASS | 冻结QuantScore>=80且非HIGH；后3日High达到+3%失效，否则最大收盘<=0扣10，其余扣6；V1.3边界测试一并保留。 |
| T18 | PASS | test_T18_no_chip_data |
| T19 | PASS | test_T19_no_minute_data |
| T20 | SKIP | T20: 自动选股排名属于明确排除的Stage 2；不伪造通过。 |

## V1.3 新增测试

新增54项，覆盖四项最终语义、C5生命周期、版本、旧规范哈希和评分权重保持。

## 失败项

无。

## Stage 2 恢复验收

原295项用例ID全部保留；新增数据层/API/CLI/五条规则/恢复审计回归测试。
WorkBuddy边界断言仅按V1.3已冻结左闭右开分档修正，没有删除或减弱断言；见STAGE2_CURRENT_STATE_AUDIT.md。
真实网络验收独立于离线pytest；见STAGE2_DATA_SMOKE_REPORT.md，网络失败不计真实通过。
历史Word完整性与原测试保留证据：outputs/runtime/resume_final_audit.json。

## Stage 2.1

版本三元组统一为spec_version=1.4、assumption_version=v1.3、data_contract_version=1.4。
原T02节点仅保留为历史回归入口，实际执行冻结新语义；活动验收使用T02_NEW。
代理诊断与真实结果见STAGE2_NETWORK_DIAGNOSIS.md、STAGE2_DATA_SMOKE_REPORT.md；不以离线测试冒充真实行情。

## 完整性

V1.4 Word SHA256为 `29946bc44f8762597a9b34ad40c18b10a90e7e43867dc9338ed537af6c6ef5f4`。
测试仅证明已实现行为及明确的未知守卫；不证明未实现复杂规则已通过业务验收，不代表回测收益或真实行情验证。

## Stage 2.5 Web MVP

433项：432 PASS / 0 FAIL / 1 SKIP，原417项全部保留，新增16项Web测试。原评分规则与参数逐字段相同。真实600519浏览器验收另行执行并通过，桌面和390px手机布局正常，见STAGE25_WEB_REPORT.md；公开Cloud部署尚未执行。

## UI Final Redesign — current WorkBuddy baseline

实际完整运行python -m pytest：438项，437 PASS / 0 FAIL / 1 SKIP。原435个测试节点全部保留；新增3项导航/主题/会话记录、图表暗色不改变值、真实序列小走势图测试。原Web测试仅改为稳定按钮key定位，并隔离首页网络访问，保留全部断言场景。

TMP/TEMP/TMPDIR设为项目outputs/tmp/pytest，基准临时目录为outputs/tmp/pytest/ui_final_finish。唯一SKIP仍为阶段外自动选股排名。37个受保护核心/Provider/配置文件哈希未变。证据：outputs/runtime/ui_final_integrity.json；原始JUnit：outputs/pytest-results.xml。

## Stage 2.6 部署准备

从仅含Git发布文件的干净副本，使用独立Python 3.11虚拟环境安装requirements后实际执行完整pytest：438项，437 PASS / 0 FAIL / 1 SKIP，68.70秒。原438项全部保留，未删除或跳过部署失败测试。唯一SKIP仍为阶段外自动排名。证据：outputs/deployment/stage26-pytest.xml。此结果不是Linux或公网验收；公网URL与Cloud真实BaoStock验证待用户授权部署。
