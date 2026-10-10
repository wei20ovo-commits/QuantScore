# Stage 4C.7-R1 — Test Gate Recovery

日期：2026-10-10。范围：本地正式 `.venv` 测试门禁恢复；不是公网、行情或真实 AI API 验收。

## 基线与历史失败

HEAD 为 `93e6eb2b883bebe54297a2be567a7af91d20153e`。开始时 12 个 Stage4C.7 文件已暂存；保存 index 与全部 staged entries 的 SHA256，未执行 add/reset/restore/commit/push。

两份原始 WorkBuddy XML 和 TXT 位于 `outputs/tmp/stage4c7-checkpoint*`，保持原样。只读审计得到：

| 记录 | PASS | FAIL | ERROR | SKIP | 总数 | pytest 耗时 |
|---|---:|---:|---:|---:|---:|---:|
| checkpoint | 1015 | 1 | 0 | 1 | 1017 | 378.950s |
| checkpoint-retry | 1010 | 6 | 0 | 1 | 1017 | 1437.314s |

首轮失败为 `test_theme_navigation_and_real_result_session_history` 的首次 `.run()`，默认 3s 超时。第二轮失败如下：

| 用例 | 断言 / 失败位置 | 原记录用例耗时 |
|---|---|---:|
| `test_navigation_no_scan_or_auto_analysis[sectors]` | 导航后的默认 3s `.run()` | 15.162s |
| `test_data_error_sector_page_has_missing_score_and_explicit_status` | 首次默认 3s `.run()` | 6.283s |
| `test_missing_or_bad_snapshot_ui_graceful[home-UNKNOWN]` | 首次默认 3s `.run()` | 8.834s |
| `test_missing_or_bad_snapshot_ui_graceful[sectors-UNKNOWN]` | 首次默认 3s `.run()` | 11.917s |
| `test_missing_or_bad_snapshot_ui_graceful[candidates-UNKNOWN]` | 首次默认 3s `.run()` | 989.009s |
| `test_actual_spawn_paths_emit_parent_terminal_at_warning[timeout_worker_target-TIMEOUT]` | 实际日期 UNKNOWN，原断言预期 2026-09-30 | 8.698s |

用例总耗时不等于 AppTest 预算。已安装 Streamlit 1.64.0 的 `require_widgets_deltas` 超时后执行 `request_stop()` 和 `join()`；线程完成清理后才抛异常。因此不能根据 989s 推断业务请求进行了 989s，也不能据此确定 Git、网络或 OS 资源竞争是当时的唯一根因。

## UI 超时：证据、因果对照与修复

未修改源码时，六个历史失败 UI 用例组合运行 **6 PASS**；各用例独立新进程运行也全部通过。历史的自然超时本轮 **NOT_REPRODUCED**，不声称重现了 WorkBuddy 当时的机器负载。

每个独立测试记录所有 LocalScriptRunner 的初始运行、主题/导航重跑、分析后的渲染，以及 main、部署识别、Git、快照读取与渲染函数耗时。记录在 `outputs/stage4c7_r1/before_independent_*.json`：

- 首次 AppTest 运行为 1.581–2.330s；首页 / 导航重跑通常为 0.568–0.758s。
- 每次版本识别为 0.478–0.544s，包含 3 次 Git 子进程及来源文件指纹读取；它在每次 rerun 重新执行，不由行情缓存承担。
- 首次组合剖析中 `render_home` 最大 0.257s；版本识别最大 0.569s，单次 Git 最大 0.166s。未观察到 Provider 请求或 Full Market Scan。
- imports/ScriptRunner/元素树/线程清理包含在 AppTest 总耗时中；未取得历史单模块导入计时或 OS 竞争记录，不将这些列为已证明的历史根因。

确定的源码问题：可选部署版本识别串行执行 **3 个独立 2s Git 等待**，没有共享截止；其潜在等待预算超过 UI 测试默认 3s。使用仍受保护的 staged 源码在内存中做对照，不改变文件或 index。仅向 Git wrapper 注入每次 1.1s 延迟，保持真实 Git 查询、相同页面、相同测试 3s 预算和离线数据 fixture：

