# RMUC/UL 2027 答疑更新

**最新报告** [2026-11-24 答疑报告](reports/2026-11-24.md) <!-- rmqa-latest-report -->

从轻流共享视图获取 RoboMaster 规则答疑，与上次发布的快照比较，再通过阿里云百炼的 `deepseek-v4.1-flash` 生成 Markdown 报告。报告按变化类型分组，包含模型生成的摘要和关键词，以及脚本从快照引用的提问和官方反馈原文。无效答疑集中列在报告末尾。

答疑数据来自公开的官方共享视图。规则答复以官方原文为准。[RoboMaster27 官方答疑（轻流）](https://qingflow.com/appView/g79clgn1kk02/shareView/g79clh9dkk02?exWsId=1SdM5_PB-NwUtnyPn2b8)

## 搭建 Python 环境

以下命令在项目根目录执行。GitHub Actions 使用 Python 3.12，本地示例使用 Windows PowerShell 7。

```powershell
python -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
```

命令直接使用虚拟环境中的 Python。导出脚本依赖 `requests`，摘要脚本使用 OpenAI Python SDK 调用百炼兼容接口。

## 本地生成报告

在同一个 PowerShell 窗口依次执行。导出时需要能访问 `https://qingflow.com`。

```powershell
New-Item -ItemType Directory -Path out -Force | Out-Null
& $python -X utf8 scripts/export_rmqa.py
if ($LASTEXITCODE -ne 0) { throw '答疑导出失败' }

& $python -X utf8 scripts/prepare_rmqa.py
if ($LASTEXITCODE -ne 0) { throw '快照校验或比对失败' }
```

导出结果保存在 `out/rmqa_2027_clean.json`。比对脚本读取 [发布基线](data/rmqa_2027_published.json)，按编号识别新增答疑、新增反馈、官方反馈修订和反馈清空，生成 `out/changes.json` 和 `out/model_input.txt`。空基线会将当前快照中的所有条目归为新增。如果本次快照缺少基线中的答疑，脚本会列出缺失记录并停止后续流程。

有变更时，在百炼控制台创建模型调用 API Key，通过当前会话的环境变量传入。

```powershell
$env:DASHSCOPE_API_KEY = Read-Host '请输入阿里云百炼 API Key' -MaskInput
# 如需指定地域或业务空间，将下一行替换为控制台提供的 OpenAI 兼容 Base URL。
# $env:DASHSCOPE_BASE_URL = 'https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
& $python -X utf8 scripts/summarize_rmqa.py
if ($LASTEXITCODE -ne 0) { throw '报告生成失败' }
```

摘要脚本默认使用北京公共接入地址。使用其他地域或业务空间专属地址时，`DASHSCOPE_BASE_URL` 应与 Key 匹配。成功后生成 `out/summary.json` 和按北京时间命名的 `out/YYYY-MM-DD.md`。重跑时可复用 `out/deepseek-cache/` 中已校验的批次。无变更时，本地摘要脚本会跳过模型调用。

如需先检查请求内容，运行以下命令生成 `out/deepseek_requests.json`。预览无需 API Key。

```powershell
& $python -X utf8 scripts/summarize_rmqa.py --export-requests
```

提示词与关键词规则在 [model_input_template.txt](model_input_template.txt)，报告排版在 [reports/report_template.md](reports/report_template.md)。

## GitHub Actions

[导出并总结 RoboMaster 答疑](.github/workflows/rmqa-export.yml) 每周一北京时间 08:00 运行，也可在 **Actions → 导出并总结 RoboMaster 答疑 → Run workflow** 手动触发。首次运行前，在仓库设置中配置：

- **Settings → Secrets and variables → Actions → Secrets** 添加 `DASHSCOPE_API_KEY`。
- 使用其他地域或业务空间专属地址时，在同一页面的 **Variables** 添加 `DASHSCOPE_BASE_URL`。
- **Settings → Actions → General → Workflow permissions** 启用 **Allow GitHub Actions to create and approve pull requests**。工作流使用自带的 `GITHUB_TOKEN`，写权限只授予创建 PR 的作业。

运行完成后，在对应运行的 **Artifacts** 中下载：

| 产物 | 内容 |
| --- | --- |
| `rmqa_2027_clean.json` | 本轮导出的完整快照，作为单文件上传 |
| `rmqa-report` | 包含原始 `changes.json` 和日期报告 `YYYY-MM-DD.md` 的 ZIP |

无变更时，工作流仍会上传差异文件和注明「本次没有答疑变更」的报告，跳过模型调用和 PR。

## 审核与发布

默认分支运行成功且有变更时，工作流会通过 `automation/rmqa-publication` 创建或更新待审核 PR。合并 PR 会一并发布本轮报告、更新发布基线和 README 顶部的最新报告链接。若运行期间发布基线已经被更新，请基于新基线重新运行。

[发布答疑报告到飞书](.github/workflows/feishu-upload.yml) 在 PR 合并到默认分支后运行。自动生成和手动创建的 PR 使用相同规则。工作流读取合并提交中新增、修改或重命名后的报告，逐份创建飞书云文档并向配置的群聊发送链接。手动提交时，请将非空 UTF-8 Markdown 放在 `reports/YYYY-MM-DD.md`，同一天的多份报告可以使用 `reports/YYYY-MM-DD-数字.md`。

在仓库的 **Settings → Secrets and variables → Actions** 中配置以下值。

- **Secrets** 中添加 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_FOLDER_TOKEN` 和 `FEISHU_ADMIN_OPEN_ID`。
- **Variables** 中添加 `DOC_DOMAIN`，填写飞书文档域名，例如 `https://example.feishu.cn`。

机器人会分页获取自己加入的群聊，为每个群授予报告阅读权限后发送通知。飞书应用需开通获取群列表的权限。机器人没有加入任何群时，仍会创建云文档。
