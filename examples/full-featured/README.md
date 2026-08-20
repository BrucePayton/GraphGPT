# GraphGPT full-featured example

这个示例完全离线运行，用一条工作流验证 GraphGPT 0.6 已落地的主要能力：

- `graphgpt.plugins` 版本化本地插件；
- `${ENV_VAR}` secret 引用与安全序列化；
- `Send` fan-out、Reducer 聚合与 `Command` 动态跳转；
- 带输入/输出映射的子图；
- 节点 retry、cache 和 metadata；
- checkpointer、动态 interrupt/resume；
- sync invoke、async invoke、stream 和 `RunnableConfig` tags/metadata；
- 标准 `langgraph.json`。

`workflow.yaml` 使用内存 checkpointer，供本地 interrupt/resume 验证；`server.yaml` 使用
`server-managed`，供 LangGraph Agent Server/Studio 托管持久化。验证程序会确认两者除此之外完全一致。

一键验证：

```bash
cd examples/full-featured
uv run graphgpt-full-example
```

验证 LangGraph CLI 配置并启动 Studio：

```bash
cp .env.example .env
uv sync --extra dev
uv run langgraph dev --config langgraph.json
```

工作流中的 `apiKey` 仅保存 `${GRAPHGPT_DEMO_API_KEY}` 引用。验证程序会设置一个本地演示值，
并确认该值不会进入规范化 IR。
