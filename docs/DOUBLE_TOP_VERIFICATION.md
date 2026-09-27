# R4 双子顶 V1.3 验证范围

执行器：`app/rules/patterns/double_top.py`。规范来源：Word的R4、3.2/3.3、10与T06/T07。参数位于`config/parameters.yaml`的R4及GLOBAL。

| 条件 | 执行行为 |
|---|---|
| 历史/复权 | 至少30根；检验实际扫描窗口；adjustment_consistent必须明确为true，否则UNKNOWN |
| 高位 | P1/P2任一满足HIGH_ZONE，或P1前20日涨幅>=15%；缺数据且无法由其他分支确定时UNKNOWN |
| 峰值 | high为左右各2根窗口最大值；P1必须已确认；P2右侧未齐仅作候选 |
| 间隔 | 4至20个交易日，含两端 |
| 高差 | abs(H2−H1)/H1<=3% |
| 谷底 | 仅取P1与P2之间、不含两峰的最低low |
| 回撤 | (min(H1,H2)−Valley)/min(H1,H2)>=5% |
| 颈线 | neckline=Valley，严格close<neckline才确认 |
| P2有效突破 | close[P2]>H1×1.03否定双顶；不另发明failed breakout阈值 |
| CANDIDATE | 结构满足、尚无已确认走弱，扣4 |
| FORMED | P2后第1~3日close<M5或较P2收盘跌>=3%，扣8 |
| CONFIRMED | P2后收盘严格跌破颈线，扣12 |
| INVALIDATED | P2后连续2日收盘严格>H1×1.03，扣0，覆盖已有确认/形成状态 |
| 去重 | 选定结构只给一个状态与一次扣分，事件ID由两峰日期组成；汇总重复输入不会重复扣分 |
| 多结构 | P2最近优先；同P2取绝对峰高差最小；完全同值以P1最近稳定排序 |

raw_values保留P1/P2日期、价格、Valley日期、间隔、高差、回撤、前期涨幅、高位证据、后续每日收盘/M5和状态转移日期。conditions保留所有布尔条件、峰确认状态及failed_breakout说明性字段。

局部峰不使用未来数据；右侧未齐保留CANDIDATE，不提前晋级。多结构按V1.3确定排序，不再因多组合法结构直接UNKNOWN。平顶沿用非严格局部最高定义。

从CANDIDATE开始输出exit_risk_alert=true、alert_type=DOUBLE_TOP_EXIT_RISK及用户指定提示；INVALIDATED撤销提醒和扣分。测试新增同P2不同峰差选择、提醒撤销、右侧未齐及历史截断。

状态不是股票涨跌概率。测试全部为明确标记的人工OHLCV，涵盖四种状态、最新日候选、右侧未齐、颈线、有效突破连续性、峰高差、谷底回撤、高位前置、缺数据/复权标记、重复风险和评价日截断。实际通过情况以pytest报告为准。
