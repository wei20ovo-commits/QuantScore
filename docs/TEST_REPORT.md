# Stage 3B 最新完整回归

665项：664 PASS / 0 FAIL / 0 ERROR / 1 SKIP，新增139项；原526项全部保留。原始结果outputs/stage3b/pytest.xml、pytest.txt。Windows使用项目内TMP/TEMP/TMPDIR。1条第三方弃用警告；SKIP仍为范围之外的自动选股排名。

以下保留历史报告。

# Stage 3A.5 最新完整测试（2026-09-29）

526项：525 PASS / 0 FAIL / 0 ERROR / 1 SKIP。新增55项，原471项全部保留。原始结果：outputs/stage35/pytest.xml、pytest_final.txt。命令：python -m pytest --basetemp=outputs/tmp/pytest/stage35-final --junitxml=outputs/stage35/pytest.xml。

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
