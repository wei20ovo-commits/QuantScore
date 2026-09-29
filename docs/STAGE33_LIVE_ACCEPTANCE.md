# Stage 3A.3 Live Data Acceptance & S4 Closure

## 验收结论

**Stage 3A = PARTIAL；不进入 Stage 3B。**

本轮已重新调用 BaoStock，完成真实行业快照、三种规模行业抽样、选定成分股日线获取，并输出 S1–S7 输入证据。S4 仍未闭合：BaoStock 本轮历史接口没有提供可审计的历史涨跌停价、上市日期和风险警示元数据，不能使用涨幅阈值或 `preclose * 1.10` 代替真实涨停判定。

## 真实 Provider 证据

运行时间：`2026-09-27T05:52:37.943742+00:00 UTC`

| 指标 | 结果 |
|---|---:|
| Provider | BaoStock |
| `query_stock_industry` 总行数 | 5,555 |
| 非空行业归属行数 | 5,221 |
| 缺失行业归属行数 | 334 |
| 行业组数 | 83 |
| 唯一股票数 | 5,221 |
| SH / SZ / BJ | 2,320 / 2,901 / 0 |
| 无效代码数 | 0 |
| 行业-股票重复数 | 0 |
| `updateDate` | 2026-09-21 |

本轮快照中没有出现 BJ 股票，不能据此宣称已经完成当前北交所 `920xxx` 真实验证。

## 行业与行情覆盖

选取行业：

- 小行业：`H61住宿业`，5 只
- 中行业：`C25石油、煤炭及其他燃料加工业`，17 只
- 大行业：`C18纺织服装、服饰业`，41 只
- 合计预期成分股：63 只

请求区间：2026-05-30 至 2026-09-27；所有成功股票至少取得 83 条日线，最新共同观测日为 2026-09-24。63 只中 60 只达到至少 35 条 bars，3 只未达到完整验收标准，详见 `bar_quality.csv`。

大行业仍有 3 只预期成员缺失，因此其 S1/S2/S3/S5/S7 状态为 `DATA_INCONSISTENT`，没有用实际返回成员数缩小分母。

## S1–S7 输入状态

- 小行业：S1/S2/S3/S5/S6/S7 均为 `VALID`。
- 中行业：S1/S2/S3/S5/S6/S7 均为 `VALID`。
- 大行业：S1/S2/S3/S5/S7 为 `DATA_INCONSISTENT`；S6 按实际日期交集计算，但完整成员覆盖仍需补齐后才可作为正式 SectorHeat 输入。
- S7 已显式使用预期成分股分母：大行业报告 `valid 38/41 expected constituents`，没有把 38 当成 41。

所有机器可读输入均在 `outputs/stage33/`：

- `industry_snapshot.csv`
- `selected_industries.csv`
- `bar_quality.csv`
- `s1_inputs.csv` 至 `s7_inputs.csv`
- `s4_limit_validation.csv`
- `run_metadata.json`

## S4 当前状态与制度边界

本轮对选定的 63 只股票全部生成了显式 `DATA_ERROR` 记录，原因是 BaoStock 历史行情字段不足以审计涨停价、跌停价、上市日期和 ST 状态。未使用：

- `preclose * 1.10`
- `return >= 9.8%`
- “接近涨停”推断
- 宽泛 `4/8/92` 裸码推断北交所

深交所公开投教材料明确列出：深市主板新股上市首日、创业板新股上市前五个交易日等情形不设涨跌幅限制（深交所，2022-08-23）。因此限价引擎必须将上市阶段、板块、风险警示、特殊交易日和参考价格作为完整元数据处理，不能仅按交易所和一个固定比例计算。当前 `MarketLimitResolver` 保留“Provider 报告值优先、缺元数据即不可靠”的安全边界；北交所无报告值仍为 `UNSUPPORTED`。

北交所当前 `920xxx` 真实样本、独立限价 Provider 交叉验证、官方规则逐市场机器验证，均未完成，故 S4 不得标记 PASS。

## 代码边界修正

本轮同步完成：

1. `s7_strong_ratio()` 增加 `expected_constituents`，按预期成分股计算分母。
2. `fetch_aligned()` 不再使用自然日差值直接判定 stale；支持显式 `trading_days`，未提供交易日历时不虚构 stale 结论。
3. 生产 `canonical_symbol()` 不再把裸 `4/8/92` 代码直接推断为 BJ；BJ 需显式市场信息。
4. 新增 `tools/stage33_live_acceptance.py`，真实失败和覆盖缺口均保留为机器可读状态。

## 最终判定

真实行业与大部分历史 bars 闭环已取得进展，但以下核心缺口仍存在：

1. 3/63 选定股票未达到至少 35 bars 验收；
2. 大行业 3/41 成员行情缺失；
3. BaoStock 本轮未返回 BJ，未完成 `920xxx`；
4. S4 无可审计限价字段；
5. 没有独立 Provider 完成 S4 交叉验证；
6. 缓存首次 fetch / cache hit / stale refresh 尚未纳入本轮真实证据。

因此当前阶段必须保持：

```text
Stage 3A = PARTIAL
Stage 3B = NOT STARTED
```
