# Stage 2 Current State Audit

恢复后先只读审计，再于本记录之后修改。WorkBuddy 原交接文件保留；入场版本另存 archive/workbuddy_resume_baseline.zip。

| 检查项 | 入场结果 |
|---|---|
| Git status / diff / untracked | 实际执行，目录不是 Git 仓库；不初始化、不丢弃内容。改用归档文件差异与哈希 |
| 最近修改 / 目录 | 现有 app/data、features、services、api.py、cli.py；交接文件位于 outputs/runtime |
| requirements / pyproject | 依赖存在；pyproject 项目描述仍写 V1.3，待同步 |
| 测试 | 实际完整执行 374 项：373 PASS、0 FAIL、1 SKIP；T20 自动排名排除于 Stage 2 |
| V1.4 Word | ZIP/XML 有效且继承 V1.3；首页有 spec_version=1.3 冲突，需局部修复 |
| 历史 Word | V1.1/V1.2/V1.3 SHA256 与 pre_v1_4_spec_hashes.json 一致 |
| FastAPI / CLI | 有真实 Service 路径与 TestClient 测试；仍需本轮真实网络命令验证 |
| AKShare | 安装版本1.18.97，四个实际函数签名已重新检查 |
| Tushare | optional；无 token 不启用；有 stk_limit / daily_basic 适配 |
| SymbolResolver | 按真实证券列表，000001 股票与显式000001.SH指数分离 |
| Benchmark | 常量及配置为000001.SH / 上证指数；所有股票统一使用 |
| raw/qfq | 独立获取，按日期严格一对一合并；指标adj，涨跌停raw |
| MarketLimitResolver | 有三级来源，不写死10%；历史证据不足返回UNKNOWN；参考价应用路径需加回归 |
| 周/月 | 有已完成周期与缺日守卫；无完整交易所日历时保守排除节假日不完整周期 |
| Cache | SQLite TTL、refresh、来源元数据；不可变评分快照 |
| DataValidator / FeatureBuilder | 日期、OHLC、单位、统一派生与as_of截断已存在 |
| 新规则 | D2/F1-X/F2/R3/R5均有执行器和测试；继续对照冻结规范审计 |
| 规则登记 | 35 IMPLEMENTED，0 PARTIAL，13 NOT_IMPLEMENTED |
| 真实 smoke | resume-real-smoke.json 与正式报告均是 NETWORK_FAILED，不是通过；旧脚本未执行完整评分及5日均线抽查 |
| 文档 | README和TEST_REPORT含过时实现状态；.gitignore未保护.env，需补齐 |

交接结论采用实际运行复核：resume-delivery.xml 的373/0/1与本轮首测一致；原295项保留和配置/权重差异还将重新从归档比对。真实网络数据未成功前，不能宣称 Stage 2 PASS。

## 恢复后复核结论

- 首次现场完整测试：374项，373 PASS、0 FAIL、1 SKIP，与resume-delivery.xml一致。
- 修复后：386项，385 PASS、0 FAIL、1 SKIP；新增12项恢复审计测试。
- 原Stage 1.2的295项用例ID全部保留；没有移除原测试函数。原评分权重全部不变。
- resume-295-retention.json 与 resume-retention-and-config.json 的原用例保留/权重结论已从Stage1.2归档独立重算，不只引用交接结论。
- 入场V1.4存在版本标签冲突，原交接关于规范状态并不完整；本轮在原文件局部修复并完成46页渲染检查。
- 发现并修复F2遗漏N板/鲤鱼跃龙门事件日期、D2/F1-X/F2连续分档端点、historical as_of补造R7快照、除权参考价应用、结果来源字段、API服务复用、报告工具旧版本回写和敏感文件忽略项。
- WorkBuddy新增D2/F1-X边界断言仅因V1.3明确的全局[a,b)约定调整；原295项在本轮未改动。两侧邻近值另加断言，没有以删除、SKIP或削弱条件换取通过。
- 真实证券表解析成功；股票与指数行情仍NETWORK_FAILED。API/CLI降级可复现，但不等于真实行情分析通过。
- 原交接文件均保留。`outputs/runtime/resume_final_audit.json`列出本轮文件差异、哈希与静态敏感扫描证据。
