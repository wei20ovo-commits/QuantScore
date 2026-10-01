# QuantScore Stage 3B.1 Live Recovery

当前状态：PASS。未commit/push，未进入Stage 3C。

## Original Failure
旧outputs/stage3b1失败记录保留。全历史请求返回10002007，CLI exit 1，HTTP 200仅为UNAVAILABLE降级。

## Error and Root Cause Evidence
安装的BaoStock SDK源码security/history.py将socketutil.send_msg返回空响应映射为10002007；common/contants.py定义为网络接收错误。直接SDK真实返回error_msg=“网络接收错误。”，stdout捕获“timed out”。这定位了失败机制为接收超时，不能凭此断言具体服务器内部故障或本机路由原因。
同样的字段在短窗口成功；2000-01-01至2026-09-30的完整字段请求在12秒及60秒socket配置下失败。最小字段长窗口得到6089行；窗口与字段宽度共同影响传输稳定性，不能把某个字段标成非法。
两组诊断曾短暂并行，并捕获10001001/用户未登录；相关记录单列overlap_*，不混入严格串行对照，也不据此断言服务端会话实现。

## Isolation Matrix
54个组合覆盖3代码、2复权、3日期长度、3字段集合；额外包含单次、顺序三股、两种raw/qfq顺序、节流重试以及12个逐字段测试。矩阵共75行，73个成功、2个真实10002007失败。长窗口对照另见long_window_tests.json。最初失败没有被后续成功覆盖。
日期由query_trade_dates核验，初始system_date=2026-09-30，latest_completed_trade_date=requested_end_date=2026-09-30。执行跨越10月1日，尚未收盘的新日不进入请求截止日；actual wrapper parameters另行逐次留存。

## Session and Parameters
默认Provider每次查询使用独立子进程，fresh login→完整读取→finally logout，异常后下次新会话；不复用旧SDK client。新增应用进程内跨Provider实例锁与0.3秒请求间隔，失败后下一次请求间隔1秒。保持既有调用方最多3次尝试，不增加无限重试。
规范代码转换保持600519.SH→sh.600519；参数统一YYYY-MM-DD、frequency=d、raw=3、qfq=2。B2仍用qfq close，S4仍用raw preclose。socket等待上限45秒，进程整体截止150秒，有限等待仍不能保证远端始终可用。

## Transport Fix
超过120自然日的传输按字段组拆分，每组date/code加最多3个字段；每组保持完整起止日及相同复权标记。严格核对全部date/code序列并一对一合并，禁止填充、丢弃或重算字段。120日仅为传输分组选择，不是评分阈值或价格观察窗口。任何组失败则整份行情失败，不缓存部分结果。
同时保留SDK原始错误消息及实际请求参数；不再只留下10002007统一码。评分层无联网、节流或传输逻辑。

## Cache Audit
cache_audit.json记录历史缓存扫描；未发现空日线条目。发现早期疑似分页截断条目，均已超过既有TTL，不作有效命中，原件保留。当前分页失败与字段组错配会抛错，完整校验之前不写行情缓存。force_refresh=True的真实API调用已在wrapper_requests.json记录新Provider请求。

## B1 Data Status
UNKNOWN仅为业务判断状态；raw_values和序列化输出同时保留upstream_data_status、sector_heat_status、provider_error_code/原因。包括股票行情整体失败的降级路径，B1/B2仍为None，而非0。

## Tests
727项：726 PASS / 0 FAIL / 0 ERROR / 1 SKIP。新增4项直接针对SDK错误保留、会话互斥、分组字段口径及错配拒绝；原测试全部保留。已有B1四种数据状态测试补充检查上游状态。

## Live Acceptance

| Symbol | Industry | Heat | B1 | B2 | QuantScore | Risk | Status |
|---|---|---:|---:|---:|---:|---|---|
| 600519.SH | C15酒、饮料和精制茶制造业 | 70 | 6 | 1 | 0.0 | HIGH | SUCCESS |
| 600688.SH | C25石油、煤炭及其他燃料加工业 | 30 | 0 | 2 | 0.0 | HIGH | SUCCESS |
| 600107.SH | C18纺织服装、服饰业 | 6 | 0 | 1 | 0.0 | HIGH | SUCCESS |

全部数据日期2026-09-30；BaoStock真实数据，无mock。原始JSON保存完整规则、原始输入和来源。股票DataStatus=PARTIAL来自原有历史涨跌停价等客观缺项，不等于行情UNAVAILABLE；本轮行业Heat/B1/B2必须完整可判定才计为E2E成功。

## CLI / FastAPI

CLI真实exit=0，JSON可解析；完整行业与B1/B2校验=True。FastAPI通过TestClient真实调用现有路由及真实Provider，不以HTTP 200单独判成功，另核验raw/qfq数量、基准、非mock、日期和完整Heat。

## Remaining Issues

首次完整行业分析较慢；外部网络仍可能间歇失败，采用有限重试并保留UNKNOWN及上游原因。没有服务端内部日志，不宣称已证明某个字段非法或确认服务端限流。历史无可靠涨跌停价/分钟/筹码等UNKNOWN仍保留。所有失败证据保留；输出目录仍遵循项目既有gitignore，未自动发布。

## Status

PASS
