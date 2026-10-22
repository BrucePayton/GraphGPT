# 实现状态与证据索引

验证日期：2026-10-21。状态含义：**实现**表示代码存在，**验证**表示自动化测试通过，
**E2E** 表示生成工程已通过外部工具链。提交列记录首次引入该能力的主线提交；0.9.0 项目记录
在发布提交与 `v0.9.0` 标签落地后固定。

| 能力 | 状态 | 代码证据 | 测试证据 | 首次提交 |
|---|---|---|---|---|
| 版本化 DSL / Graph IR | 实现、验证 | `dsl/models.py`, `domain/ir.py`, `application/transform.py` | `test_loader_and_validation.py`, `test_runtime_security.py` | `28376d5`, 0.9.0 待发布 |
| 语义校验与 SourceMap | 实现、验证 | `application/validate.py`, `domain/diagnostics.py` | `test_loader_and_validation.py` | `2681a79`, `f917afa` |
| 原生 LangGraph 编译 | 实现、验证 | `adapters/langgraph_compiler.py` | `test_compiler.py`, `test_runtime_conformance.py` | `28376d5` |
| Command / Send | 实现、验证 | `domain/ir.py`, `adapters/langgraph_compiler.py` | `test_compiler.py` | `38cc133` |
| Checkpoint / interrupt / resume | 实现、验证 | `domain/ir.py`, `registry.py`, `runtime.py` | `test_compiler.py`, `test_runtime_conformance.py` | `dfc3259`, 0.9.0 待发布 |
| 子图及持久化策略 | 实现、验证 | `application/subgraphs.py`, `adapters/subgraph_compiler.py` | `test_subgraphs.py`, `test_runtime_conformance.py` | `b82ae1e` |
| 节点注册表 / 插件 | 实现、验证 | `registry.py`, `plugin.py` | `test_registry.py`, `test_plugins.py` | `a2a4ba5`, `31e82fd` |
| 严格 State / Command 边界 | 实现、验证 | `runtime.py`, `api.py`, `cli.py` | `test_runtime_security.py` | 0.9.0 待发布 |
| LangChain Model / Agent / ToolNode | 实现、验证 | `registry.py` | `test_registry.py`, `test_runtime_security.py` | `28376d5`, 0.9.0 待发布 |
| LangChain HITL batched / per_call | 实现、验证 | `dsl/models.py`, `domain/ir.py`, `registry.py` | `test_runtime_security.py` | 0.9.0 待发布 |
| MCP | 转换契约已验证；运行时适配未实现 | `adapters/converters.py` | `test_conversion.py` | `992f5a1` |
| LangSmith | Callback 接入已验证；远程 Trace 未验证 | `observability.py` | `test_more_contracts.py` | `28376d5` |
| LangGraph CLI 生成工程 | E2E | `project.py`, templates, `langgraph.json` | `test_project.py`, `test_langgraph_cli_integration.py` | `ee1a6c8` |
| Dify / n8n 导出 | 实现、验证 | `adapters/ecosystems.py` | `test_ecosystems.py` | `992f5a1` |

## 可重复验证

```bash
uv sync --extra dev --extra langchain --extra cli --locked
uv run ruff check .
uv run mypy
uv run pytest --cov=graphgpt --cov-report=term-missing --cov-fail-under=90
uv build
```

CI 另外在最低兼容版本上运行 Runtime Conformance、安全契约与 LangGraph CLI smoke test。
远程 LangSmith Trace 需要用户凭据，因此不作为核心编译器发布门禁。
