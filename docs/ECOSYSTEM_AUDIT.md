# 历史 LangChain 生态周报适配审计

日期：2026-11-05。对象：GraphGPT / DAGGraphBuilder 0.11.0 开发分支。

## 结论

项目能够作为 Python LangGraph 的声明式编译层，支持 LangChain Runnable、模型、工具、
MCP、HITL、Checkpoint 和 Langfuse 观测。不能据此宣称覆盖整个 LangChain/Deep Agents
生态，或已经实现历史周报中全部研究提案。研究型路线与当前兼容性缺陷分开管理。

审计输入：历史聊天“LangGraph 生态周报”中第 1–4 期（9 月 25 日—10 月 23 日），
用户提供第 5 期（10 月 24—30 日）附件，以及每周推进报告。
周报仅作为需求线索；其中第三方版本、性能与研究结论不是本项目兼容承诺。
以下结论依据本仓库代码、测试和本地真实 Langfuse 服务，不重复把规划标记为完成。

## 需求—实现—边界

| 周报主题 | 本项目证据 | 结论与未覆盖部分 |
|---|---|---|
| 第 1 期：Project IR / directory compiler | `dsl/models.py`, `project.py`, `test_project.py` | 已有 YAML/IR 与 CLI 项目生成；不是 Managed Deep Agents 全目录编译器 |
| 第 1 期：Durable Run Runtime | `tasks.py`, `test_tasks_evaluation.py` | 进程内取消/恢复/资源互斥；不提供服务器持久队列、崩溃恢复或浏览器队列 |
| 第 1–2 期：Artifact / Skill | `adapters/converters.py`, `test_conversion.py` | 支持格式转换及保真报告；没有 Blob Backend、lazy/pinned Skill 执行器 |
| 第 1–2 期：Provider Capability Matrix | `registry.py`, `application/validate.py` | 有绑定/Schema 校验，未维护跨模型能力矩阵，不保证 named-tool forcing 通用 |
| 第 2 期：Checkpoint 分支隔离 | `test_runtime_conformance.py`, `test_runtime_recovery.py` | Python 原生/生成图对照与 Delta 回放验证；上游 #9344 明确 xfail |
| 第 2 期：不可变部署 | `project.py`, `test_langgraph_cli_integration.py` | CLI 工程启动已验证；没有容器构建/镜像 digest 发布器 |
| 第 3 期：并行 State 语义 | `application/validate.py`, `test_runtime_conformance.py` | fan-out writes/reducer 校验与 Python 一致性测试；无 JS 编译/跨语言对照 |
| 第 3 期：Per-call HITL | `registry.py`, `test_runtime_security.py` | batched/per_call、response schema、恢复验证；不承诺多工具外部副作用事务原子性 |
| 第 3 期：异步 Subagent | `tasks.py`, `test_tasks_evaluation.py` | 显式 interrupted/resume、父子任务关联；非 Deep Agents remote task protocol |
| 第 3 期：Middleware / ScaleDown | `registry.py` | 目前装配 HITL；任意 middleware 阶段/failure policy/ScaleDown 需应用 Runnable 适配 |
| 第 4 期：Semantic Contract / Lean4Agent | `application/validate.py`, `actions.py` | 结构、写集合与 Action Schema 契约；无通用 requires/ensures/invariants 证明器 |
| 第 4 期：TaskPlanIR / HTN | `tasks.py` | Task 生命周期不是动态依赖计划；无 HTN 重规划/成本预算求解器 |
| 第 4 期：工具参数 delta streaming | `registry.py`, `test_model_runtime.py` | 修复原生 async/config/event 传递；Core 1.7 跨协议 UI 归并仍未验证 |
| 第 1–5 期：Trace identity / evaluation | `tracing.py`, `evaluation.py`, `test_langfuse_evaluation.py` | 已换为 Langfuse v2 observation 查询；真实本地 Trace 与三项评估通过 |
| 第 5 期：typed decision / action / runtime policy | `decisions.py`, `actions.py`, `test_decisions_actions.py`, `test_runtime_recovery.py` | predicate/choice/score、拒答策略、版本 action、hooks、error handler、delta snapshot 已验证；非厂商模型认证 |
| 横向：MCP | `mcp.py`, `test_mcp.py` | 官方 MCPAdapter 发现、注册与真实进程内工具调用；beta API 由版本和 CI 约束 |

## 本轮直接修复

- `langchain:model` 原先只有同步闭包，未显式传递 RunnableConfig。现用 RunnableLambda
  提供 sync/async 两条执行路径，测试禁止异步路径退回同步 invoke，并校验 callback、
  tags、metadata 和原生模型流事件。
- CLI 在普通调用、流式调用及运行失败路径均 flush Langfuse，降低短进程 Trace 丢失风险。
- 从 callback-only / HTTP mock 提升为本机真实 Langfuse 写入、查询和评估验收；
  缺少业务 evaluator 的检查仍为 not_evaluated。

## 后续优先级与验收

1. P0：Core 1.7 新旧工具参数事件兼容测试，明确 snapshot/delta 能力标志；
   用多个交错 tool-call ID、大参数和子图验证，不把未知协议静默拼接。
2. P1：显式 ProviderCapabilityMatrix，拒绝不支持的模型能力；在有真实 provider
   凭据时增加认证测试，不能仅凭统一 init_chat_model 接口宣称支持。
3. P1：Semantic Contract IR 的有限可判定 reads/requires/ensures 子集，分支/循环
   数据流分析，失败定位源文件；不将自然语言约束等同于形式化证明。
4. P1：按产品需求引入可持久化 Task Backend 与 Artifact Store；验证进程重启、
   大对象引用、权限和幂等性，再承诺 durable async 与动态计划。
5. P2：独立扩展 Skill/Middleware Registry 和 JS backend；继续保留未支持语义的
   明确错误/保真报告，避免破坏当前 Python 编译器边界。

验证基线见 [兼容矩阵](COMPATIBILITY.md)，真实接入步骤见 [本地 Langfuse](LOCAL_LANGFUSE.md)。
上述尚未实现项目是明确保留的能力边界，不阻止已支持功能使用，也不计为已完成任务。
