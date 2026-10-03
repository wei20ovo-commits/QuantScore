# QuantScore Stage 3C Runtime Diagnosis

> **Historical runtime snapshot (2026-10-02 20:27 Asia/Shanghai):** This diagnosis preceded completion of the original run on 2026-10-03. Current acceptance is recorded in [Stage 3C final result](STAGE3C_RESULT.md).

## Original Process
PID 11468。进程启动于 2026-10-02T16:01:33.0684360+08:00；Full phase 于 2026-10-02T16:41:26.657057+08:00 开始。原任务存活，无 end_time。本轮只观察该进程，没有启动新扫描、生成Universe或行情请求。

## Process Tree
5次采样，间隔30秒，2026-10-02T20:25:48.677381+08:00 至 2026-10-02T20:27:48.678594+08:00，覆盖 120.001 秒。
子PID为31632，之后变为18040；观测到1次更换，约 0.500 次/分钟。两个worker的创建时间差为 112.831 秒；仅是观测窗口，不能外推长期固定频率。
主进程CPU增量 0.03125 秒，单核均值 0.0260%；内存 289.04 MiB，21线程，617 handles。逐次主/子进程CPU、内存、线程、handles详见CSV。

## Business Progress
24/83行业，0股票。当前记录质量：{'DATA_INCOMPLETE': 9, 'VALID': 14, 'DATA_ERROR': 1}。
最后最终记录为C26化学原料和化学制品制造业，354个成分股，DATA_ERROR / NOT_EVALUABLE，原因BaoStock login error 10002007: 网络接收错误。
该记录于 2026-10-02T20:14:27.819227+08:00 写入，比采样末尾早 13.35 分钟；此前23/83检查点为17:15:42。
最近缓存写入 2026-10-02T19:52:57.106990+08:00，002666.SZ qfq，距采样结束 34.86 分钟。
BUSINESS_PROGRESS=true（冻结的最近30分钟定义：有新行业最终记录）；本次120秒窗口内业务增量=false（无新记录、无新缓存）。推进到失败最终记录不代表行情恢复成功。
最新业务文件为 outputs\stage3c\full_market\run_metadata.json；监控工具写入不计为业务推进。

## Current Object
当前sector_id/sector_name/symbol/provider operation均UNKNOWN。C26是最后完成对象，002666.SZ是最后持久化成功结果，不是当前正在处理对象。不根据顺序推断C27，也不将最近错误符号作为当前请求。

## Provider State
BaoStock；SDK配置endpoint=public-api.baostock.com:10030（源码配置，不等于已建立连接）。5次连接采样均仅见Bound，没有Established。
最后持久化cache frame有 57 行；这是已有结果，不是本轮新请求。
最后检查点Provider逻辑请求1595，worker_starts=14，14条请求错误；这些指标在行业结束时才更新，不能当成实时调用状态。
request start / wait duration未知；单个请求是否持续超过10/20/30分钟均UNKNOWN。

## Retry State
最后检查点retry_count=10。该计数为曾失败的相同请求再次调用，不等同所有错误次数。
C26日志可确认002648.SZ qfq和002669.SZ、002734.SZ、002748.SZ raw发生网络接收错误；002748.SZ attempt=1/2/3均已记录。观察到worker更换活动，但当前请求重试序号UNKNOWN。
RUNTIME_CONTROL_BUG=UNKNOWN：没有单次请求开始/结束时间，不能证明当前请求越过设计期限。静态审计确认存在无总期限的等待路径，详见下一节。

## Timeout Audit
| Layer | Boundary | Gap |
|---|---|---|
| SDK socket | 默认connect/read/send阻塞操作45秒 | 整个多次recv响应无累计期限；DNS无单独期限；SDK recv循环未处理空字节EOF，可能循环，但无当前死循环证据 |
| Batch worker | pipe.poll(150)等待结果 | send、poll后的recv未设期限；这不是覆盖整个请求的硬期限 |
| Worker cleanup | join(1)后terminate | send(None)及terminate后的join没有期限 |
| Provider mutex | 成功间隔0.3秒，失败间隔1秒 | 获取mutex无期限；排队时间不在poll(150)内 |
| Industry fetch | 每个fetch最多3次 | pool.map无timeout，线程池退出会等已排队/运行任务；无per-sector deadline |
| Stock ProviderManager | 默认2次，配置最多3次 | 每个长历史字段组另有请求；无per-stock deadline |
| Screening | 顺序行业再股票 | RUN_LOCK无期限，无whole-run deadline |

因此“150秒×3”不能作为一个行业的全程上限。354个成员及其他字段/日历请求、序列化等待、线程池排空均可能累计耗时。没有单行业硬上限，IPC/锁/清理还存在无界等待路径。本轮未修复或重构。
源码位置详见runtime_diagnosis.json的timeout_audit；核心代码未改。

## Progress Classification
**PROGRESSING**：最近30分钟有新行业最终记录，因此不满足STALLED所需连续60分钟无最终记录且无新有效Provider结果的条件。
当前120秒内无业务变化、CPU接近零、worker更换、Bound socket，支持Provider等待活动判断，但不能确定具体调用、证明死循环或确认单请求超限。
没有CRASHED证据。保留“正常完成推进”与“推进到失败结果”的区别。

## Throughput
Full phase已运行 13582.022 秒；24个行业最终记录；平均 565.918 秒/已完成行业（包括DATA_ERROR，非成功行情吞吐）；约 6.361 个最终记录/小时。本采样窗口吞吐为0。

## Projected Remaining Time
线性估计剩余59行业耗时 33389.136 秒（约 9.27 小时）；行业阶段投影结束时间 2026-10-03T05:44:17.814872+08:00。
**estimate only / not completion guarantee**。不含股票阶段；行业大小和网络状态不同，当前长等待使线性估计高度不稳定，不是产品承诺。

## Safe Termination Recommendation
SAFE_TERMINATION_RECOMMENDED=false。本窗口分类为PROGRESSING，不自动kill或重启；现有最终验收watcher继续等待。
未发现可由外部调用的扫描级安全取消机制。worker自身超时terminate不是安全终止整轮扫描机制。如后续达到STALLED，需保存证据再向用户报告。

## Evidence Files
- outputs/stage3c/runtime_diagnosis.json：分类、所有字段、边界与吞吐。
- outputs/stage3c/runtime_samples.csv：5次逐进程采样。
- outputs/stage3c/runtime_samples_detail.json：子进程变化、已有TCP状态、检查点与缓存响应。
- tools/stage3c_runtime_observe.py：只读采样工具，不导入Provider，不启动scan。
原full_market、small_live及历史PARTIAL证据保留。

## Stage 3C Status
PARTIAL。仍要求83/83行业及后续合格行业股票完整处理，并在完成后通过pytest。未改变验收语义；本轮未运行可能干扰原任务的测试。未修改筛选、评分、UI；未commit/push；不进入Stage3C.1或Stage4。