| 源码 | 正常 Git | 延迟对照 1 | 延迟对照 2 |
|---|---|---|---|
| 受保护 staged 基线 | PASS，2.0043s | APPTEST_TIMEOUT，3.9771s | APPTEST_TIMEOUT，4.0004s |
| 修复工作树 | PASS，1.8773s | PASS，1.4825s | PASS，1.4185s |

这是**受控因果复现**，不是实际 Cloud 或 WorkBuddy 历史负载证据。它证明新增可选诊断能够独立导致 3s UI 超时，并证明本次修复消除了该等待预算累积。

最小源码修复仅在 `app/web_deployment.py`：

1. 同一次 `git rev-parse --show-toplevel HEAD` 取得仓库根与实际 SHA，保持根目录和 SHA 校验。
2. Git 命令共享 1s 的剩余等待预算；不引入部署识别缓存，不硬编码 SHA。
3. Git 不可得 / 超时时诚实返回 SHA 或修改状态 UNKNOWN；继续按原算法读取真实源码指纹。已核验的 SHA 不因后续 status 超时被伪造或替换。

该预算属于可选身份诊断的 subprocess 等待，不是硬实时的整页 SLA；OS 进程创建、文件读取与调度仍可能额外耗时。生产 240s 请求截止、Provider timeout/retry、缓存 TTL、评分与 AI 逻辑未修改。

## spawn 日期：读取时序、对照与隔离修复

原测试 target 定义在导入 Streamlit/AppTest/FastAPI/分析 fixtures 的完整测试模块中。Windows spawn 为反序列化 target 必须重新导入该模块；原 8s 截止从 `process.start()` 前开始，包含启动、导入、GO gate、target 执行和诊断写入。原断言隐含了“在 8s 内必定到达 context emit”的未保证前提。

生产时序保持不变：

`spawn/import → GO → bind_sink → target 读取 → context emit → diagnostic.partial 原子替换 → timeout 父进程读取 diagnostic.json → terminal WARNING → 停止自有进程 / 清理`。

原文件不存在 / 读取失败时，父进程没有可信日期，返回 UNKNOWN；不能从测试期望或旧快照推填日期。原历史失败记录没有进程启动标记、context log 或 diagnostic.json 内容，**不能唯一证明当次是尚未读取、I/O 写入失败还是读取时序问题**，不声称历史日期已丢失或已经证明未丢失。

受控实际 spawn 证据 `before_spawn_isolation.json`：

| 路径 | 到终态耗时 | qfq 已观察耗时 | 日期 |
|---|---:|---:|---|
| 原完整测试模块 target | 8.0208s | 5.6410s | 2026-09-30 |
| 轻量 target，实际读取离线 fixture 文件 | 8.0124s | 7.0780s | 2026-09-30 |
| target 已进入，但在读取 snapshot 前等待 | 8.0058s | UNKNOWN | UNKNOWN |

两条已读取路径的截止与 qfq 计时差分别约 2.380s / 0.934s，包含启动和到 fetch 的准备开销；不是纯导入时间。第三条通过 `.ready` 标记证明 target 已进入，但快照尚未读，**其 UNKNOWN 正确**。

最小测试隔离修复：将原三个 target 移到 `tools/stage4c7_r1_workers.py`，模块顶层只导入标准库，不重新导入 UI / pytest / 分析 fixtures。target 从测试创建的实际离线 context JSON 读取日期，明确不是实际市场数据。保留原成功、失败、超时用例 ID、全部日期/状态/qfq/日志/清理断言及 20s/8s 原预算。新增读取前超时用例，断言 UNKNOWN、同一 request_id 的终态 WARNING 和自有目录清理。没有修改生产 worker 或填充日期。

## 测试框架参数

**没有提高 AppTest 默认 3s，未提高原 spawn 8s，不增加 SKIP，不删除既有用例或断言。** 原分析提交显式 20s 也保持原样。所有临时目录在项目 D 盘，完整门禁使用新的 `outputs/tmp/pytest-stage4c7-r1/formal`，不清理历史临时目录。

