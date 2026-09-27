# QuantScore Stage 2 数据 Provider 设计

## 范围

Stage 2 接入真实 A 股日线与固定上证指数基准，不改变 V1.3 评分权重和规则语义。V1.4 只新增数据契约字段：`benchmark_index=000001.SH`、`benchmark_name=上证指数`。

## 架构

```text
SymbolResolver
  -> ProviderManager
     -> BaoStockProvider（默认真实源）
     -> AKShareProvider（保留的第二顺位源）
     -> TushareProvider（可选，只有 TUSHARE_TOKEN 且权限可用时启用）
     -> DataCache（SQLite，TTL/force_refresh）
     -> DataValidator
     -> FeatureBuilder / Weekly-Monthly Resampler
     -> StockAnalysisService
     -> RuleEngine / ScoreEngine
```

Provider 只负责外部数据和字段适配；规则只消费标准 DataFrame。Adapter 内部可使用数据源代码，系统内部必须使用 `canonical_symbol`。

## Provider 策略

- AKShare 使用运行环境实际安装版本的 `stock_zh_a_hist`（raw 与 qfq 分开获取）和 `stock_zh_index_daily_em`（`sh000001`）。
- Tushare 为增强源，不是默认硬依赖；可补充历史涨跌停和换手率。
- 单次请求有硬超时，失败最多重试 3 次；失败进入明确 `ProviderError`，不无限重试。
- 真实网络 smoke 失败必须记录 `NETWORK_FAILED`，不得以 MockProvider 冒充真实通过。

## 代码解析

- `600519`、`SH600519`、`600519.SH` 解析为 `600519.SH`。
- `000001` 按真实证券列表解析为股票 `000001.SZ`。
- `000001.SH`、`SSE_COMPOSITE`、`BENCHMARK` 解析为 INDEX 上证指数。
- 不通过代码前缀猜测交易所；无真实证券列表时拒绝裸代码。

## 缓存与降级

缓存键包含 provider、symbol、start_date、end_date、adjustment；缓存只存行情 JSON，不存 token/cookie。股票与基准可分别降级：基准缺失只使 A1/A2/A3 等依赖基准的规则 UNKNOWN；涨跌停价不可可靠确认时只影响相关规则。

## 安全边界

真实凭据只允许来自运行时环境；仓库不提交 token、cookie、API key、个人账号或大型缓存。`MockProvider` 仅用于离线测试，并通过 `is_mock=true` 显式标识。

## 当前计算来源限制

MarketLimitResolver 不内置凭代码前缀猜测的市场规则表。计算路径要求调用方提供带有效期的规则证据、历史 ST/上市状态、参考价验证标记；若除权参考价与昨日原始收盘价不同，使用显式 reference_price。默认 AKShare 不能提供这些完整历史证据时进入 UNKNOWN。不能把测试中提供的已核验元数据称作真实市场验证。

R7 历史请求不写入新的历史快照；只对已存在的不可变快照提供独立 forward confirmation。历史 qfq 为获取时口径，非 point-in-time 数据库；复权口径冲突如实返回 INVALID_SNAPSHOT。

基准获取通过 BaseProvider.fetch_benchmark 与 BaoStock/AKShare/Tushare 适配实现，不另建第二套重复 Provider。FastAPI 保留初始化后的 Service，从而复用证券列表与行情缓存。单次字段获取最多尝试3次（包含首次）。

## Stage 2.2 BaoStock 与配置回退

配置文件 config/data_providers.yaml 的 provider_order 控制默认顺序：baostock → akshare → tushare。Tushare 仅 Token 和 SDK 可用时加入。显式注入单 Provider 保持兼容；providers 可注入有序列表。股票 raw/qfq 在同一 Provider 内严格按日期配对，任一失败则整组切换，禁止混源复权；基准可单独回退。缓存键包含数据源，返回 metadata.provider/data_provenance/provider_attempts 记录实际来源和失败链。无可用源返回 UNAVAILABLE。

实际安装 baostock==0.9.4，已读取其 login/logout/query_history_k_data_plus/query_stock_basic 代码并真实验证。维护者文档：https://pypi.org/project/baostock/ 。adjustflag：3=不复权、2=前复权、1=后复权（本项目不请求后复权）。真实接口证据：outputs/runtime/baostock_sdk_probe.json。

600519.SH→sh.600519；000001.SZ→sz.000001；000001.SH→sh.000001。最后一项真实 query_stock_basic 返回 type=2、上证综合指数，系统标准名保持上证指数。证券名称由真实证券表取得，非人工生成股票资料。

| 源字段 | 标准字段/处理 |
|---|---|
| date / open high low close | date及严格对齐后的*_raw / *_adj |
| volume | 股，不乘100 |
| amount | 元 |
| turn | turnover_rate，百分点，不除100 |
| preclose | 原始日线参考前收盘字段，保留 |
| tradestatus / isST | 数值保留，空值不补造 |
| code / code_name | canonical symbol / name / exchange |

指数不请求 turn/tradestatus/isST，缺失保持空值。保留原始停牌记录，不静默剔除或对价格前向填充。preclose/isST/tradestatus 尚不足以证明完整历史涨跌停制度，MarketLimitResolver继续保守返回 LIMIT_PRICE_UNRELIABLE；不推断涨跌停价。

BaoStock SDK使用全局会话，因此生产请求放入独立子进程：login→query/分页校验→finally logout，抑制SDK打印以保持CLI JSON合法。连接/读取有socket超时，父进程设置总截止；若SDK卡死无法执行finally，最终终止专属进程并关闭socket，不宣称服务器确认登出。正常和异常请求退出路径均测试登出。未修改全局代理、VPN或其他项目。
