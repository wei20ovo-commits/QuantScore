# QuantScore Stage 3A.5 Final Acceptance Result

## Current Project Audit

2026-09-29 实际核对工作区、Git历史及更新后的 origin/main：HEAD/origin/main 均为 e994a1c，远端仍是 Stage 2.6 初始提交；WorkBuddy 的 Stage 3A–3A.4 成果位于本地未提交修改/未跟踪文件。本轮未假定远端已经包含这些成果，未执行 reset、checkout 或推送。

## Existing Work Preserved

151个既有文件在修改前保存SHA256及ZIP快照。相对本轮基线，生产代码只修改 app/data/market_rule.py、app/sector/market_data.py；规范审计更新 docs/MARKET_LIMIT_RULES_SSOT.md。既有测试、UI、Provider核心、RuleEngine、ScoreEngine、配置权重未修改。新增55项测试。后续文档追加不会覆盖历史结论。

## Official Rule Consistency

官方依据：

- [上交所交易规则（2026年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)
- [深交所交易规则（2026年修订）](https://www.szse.cn/lawrules/rule/trade/t20260424_620190.html)

两者自2026-07-06实施，适用于所要求的2026-09-24以及本轮行情日。SH/SZ主板及主板风险警示10%，STAR/GEM20%，IPO首次上市前五个交易日无价格涨跌幅限制，计入上市当天。修复301创业板识别、IPO计数与缺失元数据防护，结果保存官方URL/effective_from/rule_id。BJ明确 OUT_OF_SCOPE_FOR_V1。

## Ex-Dividend Reference Price Validation

| 股票 | 除息日 | 前日实际收盘 | BaoStock preclose | 独立参考价 | 结果 |
|---|---|---:|---:|---:|---|
| 603018.SH 华设集团 | 2026-09-21 | 5.17 | 5.13 | 5.13 | MATCH |
| 301369.SZ 联动科技 | 2026-09-24 | 155.59 | 155.41 | 155.41 | MATCH |

独立路径：发行人现金分红公告公式 + 腾讯未复权登记日收盘价；原始公告、历史行情响应、URL与SHA256均保存。不是用BaoStock昨日close推导后冒充独立验证。两个现金分红样本支持使用当日preclose作为reference price；复杂送配股并未在这两个案例中验证，不能外推为全历史保证。

## S4 Independent Data Source

腾讯公开行情 qt.gtimg.cn，直接返回字段47/48涨跌停价、字段3收盘价、字段30时间戳。解析器检查代码、完整字段、日期、已收盘时间及有效价格；独立状态由真实收盘价与独立直接报告的涨停价比较，未重算另一套10%/20%公式作为独立价格。

## S4 Positive / Negative Samples

合格样本13只：4只收盘涨停、9只非涨停。正样本为600418.SH江淮汽车（SH MAIN）、002342.SZ巨力索具（SZ MAIN）、301190.SZ善水科技（GEM）、688244.SH永信至诚（STAR）。另含沪深各一只真实ST样本600107.SH、002193.SZ，当前10%涨停价均匹配。

## S4 Cross Validation

全部来源逐行保留14条：价格可比13条/匹配13条，状态可比14条/匹配13条，mismatch=1，已解释=1，未解释=0。

唯一冲突：观势公开涨停列表把600165.SH的3.37元（+4.98%）列为涨停，并仍标“ST宁科”。本轮BaoStock isST=0，腾讯名为“宁科生物”，腾讯直接报告涨停价3.53；交易所现行规则无论普通主板或MAIN_ST均为10%，3.37不能算收盘涨停。该列表的具体内部代码不可见，但其结论与官方制度及独立报价冲突已明确，不能作为合格验证源。冲突行保留在最终CSV，标记RESOLVED_SOURCE_RULE_INCONSISTENT；没有删除样本，也没有把全来源原始comparison_status的PARTIAL偷偷改为PASS。Stage验收依据13条合格独立比较及明确的冲突调查结论。

## S1 Re-run

使用本轮新取的raw/qfq、最新采集时点的行业快照、交易日历与上证指数。收益使用qfq close、行业等权平均。三个行业3/3 VALID，coverage=100%。采集在2026-09-29北京时间上午完成，当时最近完整交易日为2026-09-28；晚间回放不声称重新获取了9月29日收盘行情。

## S2 Re-run

真实交易日网格计算5个收益间隔，以第t日与第t-5日收盘比较，不把缺失行或休市日算成交易日。3/3 VALID；CSV保存窗口起止。

## S3 Re-run

保存上涨家数、有效家数、expected家数与breadth。3/3 VALID，不将缺失数据判为下跌。

## S4 Inputs

V1.4规范明确使用 close_raw >= verified limit_up_price，非仅high触及。63只逐股原始值、IPO/metadata、制度来源及结果均保存；行业有效数41/41、17/17、5/5，本日三个行业收盘涨停数均为0。零涨停是本轮真实结果，不能单独证明检测有效；正样本验证见前述独立样本。此处仅数据输入，不执行S4正式评分或最少成分数评分门槛。

## S5 Re-run

保存3行行业摘要及63行逐日证据（3行业×21日），今日金额与此前20个真实交易日均值分开。C18比值1.137915，C25为0.808071，H61为0.444181，3/3 VALID。修复缺失金额被求和掩盖及缺日均值的问题。

## S6 Re-run

保存15行逐日收益、benchmark收益、胜负和coverage（3行业×5日）。C18/C25/H61分别胜出2/4/1日。缺失近期日期不再用更早日期补足五天，3/3 VALID。

## S7 Re-run

按本轮用户要求使用完整expected constituent list作分母，分别41、17、5；三行业本日>=5%的家数均0，3/3 VALID。数据缺失时保留DATA_INCONSISTENT，不能靠缩小分母抬高占比。原评分配置未改动，SectorHeat评分未启动。

## Data Quality Summary

83行业，原始行业记录5556、有效SH/SZ归属5222；较上一轮有所变化，未复用旧成员CSV。目标3行业63成员，raw63/63、qfq63/63，最终bar_failure=0，真实上证指数和日历齐全。601007.SH复权请求初次失败、重试成功；fetch_log保留失败尝试，不把最终零失败误写成从未发生请求错误。S1–S7均3/3 VALID。

## Cache Evidence

原Stage3A.4脚本缓存了未包含于样本的600000空表，而且force_refresh后没有真正再次Provider请求，不能沿用其PASS表述。本轮未改缓存架构，以600519真实19行数据补验：首次Provider fetch、第二次cache hit、force_refresh实际再次Provider fetch，均保存as_of与时间。原文件未删改。

## Tests

实际完整pytest：526项，525 PASS，0 FAIL，0 ERROR，1 SKIP。新增55项，原471项保留。SKIP为自动选股排名（本阶段明确不实施）。一次中断运行遇到Windows临时目录错误，保留pytest.txt；最终使用项目内TMP/TEMP/TMPDIR及独立basetemp完成，原始结果为pytest_final.txt和pytest.xml。另有1条第三方Starlette弃用警告，不影响通过。

## Evidence Files

目录 outputs/stage35/：

- run_metadata.json、fetch_metadata.json、fetch_log.csv、membership.csv、bar_alignment.csv
- s1_inputs.csv … s7_inputs.csv
- s4_cross_validation_final.csv、s4_constituent_details.csv
- ex_dividend_reference_validation.csv
- s5_daily_amounts.csv、s6_daily_comparisons.csv、cache_verification.csv
- raw/、samples/、sources/ 原始响应与官方制度附件
- source_hashes.json、baseline_hashes.json、pre_stage35_workspace.zip、preservation_audit.json
- pytest_final.txt、pytest.xml

重放：PYTHONPATH包含.deps与项目根目录，执行python tools/stage35_replay.py；重放只读取本轮真实存档，不调用网络，也不生成mock。重放会重置验收状态为PENDING_TESTS，需要重新检查测试与冲突后签结论。

## Remaining Issues

无阻塞本轮SH/SZ数据验收的未解释冲突。保留限制：当前行业归属不是历史时点归属；本轮是2026-09-28收盘快照，不是实时行情；复杂除权、重新上市/退市整理特殊首日不在已验样本；公共数据源可能失败，需继续保守报告。工作区Stage3A成果仍未提交到GitHub。未修改UI、评分权重，未接入SectorHeat/B1/B2，没有自动选股或Stage3B。

## Stage 3A Final Status

**PASS — Stage 3A Industry V1 (SH/SZ)**。原始跨来源冲突仍保留，正式验收依据已核实有效来源、已解释冲突及0失败测试。BJ不在V1验收范围。完成后停止。
