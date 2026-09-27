# QuantScore V1.4 数据契约

## 版本边界

- 当前评分真源：V1.4。
- V1.1、V1.2、V1.3 Word 原件保留不覆盖；旧 T02、`scoring_spec_version=v1.1` 等继承文字在 V1.4 仅作 `HISTORICAL / SUPERSEDED` 历史对照。
- V1.4 不新增评分规则、不修改权重，仅补全数据契约与固定基准。
- 版本分层：API/文档规范版本、评分注册表、RuleResult、ScoreResult 与冻结快照均使用 `spec_version=1.4`；评分语义继承字段使用 `assumption_version=v1.3`，表示继承 V1.3 规则语义。配置同时声明 `data_contract_version=1.4`。

## 全局契约

```yaml
spec_version: '1.4'
benchmark_index: 000001.SH
benchmark_name: 上证指数
```

所有股票分析均使用 `000001.SH` 作为 benchmark，不按股票所属市场切换。`000001.SZ` 是平安银行股票，不能与指数混淆。

## 标准行情字段

股票日线至少包含：

`date, open_raw, high_raw, low_raw, close_raw, open_adj, high_adj, low_adj, close_adj, volume, amount, turnover_rate, limit_up_price, limit_down_price, symbol, name, exchange`。

- 趋势、均线、收益和形态使用 `*_adj`。
- 涨跌停、T 板、一字板使用 `*_raw` 与可靠的历史涨跌停价。
- `turnover_rate` 使用百分点（5 表示 5%），不除以 100。
- raw/qfq 必须按日期一对一严格对齐，禁止按位置拼接或静默填充。
- 指数允许 `raw == adj`，metadata 必须声明 `asset_type=INDEX`、`adjustment_type=NONE`。

## 质量与时间

日期升序且唯一；OHLC 合法；数量非负；禁止非法 NaN/Inf；评价日必须存在；基准必须覆盖评价日。所有数据先执行 `date <= as_of`，再计算指标、峰谷、平台和形态。R7 新信号在未来三日未完成时为 `UNKNOWN / AWAITING_FORWARD_CONFIRMATION`。

## 周月周期

从已取得日线自行聚合。周/月的 open 为首个交易日，high/low 为极值，close 为最后交易日，volume/amount 求和。只有已完成周期进入确认规则，输出 `is_complete_period`；当前未收盘周期不得伪装完成。

## 涨跌停

优先使用 provider 报告值（`PROVIDER_REPORTED`）；否则仅在证券元数据和历史市场规则充分可靠时计算（`MARKET_RULE_CALCULATED`）；无法确认则为 null，`limit_source=UNKNOWN`、`reason_code=LIMIT_PRICE_UNRELIABLE`，相关规则 UNKNOWN，绝不统一伪造 10%。

## 结果契约

AnalysisResult 至少包含 canonical symbol、评价日、benchmark、provider、行数、字段状态、warnings、QuantScore、Coverage、规则明细及数据 provenance。真实网络失败状态只能为 `NETWORK_FAILED`；离线 Mock 结果必须明确 `is_mock=true`。


## Stage 2.1 活动验收一致性

所有新RuleResult、ScoreResult、AnalysisResult、DataStatus及新冻结快照统一包含spec_version=1.4、assumption_version=v1.3、data_contract_version=1.4。历史兼容快照不重写。

Active Acceptance Test使用T02_NEW：旧C5跌破立即INVALIDATED，收复只由C4评价，新C5重新连续累计至少5日。旧T02仅作HISTORICAL / SUPERSEDED。

R7活动验收以冻结QuantScore>=80且非HIGH为前提，完整3日后按盘中+3%失效、最大收盘<=0扣10、其余未达+3%扣6判断；旧70分/2%逻辑只保留历史对照。
