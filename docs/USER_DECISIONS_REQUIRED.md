# V1.3 用户语义确认结案

No unresolved user-defined trading semantics remain in V1.3.

| ID | 规则 | resolution_status | resolution_source | 最终规则 |
|---|---|---|---|---|
| U01 | R7 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 三日High均<+3%时，最大收盘收益<=0扣10，其余0~3%扣6；任一High>=+3%则失效。 |
| U02 | E1 | RESOLVED_IN_V1_3 | USER_CONFIRMED | 最多1根4%~5%过渡阳计入7日，独立于最多1根小阴/十字星；第二根终止。 |
| U03 | F1-Y | RESOLVED_IN_V1_3 | USER_CONFIRMED | 收盘同时越过共振压力线与M60即可突破，无涨幅、量比或近涨停门槛。 |
| U04 | F1-O | RESOLVED_IN_V1_3 | USER_CONFIRMED | <=5%干净启动；5%~15%开区间部分2分；R12异常先清零。 |

旧问题原文保留于V1.2 Word和docs/archive/stage1_1_v1_2_baseline.zip，不删除历史。

数据缺失、历史长度不足、缺分钟或筹码数据、涨跌停价缺失、未来确认期不足、规则尚未实现仍可UNKNOWN；这些不是未解决的用户语义。
