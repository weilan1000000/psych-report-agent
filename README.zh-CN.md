# PsychReportAgent

[English README](README.md) · [演示报告 PDF](docs/showcase/junior-high-demo.pdf) · [控制台说明](docs/report_operations_console.md)

PsychReportAgent 是面向儿童与青少年的测评报告生成原型。它把结构化测评分数转为可阅读的图文 PDF，支持按学段组织综合画像、指标解读和成长建议。

公开版提供多智能体流程、可复用写作规则、指标参考卡、合成检索示例、质量检查、人审记录和 PDF 渲染器。真实学生样本、专家材料原文与内部案例库保存在私有仓库。

Windows 用户可先运行 `SETUP_FIRST_TIME.cmd`，然后打开 `OPEN_REPORT_CONSOLE.cmd`。调用 DeepSeek 生成报告需要自行提供 API Key。[输入模板](templates/README.md)里的分数是合成数据。离线演示和测试命令见英文 README。报告用于教育反馈，不提供诊断。
