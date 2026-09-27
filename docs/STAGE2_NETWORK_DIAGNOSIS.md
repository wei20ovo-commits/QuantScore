# Stage 2.1 Network Diagnosis

## 结论

正常代理路径与隔离直连均未取得日线。已定位代理继承来源，但没有证据证明代理是唯一原因，也不能据此判定 AKShare 本身故障。Stage 2.1 真实验收仍为 PARTIAL。

## 环境与实际请求

HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY（含小写）全部未设置。获授权的正常 Python 进程 urllib.getproxies() 读取到 Windows 代理 http/https/ftp = http://127.0.0.1:7897。环境变量为空不代表 Python 不使用代理。未修改 Windows 代理、VPN、注册表或用户环境。

AKShare 1.18.97 的 stock_zh_a_hist（raw、qfq）及 stock_zh_index_daily_em 实际请求：
https://push2his.eastmoney.com/api/qt/stock/kline/get

完整诊断及异常 traceback / cause / context / reason 链保存在 outputs/runtime/stage2_1_network_diagnosis.json；诊断时间 2026-09-26T08:03:52 UTC。

| 请求 | 正常环境 | 当前隔离 Python 进程忽略代理 |
|---|---|---|
| 股票 raw | ProxyError | ConnectionError |
| 股票 qfq | ProxyError | ConnectionError |
| 上证指数 | ProxyError | ConnectionError |

正常异常链：requests.ProxyError → urllib3.MaxRetryError → urllib3.ProxyError（Unable to connect to proxy）→ http.client.RemoteDisconnected（Remote end closed connection without response）。
直连异常链：requests.ConnectionError → urllib3.ProtocolError → RemoteDisconnected。
诊断记录实际请求代理：正常为 127.0.0.1:7897，直连为空。证券代码/名称解析成功，不能把日线端点失败等同于全部网络不可用。

## Provider 回退

仅遇 ProxyError 时，在 AKShare 专用子进程临时屏蔽 Requests 初始请求和重定向的系统/环境代理查询，直连重试一次。保留证书验证与 TLS 环境设置。finally 恢复两处查询函数，不修改 os.environ。父进程及其他 API 请求不受影响；超时采用子进程总截止，回退失败不再叠加外层重试。

离线测试覆盖正常请求、仅 ProxyError 回退、直连成功/失败、异常链、环境与函数恢复及 TLS 设置保留。离线测试不作为真实行情成功证据。

## 回退后的真实复测

600519 → 600519.SH / 贵州茅台、000001 → 000001.SZ / 平安银行、000001.SH → 上证指数解析通过。两只股票 raw/qfq 和上证指数日线仍均为代理失败后直连 ConnectionError，volume/turnover 未取得，不填造数据。

实际执行 python -m app.cli analyze 600519 --json：JSON有效，退出码1，data_status=UNAVAILABLE。
FastAPI真实Provider的 /api/analyze/600519：HTTP200，data_status=UNAVAILABLE。该响应表示降级报告成功，不表示行情获取成功。

没有真实 qfq close，五个交易日 M5/M30/M60 手工复核未执行。复测完整结果：outputs/smoke/stage2_smoke_report.json。后续需在该日线端点可达时重新执行 tools.stage2_smoke；本轮不进入 Stage 3。