新增 3 个测试：Git 共享剩余预算、Git timeout 的真实指纹 fallback、读取快照前超时的 UNKNOWN 与终态日志。

## 修复后独立、组合与顺序验收

| 验证 | 结果 | 证据 |
|---|---|---|
| 历史六个 UI 用例 + spawn 超时各自独立进程 | 7/7 PASS | `after_independent_*.xml/json` |
| 完整 observability 套件 | 28 PASS | `after_observability.xml` |
| observability → product → ui_final | 83 PASS / 0 FAIL / 0 ERROR / 0 SKIP | `after_combined.xml` |
| ui_final → product → observability | 83 PASS / 0 FAIL / 0 ERROR / 0 SKIP | `after_reverse.xml` |

组合与反序 AppTest 默认 3s 的实际单次最大分别为 2.4131s / 2.5782s。独立进程与组合、反序均通过；既有 cache clear fixtures 保持不变，cache MISS/HIT 和每次 request_id 的原断言仍通过。未观察到顺序依赖，但这不证明任意 OS 负载下永不超时。

## 完整正式回归

正式命令：`.venv/Scripts/python.exe -m pytest --basetemp=outputs/tmp/pytest-stage4c7-r1/formal --junitxml=outputs/stage4c7_r1/formal.xml`。该次完整运行不加载计时 plugin，使用新的 D 盘临时目录，退出码 **0**。

| 总数 | PASS | FAIL | ERROR | SKIP | XML 实测耗时 |
|---:|---:|---:|---:|---:|---:|
| 1020 | 1019 | 0 | 0 | 1 | 246.556s |

原 1017 项保留，新增 3 项。唯一 SKIP 仍是已有的历史 T20（Stage3C 已替代）；没有新增或扩大 skip 条件。完整证据为 `outputs/stage4c7_r1/formal.xml`、`formal.txt`。本轮失败集独立运行、正常组合、反序组合和完整回归均无 FAIL/ERROR。

## 变更文件与保护

- 修改：`app/web_deployment.py`、`tests/test_web_observability.py`。
- 新增：本报告；`tools/stage4c7_r1_workers.py`、`stage4c7_r1_profile.py`、`stage4c7_r1_isolation.py`、`stage4c7_r1_spawn_probe.py`、`stage4c7_r1_closure.py`。
- 新证据仅写入 `outputs/stage4c7_r1/` 及 R1 自有临时目录。
- 12 个原暂存内容不变；上述两个 staged 文件仅在工作树产生后续修复差异。没有 git add/reset/restore/commit/push，其他阶段报告、工具、缓存与历史文件保留。

## 凭据与隐私

使用 `tools/stage4c7_r1_closure.py` 实际完成扫描，**凭据与个人目录 0 命中**。扫描范围包括本轮工作树变更、原暂存文件、staged/unstaged diff、本报告与新 R1 证据；还以内存中的环境凭据值做精确匹配，不输出或保存匹配值。新 pytest XML/TXT 的本机用户目录和 XML hostname 元数据已脱敏。没有创建截图、使用真实 Key、发出 API 或公网请求。

证据：`outputs/stage4c7_r1/closure.json`。index 字节 hash、全部 staged entries hash 均与开始时相同；12 项暂存仍保留。没有为了得到零命中而修改原始历史日志。含本机路径的历史 WorkBuddy 原始失败日志与本轮 pytest 自有临时目录属于本地原始材料，保持不公开；不将整个既有 outputs/tmp 宣称为零个人信息，不因隐私扫描删除其他阶段文件。

## 剩余不确定性与状态

- 两轮历史失败自然条件未直接复现；无法追溯当时 OS 调度、资源竞争或单个文件访问的耗时。
- 受控证明了可选版本诊断的等待累积缺陷和 spawn 的未读取 / 已读取区分；不将受控故障注入冒充历史根因或真实数据验证。
- 修复没有改动评分语义，公网部署与 Stage4C 整体验收仍另行进行。本轮公网请求/API 调用均为 0。
- **Status：PASS（本地 Stage4C.7-R1 正式测试门禁恢复）**。该状态不代表历史自然故障的全部环境因素已证明，也不代表 Stage4C 公网整体验收 PASS。
