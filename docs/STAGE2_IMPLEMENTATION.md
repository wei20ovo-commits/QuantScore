# Stage 2 实现说明

## 已落地

- Provider 抽象、AKShare 默认适配、可选 Tushare、超时/重试。
- SymbolResolver：`600519 -> 600519.SH`、`000001 -> 000001.SZ`、`000001.SH -> INDEX`。
- raw/qfq 严格按日期合并；固定 benchmark `000001.SH / 上证指数`。
- SQLite TTL cache、force refresh、数据校验、涨跌停可靠性分级。
- 日线特征、已完成周/月聚合、as_of 截断与无未来泄漏保护。
- StockAnalysisService、FastAPI health/analyze/rules/data status、CLI JSON。
- 离线测试保留原有测试，并覆盖 provider schema、symbol、benchmark、cache、retry、周期、look-ahead 和降级。

## 规则状态

Stage 2 已完成 D2、F1-X、F2、R3、R5 的执行器、分档/依赖守卫与业务边界测试；另有 13 条规则仍明确 NOT_IMPLEMENTED。数据不可得时任何规则仍可按契约返回 UNKNOWN，不能把数据缺失误报为 FAIL 或 PASS。具体见 `docs/RULE_IMPLEMENTATION_MATRIX.md`。

## 真实网络验收

运行 smoke 必须直接调用 AKShare 实际接口，记录版本、请求代码、行数、最后交易日、字段覆盖和异常。任何代理、超时、接口字段变化或网络不可达均写入 `NETWORK_FAILED`，最终 Stage 2 状态为 `PARTIAL`；不得使用人工 fixture 代替。

## 不在本阶段

不做 Stage 3 板块扫描、自动选股排名、Web UI、收益预测/回测、筹码分布或分钟级 R6。

## 恢复审计修复

- 局部修复既有 V1.4 Word 版本声明与页眉页脚；V1.1/V1.2/V1.3 不变。
- D2/F1-X/F2 按已冻结的全局连续分档 [a,b) 执行；旧源表显式不等式作为继承来源保留，不覆盖最终区间约定。结构性不等式不变。
- F2 使用 N 板 second_start_date（候选使用 first_start_date）或鲤鱼跃龙门 jump_date，不能用当前日替代事件日。
- 五条新规则的数字阈值/分值集中到 parameters.yaml，数值来自冻结规范，没有新增规则或修改权重。
- 历史 as_of 请求不补造 R7 冻结快照；现存冻结信号后续验证独立于历史分数。
- 涨跌停计算支持经核验的除权参考价；证据不充分仍 UNKNOWN。
- 规则原生结果增加 data_provenance，与 API Schema 保持一致。
- smoke 改为自动日期、完整 Service、真实 API/CLI 调用和五日均线抽查；当前网络失败时不声称成功。
- README、报告生成器、Schema、manifest 和实现矩阵同步 V1.4；原交接文件保留。
