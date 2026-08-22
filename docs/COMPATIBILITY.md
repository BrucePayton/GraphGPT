# 兼容矩阵

验证日期：2026-08-22。

| GraphGPT | Python | LangGraph | LangChain | LangSmith | DSL |
|---|---|---|---|---|---|
| 0.8.x | 3.11–3.13 | >=1.0,<2.0 | >=1.0,<2.0 | >=0.4,<1.0 | v1alpha1 |

依赖元数据允许 `langgraph>=1.0,<2.0` 与 `langchain>=1.0,<2.0`，精确可复现组合记录在
`uv.lock`。CI 覆盖 Python 3.11 和 3.13。Langfuse 3.x 是可选依赖，通过标准 LangChain
callback 接入，不改变编译结果。插件协议独立版本为 `graphgpt.dev/plugin/v1alpha1`。

工具链验证组合为 `langgraph-cli==0.4.31`、`langgraph-api==0.12.0` 与
`langgraph-runtime-inmem==0.32.0`。生成的 Branch 项目已通过 `langgraph dev` 启动、`/ok`
健康检查、assistant 注册，并通过 `/runs/wait` 得到 `{"approved": true, "result": "accepted"}`。

GraphGPT 仅从集中适配器使用 LangGraph 公共 API；升级后必须通过循环、条件路由、messages
Reducer、interrupt/checkpointer 和模板行为测试。
