# QuantScore Stage 2.5 Web 验收

状态：PASS（本地真实Web验收通过，尚未公开部署）。

## 实际验证

- 实际启动：python -m streamlit run app/web.py --server.address 127.0.0.1 --server.port 8501。
- Headless Microsoft Edge通过Playwright打开页面、输入600519、点击“开始分析”；未注入mock或改写响应。
- 页面真实显示贵州茅台 / 600519.SH，数据源baostock，数据日期2026-09-24。
- QuantScore=0、Risk Level=HIGH、Positive Score=10、Risk Penalty=20；正向覆盖率59.0%，风险覆盖率66.7%。这些是本次核心服务返回值，不是预测或推荐。
- 评分状态信息不足，页面明确提示结合覆盖率与UNKNOWN查看；没有隐藏数据限制。
- 主要正向/风险原因、41条全部规则的status/score/max_score/explanation/raw_values与风险penalty可查看。
- 桌面1440×1000、手机390×844：无横向页面溢出；手机指标自动纵向排列。规则列表在手机宽度展开成功，浏览器pageerror为空。
- 已人工查看desktop.png、mobile.png、mobile_rules.png，标题、输入、免责声明、结果与规则文字正常可读。

## 离线回归

实际运行python -m pytest --junitxml=outputs/pytest-results.xml -q：433项，432 PASS / 0 FAIL / 1 SKIP。新增16项Web层测试；原417项全部保留。SKIP仍为既有自动选股排名，不属于本阶段。无新增评分规则或权重变更。

Web测试覆盖初始页不自动联网、输入校验、覆盖率百分比、指标与规则显示、mock拒绝、数据不可用、异常信息保护、重新提交失败清除旧结果。人工夹具只用于离线测试，不作为真实Web证据。

## 文件与部署

app/web.py为Streamlit入口；app/web_backend.py为现有StockAnalysisService的薄适配层。requirements.txt固定streamlit==1.64.0；.streamlit/config.toml保留CORS/XSRF保护，关闭统计；.gitignore保护secrets.toml。README提供本地与Community Cloud部署步骤、Python3.11与入口路径。

未创建或发布远程Git仓库，未取得公网部署地址。Cloud网络可达性、并发容量需要部署后验证。现有核心缓存/快照继续使用，没有新增数据库、账号或用户存储。

## 证据

- outputs/web/stage25_web_smoke.json：真实浏览器验收记录。
- outputs/web/desktop_text.txt：本次页面文字。
- outputs/web/desktop.png、mobile.png、mobile_rules.png：实际页面截图。
- outputs/pytest-results.xml、outputs/test-summary.json：完整测试结果。
- docs/archive/stage2_2_acceptance_baseline.zip：原417项与原评分配置。

完成本阶段后停止，未进入Stage 3。
