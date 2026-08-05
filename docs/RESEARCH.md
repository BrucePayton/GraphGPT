# 相关项目调研与取舍

调研日期：2026-08-05。星数会变化，仅用于判断社区采用度，不作为复制实现的依据。

| 项目 | 调研时信号 | 可借鉴点 | GraphGPT 的差异化取舍 |
|---|---:|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | 约 37.4k stars | 原生状态图、持久化、interrupt、stream | 只使用公共 API，不复制 runtime |
| [LangGraph Builder](https://github.com/langchain-ai/langgraph-builder) | 236 stars，已归档 | Canvas、条件边和循环的编辑体验 | v0.1 先稳定 IR/Schema，为未来 UI 提供边界 |
| [langgraph-gen-py](https://github.com/langchain-ai/langgraph-gen-py) | 110 stars | YAML 到 Python/TS stub 的快速生成 | 运行时直接构图为主，避免生成代码成为事实 runtime |
| [Yagra](https://github.com/shogo-hs/Yagra) | 活跃、265 commits | 注册表、TypedDict、Send、子图、模板、Golden Test | 增加版本化 IR、统一诊断和严格端口边界；避免 Litellm 等成为核心依赖 |
| [retrieval-agent-template](https://github.com/langchain-ai/retrieval-agent-template) | LangChain 官方模板 | `src/`、测试、`langgraph.json` 的可部署项目形态 | `graphgpt init` 直接生成同类标准结构 |

LangGraph Builder 在 2026-02-24 被归档，因此 GraphGPT 不依赖其前端或生成器。Yagra 是当前
最接近的声明式竞品；GraphGPT v0.1 刻意保持更小的核心，并把 DSL、IR、绑定、编译和观测
分离，降低后续兼容 LangGraph 2.x、TypeScript 后端或 Web 编辑器时的迁移成本。

## 官方生态约束

- [`langgraph.json` 应用结构](https://docs.langchain.com/langsmith/application-structure)：
  生成 `dependencies`、`graphs`、`env`，graph 指向已编译对象；
- [LangGraph CLI](https://docs.langchain.com/langsmith/cli)：`graphgpt dev` 仅转交
  `langgraph dev -c ...`，不实现第二个服务器；
- [Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)：编译器使用
  `StateGraph.add_node/add_edge/add_conditional_edges/compile`；
- [Langfuse integration](https://docs.langchain.com/oss/python/integrations/providers/langfuse)：
  在调用配置中传入 callback，不侵入节点与 IR。

