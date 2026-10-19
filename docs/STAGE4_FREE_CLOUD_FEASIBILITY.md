# QuantScore 免费托管日更：可行性与工程验收

审计日期：2026-10-19。基线：`main @ cc0e13d7d3a866a1a1763f6a5d01422b47e7d0c7`。

## 结论与状态

**总体 PARTIAL。GitHub-hosted 标准 Linux runner 具备分批执行的资源可能性，但尚未证明能稳定完成本项目的83行业真实日更。不能宣布 CLOUD_PASS。**

已实现顺序分批、跨作业状态传递、同交易日续跑、跨日缓存复用、完整结果门禁及调用既有原子发布器的可执行方案。没有安装/启用新工作流，没有替换生产 self-hosted 定时任务，没有 commit/push，没有刷新或改写2026-09-30正式行情。

| 层次 | 结论 | 证据边界 |
|---|---|---|
| 本地工程实现 | LOCAL_PASS | 完整回归1,129 PASS / 0 FAIL / 0 ERROR / 1原有SKIP；离线契约、真实历史缓存传输、同输入回归 |
| 本机真实数据源 | PARTIAL | 日历成功；行业归属20秒预算内超时，立即停止 |
| GitHub-hosted 数据源连通性 | NOT_RUN | 本轮无实际托管 runner 执行 |
| 托管83行业初始化/连续交易日日更 | NOT_RUN | 历史8.35小时不是本次云端测量 |
| 生产日更与Streamlit数据生效 | NOT_DEPLOYED | 需要WorkBuddy发布、托管试运行及公网核验 |

## 现有链路审计

链路为 BaoStock → 真实日历/证券与行业归属 → raw/qfq及指数 → 原有SectorHeat S1–S7 → 行业Heat≥70的全部成分股 → 原有41条规则与候选判定 → 正式发布文件 → Web只读。

现有实现已包含RequestCache、HistoryCache、ScoreMemo、逐对象CheckpointStore、交易日与16:00数据截止判定、不可变generation及最后一步原子current指针更新。本轮直接复用这些模块，没有新增评分算法。Stage3C行业输入仍只使用BaoStock，**没有把AKShare当作可随意替换的行业来源**；单股Provider fallback也未修改。

实际历史83行业记录：`outputs/stage3c/full_market/screening_details.json`，交易日2026-09-30，30,064.172秒，10,329次Provider请求，37次retry；行业阶段25,882.125秒，个股阶段4,182.047秒，78只股票已处理。结果是PARTIAL：40个行业可评分、43个不可评分，不能把这份历史结果当作成功日更的新证据。该文件约11.20 MiB；当前指数manifest和旧行业结果仍是2026-09-30，未生成新的正式current指针。

Stage3C.1的3,248.499 → 871.855 → 235.550秒是三行业固定归档输入对照，不是83行业次日增量实测；不能据此承诺全市场每日几分钟。

### 首次与正常增量的区别

| 数据/计算 | 首次 | 后续交易日 |
|---|---|---|
| 日历、行业归属、证券资料 | 从真实源获取并校验 | 仍需验证新日期/归属，不能沿用旧日期冒充有效 |
| 行业成员raw/qfq，约80自然日窗口 | 下载全部所需窗口 | HistoryCache重取至少覆盖原末日的14自然日重叠区与新数据；价格/复权锚变动则全量重取 |
| 合格行业中的完整个股历史 | 首次可能扩展长历史，按原字段分组请求 | 已有覆盖范围可增量；新入围股票可能再次承担冷初始化成本 |
| Benchmark | 必要完整历史，现有prepare共享 | 按既有历史缓存重叠验证，必要时全量刷新 |
| SectorHeat、B1/B2、41条规则 | 原引擎完整计算 | 新日期/输入改变仍需重算；ScoreMemo只复用精确相同指纹 |
| R7历史冻结输入 | 原始冻结机制 | 跨作业保留score_snapshots，禁止重新生成不同验收输入 |

增量主要减少传输量，不保证请求数等比例下降。若N个有效SH/SZ成分股都需要更新，raw/qfq通常仍需约2N次历史查询，另加日历、归属、指数、长历史扩展及原有有限重试。以约5,000成员作**数量级估算**，仅原有0.3秒串行节流下界已约50分钟；这不是实际总时长，未含网络响应、评分、重试和状态传输。行业是否入围、复权锚修正及当天数据质量均会改变成本。

