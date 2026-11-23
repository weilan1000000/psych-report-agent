# 本地报告生成台

## 推荐的一次性安装

如果项目来自同事发送的压缩包，首次使用应双击 `SETUP_FIRST_TIME.cmd`，而不是
直接运行启动按钮。它会检查并安装 Python、Node.js、Python/Node 项目依赖和
Playwright Chromium，然后执行离线验证并创建桌面入口。安装日志位于
`output/setup/setup.log`。

必须先在 ZIP 文件上右键选择“全部解压”，再进入解压后的普通文件夹运行安装器。
不能在资源管理器的 ZIP 预览窗口中直接双击 `.cmd`；否则 Windows 只会临时取出
单个命令文件，安装器找不到同级的 `scripts/`、`report_app/` 和其他运行资料。

开发者已经配置好环境时，可以只运行 `INSTALL_REPORT_CONSOLE.cmd` 创建快捷方式。

双击根目录的 `INSTALL_REPORT_CONSOLE.cmd`。它会：

1. 在桌面创建 `Psych Report Console` 快捷方式；
2. 设置为登录 Windows 后静默启动本地服务；
3. 立即启动服务。

安装后可收藏并直接打开：

```text
http://127.0.0.1:8765
```

平时不再需要进入项目文件夹。桌面快捷方式也会自动检测服务，未启动时先静默
启动再打开页面。服务只监听本机地址，其他电脑无法通过该地址访问。

如不希望服务随登录启动，可在 PowerShell 中运行安装脚本时加
`-SkipAutoStart`，或删除 Windows 启动文件夹中的 `Psych Report Console Service`
快捷方式。手动停止可双击 `STOP_REPORT_CONSOLE.cmd`。

## 用途

`report_app` 是面向内部同事的本地操作界面。它只封装现有正式报告流水线，
不复制 TextAgent、CheckerAgent 或 PDF renderer 的业务逻辑。

## 启动

双击项目根目录的 `OPEN_REPORT_CONSOLE.cmd`（旧的
`START_REPORT_CONSOLE.cmd` 仍兼容），或运行：

```powershell
cd D:\Agent1
python -m report_app.server
```

浏览器访问 `http://127.0.0.1:8765`。

开发者可在服务启动后运行独立的界面检查：

```powershell
npm run app:check-ui
```

该命令使用独立的无头 Chromium 检查桌面、平板和手机宽度，并将截图写入
`output/report_app_ui_checks/`。它不依赖 Codex 内嵌浏览器。

## 操作流程

1. 选择小学版、初中版或高中版。
2. 填写本次使用的 DeepSeek API Key。
3. 多选被试 JSON 文件。
4. 按需调整改写轮次、目标质量分和审核稿选项。
5. 点击“开始批量生成”，等待队列逐份完成。
6. 在结果列打开 PDF、`final_report.json` 或 `final_check.json`。

## 待复核报告与反馈窗口

当状态显示“待复核”时，结果列会列出质量分、主要问题和建议动作。点击“处理反馈”
后，可逐条查看 Checker 的问题、当前原文、检查依据、期望结果和自动修订方向，并选择：

| 决定 | 何时使用 | 当前系统行为 |
|---|---|---|
| 确认问题，等待修正 | Checker 判断正确，但尚未处理 | 记录为未解决问题 |
| Checker 误报 | 原文符合要求，规则判断错误 | 记录为已解决，供后续校正规则 |
| 已人工改写 | 审核者已经给出替换文字 | 保存替换文字并记录为已解决 |
| 请求局部重生成 | 需要 Agent 只改指定段落 | 记录为待执行请求，当前版本不会自动发起新 API 调用 |

反馈保存在：

```text
output/report_app/<job-id>/human_feedback.jsonl
```

API Key 会从审核说明、替换文字和审核者字段中脱敏。反馈不会直接进入 Skills、RAG 或
优秀案例库；应由负责人定期汇总，经过专家确认、匿名化、去重和版本化后再蒸馏。这能
让真实使用反馈成为训练材料，同时避免个人临时判断直接改变生成规则。

## 版本覆盖规则

界面选择是本次任务的最高优先级。服务端会在保存输入副本时写入：

- `school_stage`
- `writing_variant`
- `respondent_profile.age_group`
- `audience`

因此旧 JSON 中残留的报告标题不会覆盖界面选择。原始文件本身不会被修改。

小学版固定面向家长，初中版固定面向学生本人。它们共享指标定义、常模、安全边界和
Checker，但分别加载小学家长语气或初中学生语气、成长建议和插图。不要在同一份任务中
混用两个版本的提示词；需要另一版本时重新选择版本并生成。

## 隐私与密钥

- 服务只监听 `127.0.0.1`，不向局域网开放。
- API Key 仅存在于当前 HTTP 请求、工作线程和子进程环境变量中。
- API Key 不写入输入副本、日志、输出 JSON 或项目配置。
- 运行日志会主动清除 `sk-...` 形式的密钥。
- `output/report_app/` 包含被试输入副本和报告产物，已被 `.gitignore` 排除。

## 批处理策略

同一批次默认顺序执行，避免同时请求 DeepSeek 导致限流或连接不稳定。单份报告
失败不会阻断后续文件。页面状态包括：等待中、生成中、已通过、待复核和失败。

## 输出目录

```text
output/report_app/<job-id>/
  inputs/                         # 注入学段后的本次输入副本
  human_feedback.jsonl           # 追加写入的人工复核记录（存在反馈时生成）
  reports/<sample>/
    final_report.json
    final_check.json
    retrieval_trace.json
    run_summary.json
    pdf/
```

## 服务化边界

当前控制台适合可信内部电脑使用，不等同于公网 SaaS。后续部署到服务器时必须增加
登录鉴权、任务数据库、对象存储、密钥管理、访问审计、并发控制和数据保留策略；
报告生成本身仍应调用同一正式流水线。

## 开发者验证

提交生成流程或反馈窗口修改前，至少运行：

```powershell
npm test
npm run check:ui
```

需要验证新状态图时，再分别以 `legacy` 和 `langgraph` 运行同一组脱敏样本，并比较
状态、轮次、最终稿及失败语义。`tests/test_graph_parity.py` 已覆盖主要控制流，但不能
替代真实 DeepSeek 样本回归。
