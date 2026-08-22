# GraphGPT

[![PyPI](https://img.shields.io/pypi/v/graphgpt-builder)](https://pypi.org/project/graphgpt-builder/)
[![Python](https://img.shields.io/pypi/pyversions/graphgpt-builder)](https://pypi.org/project/graphgpt-builder/)
[![CI](https://github.com/BrucePayton/GraphGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/BrucePayton/GraphGPT/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

GraphGPT 是一个 Python 优先、面向 LangGraph 1.x / LangChain 1.x 的声明式状态图编译器。
它把版本化 YAML 编译为原生 `StateGraph` / `CompiledStateGraph`，不引入第二套运行时。

> 当前版本：v0.8.0。GraphGPT 支持循环、条件路由和持久化，因此它并不把图限制为 DAG。

## 核心能力

- 严格的 `graphgpt.dev/v1alpha1` YAML DSL 与 JSON Schema；
- YAML → 纯领域 IR → 语义诊断 → 原生 LangGraph 编译；
- 普通边、条件边、循环、messages state、Reducer、interrupt 和内存持久化；
- Command 动态跳转、Send fan-out、retry/cache、可映射子图与跨文件诊断；
- 显式注册、受 allowlist 保护的 Python callable、LangChain Runnable、model/agent 和 ToolNode；
- 版本化第三方插件协议、插件发现/健康检查及独立插件项目生成；
- 环境变量 Secret 引用、诊断脱敏，以及精确到 YAML 文件/行/列的 SourceMap；
- `validate`、`inspect`、`run`、`init`、`export`、`schema`、`doctor`、`dev` CLI；
- 标准 `langgraph.json` 生成，适配 LangGraph CLI、Agent Server 与 LangSmith Studio；
- LangSmith 环境变量透传，以及可选 Langfuse callback；
- Chat、Branch、Loop、Tool-use、RAG 五个离线可运行模板。

## 快速开始

```bash
pip install graphgpt-builder
graphgpt init ./my-agent --template branch
cd my-agent
uv sync
uv run graphgpt validate workflow.yaml
uv run graphgpt run workflow.yaml --input '{"approved": true}'
```

若要使用 `graphgpt dev` 的官方 CLI 委托，可在生成的项目中执行
`uv add "graphgpt-builder[cli]>=0.8,<0.9"`。Langfuse 追踪同理使用 `langfuse` extra，
LangSmith SDK 已随核心 LangGraph 生态安装并通过标准环境变量启用。

在 Python 中也可以只采用编译器核心：

```python
from graphgpt import BindingRegistry, compile_workflow

registry = BindingRegistry({"step": lambda state: {"result": "ok"}})
graph = compile_workflow("workflow.yaml", registry=registry)
print(graph.invoke({}))
```

## 插件生态

创建一个可独立测试、构建和发布到 PyPI 的社区插件：

```bash
graphgpt plugin init ./graphgpt-acme --name acme
cd graphgpt-acme
uv sync --extra dev
uv run pytest
uv build
```

安装插件后可检查 entry point、协议版本和能力声明：

```bash
graphgpt plugin list
graphgpt plugin list --output json
```

插件作者指南见 [`docs/PLUGINS.md`](docs/PLUGINS.md)，已验证集成和社区插件目录见
[`ECOSYSTEM.md`](ECOSYSTEM.md)。第三方插件在独立包中维护，不会把 provider SDK 引入核心。

## 最小 DSL

```yaml
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: hello
spec:
  state:
    fields:
      result: {type: string}
  security:
    allowedModules: [my_agent]
  nodes:
    hello:
      use: python:my_agent.nodes.hello
  edges:
    - {from: $start, to: hello}
    - {from: hello, to: $end}
```

`graphgpt validate` 不导入节点代码或访问网络。只有 `compile` / `run` 阶段才解析绑定，
且 `python:` 引用必须位于 `security.allowedModules` 中。

## 架构

核心依赖方向固定为：`domain <- application <- adapters/CLI`。DSL 模型不会直接泄漏到
LangGraph 编译器，LangSmith 和 Langfuse 也只是外层观测适配器。详见
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 和
[`docs/RESEARCH.md`](docs/RESEARCH.md)。长期路线见
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md)。

## 开发

```bash
uv run ruff check .
uv run mypy
uv run pytest --cov=graphgpt
uv build
```

欢迎提交 bug、RFC、集成和社区插件。参与前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)、
[`GOVERNANCE.md`](GOVERNANCE.md)、[`SECURITY.md`](SECURITY.md) 与
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

许可证：Apache-2.0。
