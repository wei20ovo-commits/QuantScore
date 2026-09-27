# QuantScore Stage 2.6 — Public Deployment

## Status

READY_FOR_USER_DEPLOY。尚无公网 URL，未完成任何云端分析验收。已完成本地部署准备；用户已授权，本机Git已确认目标账号，现创建 https://github.com/wei20ovo-commits/QuantScore ，等待推送及Cloud部署。

## Deployment Audit

2026-09-27 审计：原目录不是 Git 仓库；现已初始化独立 main 分支并暂存发布文件，未创建远程仓库、未推送。当前远程为空。已连接 GitHub 应用范围内搜索 QuantScore 未返回可用仓库，不代表用户所有账号或未授权私有仓库都不存在。发布前必须由用户确认是否已有本项目仓库，避免重复创建。

Python 3.11.0；BaoStock 0.9.4；Streamlit 1.64.0；Plotly 7.1.0。入口 app/web.py 根据文件位置解析项目根目录；运行代码无私人绝对路径，无 localhost API 服务依赖；默认不需要 API Key。相对缓存目录不存在时由原服务创建，无需上传本地 SQLite。

requirements.txt 补充直接使用的 numpy / requests；pyproject.toml 同步 BaoStock、Streamlit、Plotly 与直接依赖。现有 Streamlit 配置无需改变。新增 Linux / Python 3.11 GitHub Actions 测试配置，待推送后实际执行，不能视为已经通过 Linux 验证。

## Release Hygiene

忽略本地依赖、虚拟环境、缓存、pytest临时目录、输出、工作助手文件、原始用户请求、本地 Secrets / 密钥文件和历史UI备份。核心代码、研究规范、全部测试保留。

历史8个归档中存在私人路径文本：原件完整备份在被忽略的 outputs/deployment/private_archive_backup；发布归档仅脱敏路径文本，成员列表不变，config 和 DOCX 每字节与原件相同。tools/upgrade_v12.py 的历史附件路径改为项目相对路径；历史迁移禁用保护未改变。

对暂存文件及嵌套归档进行密钥模式、私人路径、本地缓存与大文件检查，未发现匹配项。此检查不能保证发现所有可能的敏感信息；不打印密钥内容。可重新执行 python tools/deployment_audit.py。

37个评分/Provider/配置文件SHA256保持不变；UI代码和样式未修改。

## Clean Environment Verification

使用独立 .venv-deploy，从公开包源安装根目录 requirements.txt，pip check 通过。只复制 Git 发布文件到 outputs/deployment/clean_checkout，未复制 .deps、本机行情缓存或Token。

该副本实际运行 python -m pytest：438项，437 PASS / 0 FAIL / 1 SKIP，68.70秒。原438项全部保留。唯一SKIP为阶段外自动排名；一条原有Starlette/httpx弃用提示。

在该副本清除当前子进程的代理变量、PYTHONPATH和TUSHARE_TOKEN后，实际执行 python -m app.cli analyze 600519 --json --refresh：600519.SH / 贵州茅台，日期2026-09-24，BaoStock raw/qfq各6086行、基准6479行，cache_hit=false，is_mock=false，规则评分成功。data_status=PARTIAL源于缺少可靠历史涨跌停等字段，不是请求失败。

以上是Windows上的干净环境检查，不是Linux或公网验收。证据：outputs/deployment/stage26-pytest.xml、stage26-clean-real.json、outputs/runtime/stage26_summary.json。运行证据含本地路径，默认不上传。

## User Action Required

### 1. GitHub仓库确认与发布

1. 打开 https://github.com 并登录，检查自己账号的Repositories，确认是否已有此项目。
2. 建议用 GitHub Desktop（https://desktop.github.com/）登录同一账号，选择 File → Add local repository，选中当前 QuantScore 文件夹。
3. 当前发布文件已暂存；填写提交说明 `Prepare QuantScore Stage 2.6 deployment`，点击 Commit to main。不要勾选忽略文件或拖拽整个磁盘目录上传。
4. 如果没有现有仓库：点击 Publish repository，Name填 `QuantScore`；如要公开源码，取消 Keep this code private，再点击 Publish repository。这一步由用户本人确认可公开内容。
5. 如果已有仓库：不要点击创建重复仓库。将现有仓库URL发回，以便核对远程历史后安全接入；不要 force push 或覆盖旧历史。

命令行替代方式（仅在目标为空的新仓库时）：在项目终端配置自己的本地Git署名并提交；将 YOUR_GITHUB_NAME 替换为真实用户名。不要使用密码或Token作为URL的一部分。

```sh
git config user.name "YOUR_GITHUB_NAME"
git config user.email "YOUR_GITHUB_NOREPLY_EMAIL"
git commit -m "Prepare QuantScore Stage 2.6 deployment"
git remote add origin https://github.com/YOUR_GITHUB_NAME/QuantScore.git
git push -u origin main
```

### 2. Streamlit Community Cloud

1. 打开 https://share.streamlit.io/ 并完成登录，按页面要求授权 GitHub 仓库访问。
2. 点击 Create app → Yup, I have an app。
3. Repository：`你的GitHub用户名/QuantScore`（如复用现有项目，填实际仓库路径）。
4. Branch：`main`。
5. Main file path：`app/web.py`。
6. Advanced settings → Python version：`3.11`；Secrets 留空。默认BaoStock不需要Token，不能粘贴本机代理或私人路径。
7. Save，然后点击 Deploy。等待安装完成，复制实际生成的 `https://…streamlit.app/` 地址发回。

官方依据：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy 。Python版本通过Advanced settings选择，不能把本地版本声明当作已设置Cloud运行时。

## Public Acceptance — Pending

收到真实URL后再从外部浏览器检查：首页、Light/Dark切换、600519→贵州茅台、真实日期与BaoStock来源、规则评分、K线和核心判断、390px手机。不能只检查首页。

若云端BaoStock无法连接或出现依赖/权限/超时错误，提供Cloud日志（先移除任何Secrets）。只修复部署兼容问题，不修改评分规则、权重或业务含义。

## Remaining Issues

尚无GitHub远程、Cloud授权或公网URL；云端BaoStock出站连接未验证。Cloud文件系统不保证缓存/冻结快照持久保存，高并发容量未验证。无需开启Stage 3；本轮停在用户部署授权步骤。

## Authorized Deployment Continuation

已通过本机Git凭据向GitHub官方API确认登录账号 wei20ovo-commits（与用户截图一致），并检查账号现有仓库无QuantScore重复项目。随后创建唯一公开仓库 https://github.com/wei20ovo-commits/QuantScore ，origin已配置。首次提交使用该账号的GitHub noreply地址，避免公开本机私人邮箱。另一个已连接的GitHub应用账号不一致，未用于发布。

Cloud请使用现有GitHub仓库部署，不能使用示例模板或GitHub Import入口。固定设置：Repository=wei20ovo-commits/QuantScore；Branch=main；Main file path=app/web.py；Python=3.11；Secrets留空。公网URL仍待实际部署生成。
