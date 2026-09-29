# QuantScore Stage 3A.4 Final Closure Result

## Code / Report Consistency

已修复生产 `canonical_symbol()`：裸 `4/8/92` 代码不再自动推断为 BJ；必须有显式 exchange。新增回归断言：`830001`、`870001`、`920001` 裸码均拒绝，`830001.BJ` 显式市场仍可解析。

## BaoStock Metadata Audit

本轮实测 BaoStock：

- `query_stock_basic(code=...)` 返回 `code, code_name, ipoDate, outDate, type, status`
- `query_trade_dates()` 返回 `calendar_date, is_trading_day`
- RAW 日线请求使用 `adjustflag=3`，返回并转换 `preclose, turn, tradestatus, pctChg, isST`
- 最新样本 `2026-09-24` 的 `preclose/isST/tradestatus` 已进入真实证据链

相关证据：`outputs/stage34/security_metadata.csv`、`bar_retry_log.csv`、`bar_quality.csv`。

## Trading Calendar

使用 BaoStock `query_trade_dates()` 建立真实交易日历，最新交易日为 `2026-09-24`。正式验收脚本不使用 `pd.bdate_range` 代替 A 股交易日历。

## Failed Bar Recovery

本轮对 63 只选定股票执行独立 BaoStock 请求，每只最多 3 次尝试并记录：股票、attempt、provider、error_code、error_msg、timestamp。最终：

- bar_expected：63
- bar_valid：63
- bar_provider_error：0
- 本轮未触发 secondary provider 降级

## Market Limit Official SSOT

已建立 `docs/MARKET_LIMIT_RULES_SSOT.md`，记录 SH MAIN、SH STAR、SZ MAIN、SZ GEM、BJ BSE 及 2026-07-06 后主板风险警示规则的当前参数、有效期、无涨跌幅情形、最小价位、舍入方式和官方来源类别。

## Current 2026 Rule Table

当前引擎配置：

- SH MAIN：10%
- SH MAIN_ST：10%
- SH STAR：20%
- SZ MAIN：10%
- SZ MAIN_ST：10%
- SZ GEM：20%
- BJ BSE：30%

## LimitPriceEngine

新增 `CurrentMarketLimitEngine`：

- 根据 exchange、symbol、isST 识别 MAIN / MAIN_ST / GEM / STAR / BSE
- 使用 Decimal 计算和 `ROUND_HALF_UP` 舍入
- 输出 `limit_up_price`、`limit_down_price`、`limit_ratio`、`rule_id`、`rule_source`
- 同时输出 `touched_limit_up` 与 `closed_at_limit_up`
- 保留 `MarketLimitResolver` 兼容入口

本轮 63/63 个沪深样本得到 `VALID` S4 计算结果。

## IPO No-Limit Logic

通过 `ipoDate` 与 BaoStock 真实交易日历计算上市后交易日序号。上市后前 5 个交易日返回：

```text
status = NOT_APPLICABLE
reason_code = NO_DAILY_PRICE_LIMIT
```

## ST Logic

S4 使用真实历史日线 `isST` 字段，而不是股票名称字符串。风险警示字段保留在输出中，即使当前 2026 主板风险警示比例与普通主板配置一致。

## S4 Cross Validation

输出：`outputs/stage34/s4_cross_validation.csv`。

- 样本数：63
- 主 BaoStock + CurrentMarketLimitEngine 结果：63/63 VALID
- 独立结果源：AKShare optional，当前未取得有效独立结果
- match_count：0
- mismatch_count：0

因此这里的 `0 mismatch` 不能解释为“交叉验证通过”，只能解释为独立源未返回结果，S4 独立交叉验证仍未闭合。

## BJ Universe Decision

本轮真实行业快照没有 BJ 股票，未伪造 `920xxx` 样本。当前冻结：

```text
QuantScore Stage 3 V1 Universe = SH + SZ
BJ = OUT_OF_SCOPE_FOR_V1
```

后续若要支持北交所，应建立独立 BJ Provider 和真实 920xxx 验收，不阻塞沪深 V1 行业链路。

## S1-S7 Re-run

Stage 3A.4 重新获取了真实行情、交易日历和元数据。大行业的成员覆盖问题与前轮一致时，继续保留数据质量状态，不缩小预期分母、不把缺失填成零收益。原 Stage 3A.3 的 S1-S7 文件未被当作本轮新证据。

## Cache Verification

输出：`outputs/stage34/cache_verification.csv`。

已验证：

1. 首次写入来自 Provider fetch；
2. 完全相同请求第二次读取为 cache hit；
3. `force_refresh=True` 不返回缓存，触发重新 Provider fetch 路径；
4. 缓存读取不改变数据值。

## Data Quality Statistics

`outputs/stage34/run_metadata.json`：

- latest_trade_date：2026-09-24
- industry_expected_count：63
- bar_expected：63
- bar_valid：63
- bar_provider_error：0
- S4 valid：63
- S4 sample_count：63
- S4 independent match：0
- S4 independent mismatch：0

## Tests

完整回归：

```text
470 passed, 1 skipped, 1 warning
0 failed
```

## Remaining Issues

1. AKShare/Eastmoney 独立涨停池本轮未返回有效结果，S4 交叉验证不能宣称 PASS。
2. 本轮报告尚未将三个行业的全部 S1–S7 明细重新复制到 stage34 专属 CSV，机器证据仍需从 Stage 3.3 输入与本轮 bars 重新聚合。
3. BJ 920xxx 不在当前 SH/SZ V1 Universe，未执行真实北交所样本验证。
4. 官方规则 SSOT 已建立，但后续若交易所发布新规则仍需更新。

## Stage 3A Final Status

```text
Stage 3A Industry V1 (SH/SZ) = PARTIAL
BJ = OUT_OF_SCOPE_FOR_V1
Stage 3B = NOT STARTED
```

虽然本轮已完成 63/63 bars、BaoStock 元数据、真实交易日历、当前限价引擎和缓存生命周期验收，但独立 S4 结果源缺失，且 S1-S7 专属重跑证据仍需进一步补齐，因此不将 Stage 3A 虚假标记为 PASS。
