# Changelog

## Unreleased

- 增加 `graphgpt.dev/ecosystem/v1alpha1` 框架无关调用契约；
- 增加 `graphgpt ecosystem list/export`、Dify OpenAPI Custom Tool 和 n8n callable
  sub-workflow 导出；
- 插件协议增加 `ecosystem` 能力，第三方框架适配器无需修改核心 IR；
- 导出默认使用 Bearer 认证、不写入密钥，并拒绝路径穿越和覆盖已有资产。
- 增加 `graphgpt.dev/universal/v1alpha1` 通用流程 IR，以及 `formats`、`detect`、`convert`
  命令；
- 首批支持 GraphGPT Workflow、MCP capability snapshot、Agent Skills、LangGraph graph JSON、
  Dify DSL/Custom Tool 与 n8n workflow JSON 转换；
- 每次转换生成机器可读 fidelity 报告，并支持 `--fail-on-lossy` CI 门禁；
- 插件协议增加 `converter` 能力，允许社区添加 Coze、Flowise、CrewAI 等格式适配器。

## 0.8.0 - 2026-08-22

- 增加已安装插件发现、协议验证及 human/JSON 健康检查；
- 增加 `graphgpt plugin init`，生成可独立测试、构建和发布的第三方插件包；
- 增加插件作者指南、生态目录、贡献/治理/安全/行为准则和结构化 Issue/PR 模板；
- 增加 Dependabot 与插件脚手架 CI smoke test，并完善 PyPI 项目元数据。

## 0.7.0 - 2026-08-22

- 语义与跨文件子图诊断增加 YAML SourceMap 文件、行和列；
- SourceMap 保持为非序列化上下文，规范化 IR 不泄露本机路径。

## 0.2.0–0.6.0

- 增加 Command/Send、RunnableConfig/resume、retry/cache 与子图；
- 增加版本化插件协议以及环境变量 Secret 引用和脱敏。

## 0.1.0 - 2026-08-05

- 项目正式命名为 GraphGPT，distribution 名为 `graphgpt-builder`；
- 发布 `graphgpt.dev/v1alpha1` DSL、版本化 IR 和稳定诊断模型；
- 支持原生 LangGraph 节点、边、条件路由、循环、Reducer、interrupt 与内存持久化；
- 增加 LangChain model/agent/ToolNode 适配及 LangSmith/Langfuse 观测入口；
- 增加 CLI、五个模板、`langgraph.json` 项目生成、架构 ADR 和兼容矩阵。
