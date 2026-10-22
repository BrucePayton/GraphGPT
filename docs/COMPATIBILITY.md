# 兼容矩阵

验证日期：2026-10-21。

| GraphGPT | Python | LangGraph | LangChain | LangSmith | DSL |
|---|---|---|---|---|---|
| 0.10.x | 3.11–3.13 | >=1.2.16,<2.0 | >=1.4.6,<2.0 | >=0.4,<1.0 | v1alpha1 |

最低兼容组合为 `langgraph==1.2.16`、`langchain==1.4.6`、
`langchain-core==1.6.12` 与 `langgraph-cli==0.4.36`。`uv.lock` 当前记录的已验证组合为
`langgraph==1.2.16`、`langchain==1.4.7`、`langchain-core==1.6.13` 与
`langgraph-cli==0.4.37`。CI 覆盖 Python 3.11 和 3.13，并另跑最低兼容组合。

生成的 Branch 项目通过 `langgraph validate`、`langgraph dev` 启动和 `/ok` 健康检查。
Runtime Conformance Suite 对比手写原生图与生成图，覆盖首次执行、并行状态合并、中断恢复、
并行恢复、子图恢复和历史分支六类语义。

GraphGPT 仅从集中适配器使用 LangGraph 公共 API。LangChain HITL 的 `per_call` 模式需要
1.4.6 或更高版本；审批恢复必须启用 checkpointer。Langfuse 3.x 是可选依赖，插件协议独立
版本为 `graphgpt.dev/plugin/v1alpha1`。

首方 MCP 运行时适配通过 `graphgpt-builder[mcp]` 安装，使用
`langchain.mcp.MCPAdapter`。该命名空间当前仍是 LangChain beta API；远程 HTTP、stdio
和进程内服务由 FastMCP 传输层处理，GraphGPT 负责工具发现、名称冲突检查与 Registry 注册。
