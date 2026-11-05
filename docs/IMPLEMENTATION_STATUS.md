# 实现状态与证据索引

验证日期：2026-11-05。状态含义：**实现**表示代码存在，**验证**表示自动化测试通过，
**E2E** 表示生成工程已通过外部工具链。提交列记录首次引入该能力的主线提交；0.10.0
新增项目在发布提交与标签落地后固定。

| 能力 | 状态 | 代码证据 | 测试证据 | 首次提交 |
|---|---|---|---|---|
| 版本化 DSL / Graph IR | 实现、验证 | `dsl/models.py`, `domain/ir.py`, `application/transform.py` | `test_loader_and_validation.py`, `test_runtime_security.py` | `28376d5`, `3606fca` |
| 语义校验与 SourceMap | 实现、验证 | `application/validate.py`, `domain/diagnostics.py` | `test_loader_and_validation.py` | `2681a79`, `f917afa` |
| 原生 LangGraph 编译 | 实现、验证 | `adapters/langgraph_compiler.py` | `test_compiler.py`, `test_runtime_conformance.py` | `28376d5` |
| Command / Send | 实现、验证 | `domain/ir.py`, `adapters/langgraph_compiler.py` | `test_compiler.py` | `38cc133` |
| Checkpoint / interrupt / resume | 实现、验证 | `domain/ir.py`, `registry.py`, `runtime.py` | `test_compiler.py`, `test_runtime_conformance.py` | `dfc3259`, `3606fca` |
| 子图及持久化策略 | 实现、验证 | `application/subgraphs.py`, `adapters/subgraph_compiler.py` | `test_subgraphs.py`, `test_runtime_conformance.py` | `b82ae1e` |
| 节点注册表 / 插件 | 实现、验证 | `registry.py`, `plugin.py` | `test_registry.py`, `test_plugins.py` | `a2a4ba5`, `31e82fd` |
| 严格 State / Command 边界 | 实现、验证 | `runtime.py`, `api.py`, `cli.py` | `test_runtime_security.py` | `3606fca` |
| LangChain Model / Agent / ToolNode | 实现、验证 | `registry.py` | `test_registry.py`, `test_runtime_security.py` | `28376d5`, `3606fca` |
| LangChain HITL batched / per_call | 实现、验证 | `dsl/models.py`, `domain/ir.py`, `registry.py` | `test_runtime_security.py` | `3606fca` |
| MCP | 转换与官方运行时适配均已验证 | `adapters/converters.py`, `mcp.py`, `registry.py` | `test_conversion.py`, `test_mcp.py` | `992f5a1`, 0.10.0 待发布 |
| Langfuse / Trace Metadata | 本地真实服务 E2E；LangSmith 保留环境变量兼容 | `observability.py`, `tracing.py` | `test_more_contracts.py`, `test_tracing.py`, `scripts/verify_local_langfuse.py` | 0.11.0 |
| LangGraph CLI 生成工程 | E2E | `project.py`, templates, `langgraph.json` | `test_project.py`, `test_langgraph_cli_integration.py` | `ee1a6c8` |
| Dify / n8n 导出 | 实现、验证 | `adapters/ecosystems.py` | `test_ecosystems.py` | `992f5a1` |
| Typed Decision IR | 实现、验证；远程模型适配由应用提供 | `decisions.py`, `dsl/models.py` | `test_decisions_actions.py` | 0.11.0 |
| Action Registry / 版本 / Hook | 实现、验证 | `actions.py`, `registry.py` | `test_decisions_actions.py` | 0.11.0 |
| 异常恢复 / Delta snapshot policy | 实现、验证 | `adapters/langgraph_compiler.py` | `test_runtime_recovery.py` | 0.11.0 |
| Async Task 生命周期 | 进程内实现、验证；非持久化调度服务 | `tasks.py` | `test_tasks_evaluation.py` | 0.11.0 |
| Evaluation Manifest / Langfuse Observations v2 查询 | SDK HTTP 模拟 + 本地真实 v4 服务 E2E | `evaluation.py` | `test_langfuse_evaluation.py`, `scripts/verify_local_langfuse.py` | 0.11.0 |
| Model async / config / stream events | 实现、验证 | `registry.py` | `test_model_runtime.py` | 0.11.0 |

## 可重复验证

```bash
uv sync --extra dev --extra langchain --extra mcp --extra cli --extra langfuse --locked
uv run ruff check .
uv run mypy
uv run pytest --cov=graphgpt --cov-report=term-missing --cov-fail-under=90
uv build
```

CI 另外在最低兼容版本上运行 Runtime Conformance、安全契约与 LangGraph CLI smoke test。
本地 Langfuse 已验证真实写入、查询、执行与类型评估；Cloud、业务模型质量和自定义审批评估
未验证，不混入离线 CI。详见 [本地接入](LOCAL_LANGFUSE.md) 与 [周报审计](ECOSYSTEM_AUDIT.md)。

Compiler 按项目 ADR 在内存中直接构造原生 `StateGraph`；生成项目中的 `graph.py` 是可审查的
薄加载器，而不是展开后的 Python 图装配代码。这一选择避免生成并执行源码，不影响原生对象、
CLI 或 Studio 兼容性。
