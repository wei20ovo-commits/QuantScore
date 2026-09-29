# Stage 3A.2 数据闭合报告

## 结论与证据边界

本轮仅处理行业映射、行情日期对齐、字段质量、聚合及缓存边界；不进入 SectorHeat 评分、自动选股、排名、UI 或 ScoreEngine 接入。

**当前结论：PARTIAL，报告待最终集成回归与真实数据验收补齐。** 离线注入测试证明代码边界，不证明外部行情服务可用；Stage 3A.1 的 83 个行业、28 只成分股属于历史记录，不能作为本轮真实验收结果。

## 基线问题

审阅初始实现发现：

- `quality_stats` 只使用 `notna`，空白、非有限数等可能被错误算作有效。
- `aggregate_industry` 仅用一日收益计算总质量，五日收益与成交额缺失不影响该状态。
- 成分代码规范化没有完整识别 canonical 后缀形式。
- 行业契约具有日期敏感键，但该键本身不是完整的行业缓存/降级策略。
- 原有行业映射是当前归属快照，不能自动推断历史成员归属。

这些问题由本轮对应实现与回归逐项约束；最终实现细节以源码和运行结果为准。

## 新增闭合回归

`tests/test_stage32_data_closure.py` 当前包含 16 个离线测试案例：

| 范围 | 验收内容 |
| --- | --- |
| provider 失败 | 行业列表/成分查询超时保留 `ProviderError` 与底层原因，不转空数据或业务 UNKNOWN |
| provider 字段 | 返回列缺失明确失败；真实空成分响应不补造股票 |
| 缓存键 | 区分数据类型、行业与业务日期 |
| SQLite 行情缓存 | TTL 到期边界、强制刷新、来源/日期/复权隔离、读取对象修改不污染缓存 |
| 行情失败 | 注入行情源异常返回 `DATA_ERROR` |
| 陈旧行情 | 请求终点显著晚于观测值时返回 `DATA_STALE`，保留实际 `as_of` |
| S6 日期 | 完全不重叠的交易日期不得产生有效胜出天数 |
| 聚合覆盖 | 请求成员完全缺失时不能标为 `VALID` |
| 缺失价格 | 当前收盘价缺失不得填充成零收益 |
| 成交额历史 | 不足 20 个历史日不得声称已有 20 日均值或倍率 |
| 完整聚合 | 输入顺序不影响结果，零值不丢失，保留来源和观测日期；必需列缺失不补造数值 |

测试只调用已经存在的 API，不依赖尚未实现的接口，也不访问真实网络。

## 测试执行记录

执行环境为项目 `.venv-deploy`。默认 Windows 临时目录发生权限错误，因此使用项目内独立 `--basetemp`，不修改业务代码解决环境问题。

```bash
.venv-deploy/Scripts/python.exe -m pytest tests/test_stage32_data_closure.py -q --basetemp=.pytest-temp/stage32-report-writer-01
```

首次可运行结果：**12 passed，2 failed**。

暴露的问题为：缺失期望成分仍标记 `VALID`；不足 20 日仍给出 20 日均值。行情数据层已修复上述两处，并加入两个聚合测试。

随后运行新增测试与原有行业契约回归：

```bash
.venv-deploy/Scripts/python.exe -m pytest tests/test_stage32_data_closure.py tests/test_stage31_sector_integrity.py tests/test_sector_contract.py -q --basetemp=.pytest-temp/stage32-report-writer-02
```

结果：**28 passed，0 failed**（新增 16 例，原有 12 例）。

完整回归与最终集成结果：待更新。

## 最终集成测试

项目内可写 `--basetemp` 下完整回归：

```text
469 passed, 1 skipped, 1 warning
0 failed
```

目标专项测试 `tests/test_stage32_data_closure.py` 的业务断言均通过；此前两项错误来自 Windows 默认 pytest 临时目录权限，使用项目内基准目录后不再出现。

## 真实数据证据边界

本轮未重新完成全市场行业快照及三行业 >=30 只历史 bars 的完整网络 smoke。已有真实证据为 Stage 3A.1：BaoStock `query_stock_industry` 返回 83 个行业组，前三组 28 条唯一成分，AKShare 仍为 ProxyError。该证据不能升级为本轮完整数据闭环 PASS。

因此 S1/S2/S3/S5/S6/S7 的离线数据计算边界已测试，但真实行业历史行情、共同交易日、完整成交额覆盖仍未闭合；S4 多市场真实限价交叉验证也未完成。

## 最终状态

**PARTIAL**：代码质量边界和完整回归通过，真实数据闭环尚未满足 Stage 3A PASS 标准，未进入 Stage 3B。


本测试文件使用明确的注入数据，不替代真实数据验证。最终报告需由实际运行日志补充行业数量、唯一成分数量、来源与观测日期、覆盖率、失败/陈旧/不一致数量。

可靠涨停价必须由可追溯的真实限价字段验证。涨幅阈值或近似涨停推断不构成可靠 S4 数据。是否闭合及验证样本以限价审计输出为准。

## 仍需明确的边界

1. 当前行业快照不是历史 point-in-time 成员数据，不能消除历史回测归属偏差。
2. 行情缓存 TTL 和键隔离通过并不代表已经实现行业 provider 故障后的完整缓存降级。
3. 日期陈旧阈值需要与交易日历语义区分；日历天差不能自动证明停牌或交易日缺失。
4. 离线可计算 S1–S7 部分输入不等于所有真实数据输入都已闭合。
5. 未运行、失败、缺失来源证据的项目一律保留明确缺口，不宣称 PASS。

## 本报告与测试交付

- `tests/test_stage32_data_closure.py`
- `docs/STAGE32_DATA_CLOSURE_REPORT.md`

本文为本轮协作的验收草稿，最终状态由集成测试与真实数据证据共同决定。
