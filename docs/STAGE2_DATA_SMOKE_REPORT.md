# Stage 2.2 真实数据 Smoke Report

真实验收状态：**PASS**。运行开始：2026-09-26T08:56:13.765598+00:00；指数复测：2026-09-26T09:04:28.568142+00:00。

BaoStock 0.9.4；无 mock、无人工行情回退。先刷新，再复用同轮真实缓存。实际源最新日期为2026-09-24，不将其冒充9月25日行情。

| 证券 | 名称 | 日线数量 | 源 | 状态 |
|---|---|---:|---|---|
| 600519.SH | 贵州茅台 | 6086 | baostock | PASS |
| 000001.SZ | 平安银行 | 6479 | baostock | PASS |
| 000001.SH | 上证指数 | 6479 | baostock | PASS |

股票raw/qfq按日期严格对齐，volume/amount/turnover真实返回；早期个别空换手率保留缺失。指数不定义股票换手率，不补造。BaoStock代码sh.000001的类型与名称已通过真实query_stock_basic确认。

## CLI / FastAPI

python -m app.cli analyze 600519 --json：退出0，JSON有效，symbol=600519.SH，name=贵州茅台，provider=baostock。
/api/analyze/600519：HTTP200，真实数据分析完成。data_status=PARTIAL源于缺可靠涨跌停价/早期可选字段，不是网络不可用；相关规则仍UNKNOWN。

## 均线核验

每种证券固定随机种子抽查5个真实交易日；对各日前5/30/60个qfq收盘价用math.fsum独立求均值，与系统rolling均值比较。共45项全部PASS。指数使用未复权close等值映射到标准adj字段，不声称指数存在股票复权。

| 证券 | 抽查交易日 | M5/M30/M60 |
|---|---|---|
| 600519.SH | 2005-07-18, 2019-09-09, 2022-09-07, 2023-11-29, 2025-08-14 | PASS |
| 000001.SZ | 2003-12-01, 2021-01-25, 2022-04-19, 2023-12-28, 2025-10-15 | PASS |
| 000001.SH | 2003-12-01, 2021-01-25, 2022-04-19, 2023-12-28, 2025-10-15 | PASS |

## 保留的限制与失败记录

首轮单独刷新完整指数历史发生一次BaoStock总截止超时；复测真实刷新成功。首轮完整失败记录保留在JSON的cases[2].previous_attempts。AKShare继续保留，本轮未继续诊断其网络。
历史涨跌停价缺证据、筹码/分钟等数据缺失仍UNKNOWN；35条规则IMPLEMENTED、13条NOT_IMPLEMENTED未变。前复权为获取时口径，不是历史时点复权快照。

## 证据

- outputs/runtime/baostock_sdk_probe.json：登录登出、接口字段与代码核验。
- outputs/smoke/stage2_smoke_report.json：真实请求、评分、API/CLI和45项均线值。
- outputs/smoke/stage22_cli_600519.json / stage22_api_600519.json：完整真实输出。
- outputs/smoke/*_baostock_bars.csv：三种证券本轮实际日线。
