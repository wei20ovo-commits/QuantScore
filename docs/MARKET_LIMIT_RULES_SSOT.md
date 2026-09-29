# QuantScore 当前市场涨跌幅规则 SSOT

## Stage 3A.5 官方制度核验

本版核验 2026-09-24 有效制度，并用于本轮 2026-09-28 收盘快照。制度来源仅为交易所，行情网站不是制度 SSOT。原 Stage 3A.4 文件已保存在 outputs/stage35/pre_stage35_workspace.zip。

- [上交所《交易规则（2026年修订）》及实施通知](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)：2026-04-24 发布，2026-07-06 实施。原始附件见 outputs/stage35/sources/sse_rules.docx。
- [深交所《交易规则（2026年修订）》及实施通知](https://www.szse.cn/lawrules/rule/trade/t20260424_620190.html)：2026-04-24 发布，2026-07-06 实施。原始附件见 outputs/stage35/sources/szse_rules.pdf。

| rule_id（保留现有ID） | exchange | board | effective_from | limit_ratio | 官方条款 |
|---|---|---|---|---|---|
| SSE_MAIN_NORMAL_20260706 | SH | MAIN | 2026-07-06 | 10% | 上交所3.3.13 |
| SSE_MAIN_RISK_20260706 | SH | MAIN_ST | 2026-07-06 | 10% | 上交所3.3.13、4.4；不再沿用旧5% |
| SSE_STAR_CURRENT | SH | STAR | 2026-07-06 | 20% | 上交所6.6 |
| SZ_MAIN_CURRENT | SZ | MAIN | 2026-07-06 | 10% | 深交所3.3.13 |
| SZ_MAIN_RISK_20260706 | SZ | MAIN_ST | 2026-07-06 | 10% | 深交所3.3.13、4.5；不再沿用旧5% |
| SZ_GEM_CURRENT | SZ | GEM（300/301） | 2026-07-06 | 20% | 深交所3.3.13 |

各结果保存 rule_id、实际官方 URL rule_source、effective_from。上述 effective_from 表示本次所核验制度版本生效日，不是各比例历史上首次采用日期。当前引擎不把该版制度应用于 2026-07-06 以前的历史交易日；历史解析接口保留原有保守行为。

## IPO 与价格计算

沪深首次公开发行上市后的前五个交易日不实行价格涨跌幅限制（上交所3.3.13、科创板6.6；深交所3.3.15）。计数包含上市当天，只计真实交易日历中 is_trading_day=1 的日期：1 <= trading_days_since_ipo <= 5 返回 NO_DAILY_PRICE_LIMIT / NOT_APPLICABLE，第6日才使用正常比例。缺少、零或负计数不能被视为已验证正常上市期。

涨跌幅限制价 = 当日参考价 × (1 ± 比例)，最小价格单位0.01元，Decimal ROUND_HALF_UP。上交所3.3.17及深交所对应计算条款还要求最少变动一档、价格下限一档；实现已覆盖。重新上市首日、退市整理首日等其他特殊事件不由普通IPO天数识别，遇到此类事件须补充专门元数据后再使用，不能宣称所有历史特殊交易日已支持。

## 除权除息

上交所4.3.2/4.3.3及深交所4.4.2/4.4.3：除权除息日以除权除息参考价计算涨跌幅，不是无条件使用昨天实际收盘价。本轮两个现金分红案例以发行人公告公式和腾讯未复权登记日收盘价独立复算，均与 BaoStock 当日 preclose 一致。证据见 outputs/stage35/ex_dividend_reference_validation.csv。此结论限定于已验样本，不声称验证了全部复杂送配股案例。

## S4 与范围

V1.4明确：真实封停使用 close_raw >= 真实limit_up_price；NEAR_LIMIT_UP不替代S4。本轮采用 closed_at_limit_up，同时保留 high >= limit_up 的 touched_limit_up 供审计。原文见 docs/SPEC_V1_4_EXTRACTED.txt。

本轮仅验收 SH/SZ。BJ = OUT_OF_SCOPE_FOR_V1；未将BJ检验缺失列为阻塞。当前行业归属仅为当前快照，不构成历史时点成分回溯。

S7数据验收按本轮用户明确要求以 expected constituent list 为分母。原配置中的 valid_components 评分文本未改写，SectorHeat正式评分未实现；数据缺失时保留覆盖率与 DATA_INCONSISTENT，不把缺失股判断为弱势股。