## 免费托管核验与约束

1. 当前仓库公开。标准GitHub-hosted public runner计算分钟免费，**不代表存储、网络、任意用途或稳定性无限承诺**。[官方计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)、[公开仓库](https://github.com/wei20ovo-commits/QuantScore)。
2. 每作业最长6小时，workflow最长35天；GitHub Free的artifact额度500 MB、repository cache默认10 GB。私有仓库免费分钟2,000/月，不能按当前历史耗时承诺私有仓库免费日更。[官方限制](https://docs.github.com/en/actions/reference/limits)。
3. 标准公开Linux runner列示4 CPU、16 GB RAM、14 GB SSD，每个job为新环境，需要显式跨作业持久化。[Runner规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
4. schedule可能延迟或被丢弃，公开仓库60天无活动可能自动停用，不能视为有SLA的交易日调度器。[触发规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
5. Cache可能被驱逐，7天未访问会删除，默认总量10 GB；提高额度可能产生费用。本方案不提高额度，必须保留拒绝超限与冷启动恢复能力。[缓存规则](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)。
6. Actions用途需要符合项目开发/测试/部署/发布及负载限制，不将其作为按用户请求运行的serverless后端、CDN或无限计算池。大规模长期任务的适用性仍受GitHub政策约束。[附加条款](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions)。
7. BaoStock官方主页/旧wiki在本轮浏览器读取中未给出可核验的数值限流/SLA及行情再分发授权。PyPI维护者页标注SDK为BSD，不等于全部底层市场数据均获无限批量访问和公开再分发许可。没有把“未查到额度”解释为无限使用。[官方维护包](https://pypi.org/project/baostock/0.9.4/)、[主页](https://www.baostock.com/)。
8. AKShare官方说明其接口和相关数据用于学术研究并提示商业风险；本轮不声称其数据许可支持任意公开缓存再分发，也没有在托管环境验证其网络可用性。[项目说明](https://akshare.akfamily.xyz/introduction.html)。

因此，只能认定**有条件的技术可行性**。云端BaoStock可用性、来源使用条件、完整83行业资源/质量以及账户共享存储余量均是正式启用前的门禁，不能通过多开并发任务掩盖。

## 新架构与数据流

```text
手动托管探测（最多5次SDK查询/120秒/不重试）
    ↓ 验证后才允许人工完整pilot
真实交易日判定 → 顺序slice 1 → slice 2 → slice 3 → slice 4
                    ↕              ↕             ↕
             不可变、有限大小、JSON/GZip状态 + 同run artifact交接
             Actions cache仅用于可丢弃的跨run暖启动
    ↓ 全量同日完成 + 所需质量/版本校验 + 安全状态导出
原有publish_market_context → 不可变generation → 原子current.json
    ↓ 另设owner开关，复用现有CI-only普通提交发布工具
GitHub main的正式数据文件 → Streamlit按原读取器校验读取
```

### 执行与可恢复性

- 最多4个**显式顺序**job，不使用并发行业矩阵，不提高Provider访问频率。每job compute最多14,400秒，job总截止285分钟，低于6小时。
- `boundary_reserve_seconds=120`仅为新托管调用启用。在下一行业前预留完整原1800秒object预算，下一股票前预留原300秒预算，再留120秒；不足则在对象边界暂停，而不是开始后人为制造DATA_ERROR。原调用默认0，原Provider重试、240秒Web截止、缓存TTL和规则均不变。
- 暂停进入`operational_pauses`历史，不能作为数据故障压低分数或使完整结果虚假PARTIAL。每批写原CheckpointStore，下一批仍校验日期、完整行业universe、选集、版本、policy和对象hash，不重算已完成对象。
- 先完整扫描行业，再按原业务规则扫描全部合格行业股票；没有Top5、候选改阈值、改变分母或抽样。
- 跨午夜/休市可以继续**已经开始且目标交易日仍相同**的STOPPED checkpoint；不能在下一交易日收盘后把旧checkpoint改名接用。新一天只复用缓存，旧checkpoint隔离保留。
- 初次job可读取同代码/数值环境指纹的最近cache；后续job必须读取前一job同run不可变artifact。缓存被清理时可从空缓存初始化，但不保证仍能在当日预算内完成。作业中途硬终止最多损失当前未导出的slice，不能承诺秒级durability。
- 失败对象不会被自动改为可重试成功；已有完成错误行不自动重算。质量故障会阻止正式发布，避免immutable resume把错误当作成功完成。下一次受控run应保留故障证据并重新取得合法输入。

### 安全状态、聚合与发布

- `cloud_state.py`只传固定SQLite表的JSON行和固定checkpoint/calendar路径；不传原SQLite可执行schema、不用pickle或tar解包，不传日志、secrets或环境变量。
- 最大压缩状态128 MiB、解压2 GiB、单记录48 MiB、100,000记录；超限失败，不静默裁剪历史、不破坏上一bundle。校验完整流hash、schema、代码及依赖/数值运行环境指纹、生产run ID、checkpoint日期与对象hash，先完成独立staging后安装。
- 保留HistoryCache原fetched_at、覆盖区、精确数值、ScoreMemo指纹与R7冻结记录。仅可省略按原TTL已经过期的**exact-query frames**；这类记录本来就无法命中。不会省略增量重叠历史或为缓存重置时间戳。
- 关键状态先上传新artifact，再只删除同一run里刚消费的前一artifact。其他run/历史文件不删。大状态也可写入10GB范围内可驱逐cache；不会把artifact当无限磁盘。
- 由原ScreeningService最终汇总全部行业/股票，仍用原排序和候选逻辑，没有另写score聚合。`publication_gate`拒绝未完成、非live/mock、日期不符、有限选集、操作故障、DATA_ERROR/STALE/INCONSISTENT；原发布器继续独立验证完整数量、版本、输入日期、指数OHLC/hash和隐私。
- DATA_INCOMPLETE仍可被如实记录为不可评分/UNKNOWN，**不新增全局coverage门槛，也不把None变0**。原发布器决定其正式数据契约是否可接受，不能仅因有行数就绕过质量检查。
- 状态导出成功后才可能切换current。损坏/漏项、错日期、输送失败、Provider故障、未收盘或源尚未更新均不得将旧行情标成新日期。Web继续按请求评价日判定DATA_STALE和B1/B2 UNKNOWN。
- 新状态报告仅含实际source SHA（取不到为UNKNOWN）、指纹、日期、slice、safe reason/error type、最后完成阶段、计数、耗时和hash，不写异常原文、凭据或私人路径。缺计数为UNKNOWN。

## 资源实测与预算

| 项目 | 实测/上限 | 含义 |
|---|---:|---|
| 当前market.sqlite3文件 | 565,944,320 bytes，539.73 MiB | 不能假设免费artifact可整库长期保存 |
| 表内frame数量/净payload | 10,097 / 554,789,469 bytes | raw/qfq/指数/元数据等，不是新交易日结果 |
| 原样无损JSON/GZip导出 | 64,910,482 bytes，61.90 MiB；137.7682秒 | 本机真实缓存测量，没有行情刷新 |
| 解压恢复并逐行hash比对 | 152.2119秒 | 10,097 frames与8条R7冻结记录完全一致 |
| 最初48 MiB传输上限 | 被真实缓存拒绝 | 保留失败证据；之后采用128 MiB预算 |
| 每slice状态上限 | 128 MiB压缩/2 GiB展开 | 不是完整83行业状态必然够用的证明 |
| compute / job截止 | 4小时 / 285分钟 | 共4批，最多16小时compute，不自动加批或延长 |

最多4批每天产生512 MiB cache写入，若7个日历日都用到最坏上限约3.5 GiB，不含其他workflow缓存与服务压缩开销；按实际61.9 MiB例约1.7 GiB/7天。**这是容量估算，不是配额保证**，旧cache访问可延长留存，需监测驱逐与账户余量。

删除前一handoff后，同run通常只留最后一份状态；上传切换瞬间两份，加上一份前一run未过期的最终状态，保守约384 MiB，另加小型状态artifact和账户其他artifact。500 MB不是本项目独占，剩余不足应失败而非增加收费额度。GitHub保留清理延迟也可能增加峰值。

本地导出+恢复约290秒，4批可能增加数十分钟setup/IO/网络搬运；源数据/完整代际还可能增长。当前长期HistoryCache/ScoreMemo数据库各仅12 KiB，**不能把这次62 MiB大小误说成已验证的全83行业暖历史容量**。超限会BLOCKED，必须由真实pilot测量后再决定能否启用。

假设每月22交易日、每次仍用历史8.35小时数量级，约11,023 runner分钟/月（未含分批overhead），远超私有Free的2,000分钟。公开标准runner无分钟费用也不构成延迟或可用性保证。没有采购、扩容或注册任何付费服务。

## 本轮真实网络与数据新鲜度

一次初探：日历46行成功2.843秒；探测脚本误调用Provider不存在的行业便捷方法，记录AttributeError后即停。该脚本缺陷已改为现有`_call('query_stock_industry')`，并增加成功/失败SDK契约测试。

唯一修正后的复测：日历46行成功3.047秒，实际目标最近收盘交易日2026-10-16；行业归属在20秒单次预算超时，实测21.312秒（含Worker清理），总24.406秒，reason_code=PROVIDER_TIMEOUT。没有继续raw/qfq/指数请求。

两轮合计**3次逻辑SDK查询、0 retry**，包含失败即停；计数不是TCP包/登录/分页总次数。未改变全局代理、未替换端点、未绕过访问限制。这证明当前本机一次行业响应不满足20秒探测预算，**不能证明GitHub IP被限制、BaoStock全站不可用或正常生产60秒预算也一定失败**。本轮不再做市场网络重试。

真实托管probe为NOT_RUN，AKShare托管连通性未测试，83行业真实更新未运行，行业/指数正式交易日期仍为2026-09-30。局部日历返回不等于市场更新成功。

## 本地测试与安全审计

最终正式`.venv`完整回归：**1,130项，1,129 PASS / 0 FAIL / 0 ERROR / 1 SKIP，398.42秒**。SKIP为原有历史T20验收，不增加SKIP；另有一条第三方Starlette/httpx弃用警告。本轮新增45项数据任务测试。原始执行证据位于`outputs/free_cloud/pytest_full.xml`，脱敏汇总为`outputs/free_cloud/acceptance.json`。测试使用人工契约或已有归档时明确属于离线证据，不冒充本轮真实行情。

安全与保护门禁：本轮交付、全部当前Git改动/暂存/未跟踪文本及选定脱敏JSON中，凭据与私人路径扫描0命中；26个原有工作区文件和37个冻结规则/配置及生产工作流文件逐文件hash保持一致，暂存区与HEAD保持原样。无commit/push、无新生产定时任务。大状态导出另有逐内容扫描及恢复校验，不将本地JUnit、原始数据库或历史日志当作公共交付。

专项覆盖：过期exact-cache裁剪不重置TTL；历史/score memo/R7精确往返；大小/截断/流hash/路径穿越/私密内容/重复对象拒绝；同日pause-transport-resume确定性；跨日、未收盘、休市；导出失败/不完整/数据错误不得切换正式指针；原发布器再次校验；41条规则同输入结果和QuantScore/Risk/B1/B2/候选语义一致。

本轮未接收、读取或使用AI API Key。只允许脱敏状态JSON与经导出扫描的市场状态进入新的公共artifact路径。历史ignored日志、失败JUnit和本机数据不自动发布，不能声明整个磁盘所有截图/二进制均经过OCR或无任何私人信息。

### 旧UI测试门禁的复现与隔离

首轮完整回归为1,127项：1,122 PASS / 4 FAIL / 0 ERROR / 1原有SKIP，536.02秒。四个失败全部为原Streamlit AppTest默认3秒超时，不是行情、评分或新状态测试失败。

保留失败证据后，在原预算下单独组合复测：1 FAIL / 3 PASS，37.22秒；首个页面冷启动仍超时。原有采样插件组合：47 PASS / 1 FAIL，63.99秒，同一首次页面超时。因采样可能增加耗时，没有将其当作唯一证据。

另一次**仅诊断、不计正式门禁**的15秒观察窗口记录首次AppTest为5.3866秒；`app/web.py:98`首次Streamlit样式渲染2.9165秒，部署身份读取0.9646秒，首页0.9646秒；同进程后续切换1.3266–1.7869秒。此观察不涉及真实网络或规则变更，也没有用延长后的单次probe冒充正式通过。

因此只在`tests/test_ui_final.py`一处实例和`tests/test_web_explanation.py`共同AppTest构造处设`default_timeout=8`：基于已测5.39秒冷初始化提供有限框架余量，保留全部断言、已有20秒分析预算及所有测试。没有全局忽略timeout、添加SKIP、修改生产Web或Provider截止。新增数据任务测试和其预算不因此放宽。最终完整回归使用这两处正式测试修复，不加载诊断插件。

## WorkBuddy正式交接文件

仅本轮正式文件，勿混入原工作区已有README/Stage4C报告/Stage26或旧工具修改：

- `app/cloud_state.py`
- `app/cloud_update.py`
- `app/screening/service.py`（仅新增可选对象边界暂停）
- `tools/cloud_market_update.py`
- `tools/cloud_provider_probe.py`
- `tools/cloud_update_acceptance.py`
- `tests/test_cloud_update.py`
- `tests/test_ui_final.py`（只调整有复现/计时依据的测试框架冷启动预算）
- `tests/test_web_explanation.py`（同上；AI功能和断言不变）
- `deployment/github-hosted/provider-probe.yml.example`
- `deployment/github-hosted/market-slice.yml.example`
- `deployment/github-hosted/market-update.yml.example`
- 本报告。

运行证据均保留本地`outputs/free_cloud/`，不要求把原SQLite、GZip状态、完整pytest日志、缓存或历史证据上传Git。原生产`.github/workflows/market-update.yml`保持原样。

## 最少外部操作与启用顺序

1. WorkBuddy审阅并发布上述正式代码文件。本轮Codex不commit/push。确认公开仓库、标准Ubuntu runner，Actions可执行且没有新增付费额度；保留10GB cache默认上限并设置阻止超额支出策略，核对共享artifact余量。确认来源使用及公开数据缓存条件。
2. 先只将`provider-probe.yml.example`安装为`.github/workflows/hosted-provider-probe.yml`，手动运行一次。读取safe JSON：hosted=true、5个查询成功、600519 raw/qfq同日、成交量换手及上证指数通过验证。失败即停止，不开后续扫描，不需要API Key。
3. 托管probe通过后，再安装另外两个模板为`.github/workflows/hosted-market-slice.yml`与`hosted-market-update.yml`。设置`QUANTSCORE_HOSTED_PILOT_VERIFIED=true`；**不要设置定时开关或发布开关**。手动完整83行业pilot，publish=false；确认四批上限内完成、跨job恢复、全部要求质量通过、实际状态大小/IO/内存/磁盘、原子代际合法。不要把子集成功记为全量成功。
4. 再做下一个真实交易日增量pilot（仍publish=false），区分新日请求和同日warm缓存，测量实际每日吞吐和总额度。若不满足16小时总预算/市场窗口/状态上限/质量要求，保留PARTIAL/BLOCKED，不启用日更。
5. 全部通过后由owner确认repository写权限/分支保护允许现有CI-only普通快照发布，设置`QUANTSCORE_HOSTED_PUBLICATION_VERIFIED=true`并手动publish=true。正式数据提交成功后核对Streamlit实际运行SHA、generation、日期、600519及B1/B2一致性。GitHub改动通常会在Cloud自动生效，但必须现场验证，不能靠workflow绿色推断。[Streamlit官方更新说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app#update-your-app)。
6. 最后才设置`QUANTSCORE_HOSTED_UPDATES_ENABLED=true`开启17:23上海时间的候选定时流程，并确保原self-hosted开关仍关闭，避免双重任务。市场闭市日由真实日历跳过；查看每日safe status而非要求家人安装软件或让个人电脑常开。

本轮不需要新AI Key、个人电脑常开或新增付费账号。权限集中由WorkBuddy/owner处理，家人继续只用已有浏览器网站。

## 无法稳定免费运行时的替代与剩余限制

不把Streamlit Cloud当作常驻调度机：官方说明会休眠且有资源限制；用户浏览不应触发83行业扫描。GitHub Pages也不是Python后台。没有证据证明任意其他免费平台能改善本数据源网络、批量许可或每日总吞吐，不能把换平台当已解决。

最低成本的安全退路是保留本套手动托管更新入口，诚实展示最近成功日期/STALE；如获得已有合规常在线资源，可直接使用原self-hosted生产工作流而不更改评分。若必须承诺每日完成、而免费pilot持续无法通过，才评估有稳定出站网络与持久盘的付费执行环境或合法上游完整快照，费用与权限另行确认。本轮未购买或接入。

Actions定时不是SLA；cache不是备份；单sector超过原1800秒预算、数据缺失或版本/数值依赖变化均会阻止发布。四批不足不会自动追加作业或使用另一批IP加压数据源。`CLOUD_PASS`必须有实际托管全量与跨交易日证据，当前不满足。
