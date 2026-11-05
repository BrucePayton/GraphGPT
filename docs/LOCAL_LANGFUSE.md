# 本地 Langfuse 接入

验证日期：2026-11-05。当前开发分支 0.11.0；不是 PyPI 已发布声明。

## 启动与重跑

在仓库根目录运行（需要 Docker Desktop 启动、网络可访问官方镜像仓库）：

```bash
uv sync --extra dev --extra langchain --extra langfuse --locked
uv run python scripts/local_langfuse.py
docker compose --project-directory .local/langfuse up -d
# 首次启动需要等待数据库迁移及 /api/public/health 返回成功
curl --fail http://localhost:3300/api/public/health
uv run python scripts/verify_local_langfuse.py
```

网页地址：http://localhost:3300。首次初始化账号是 `developer@graphgpt.local`；
密码在 `.local/langfuse/.env` 的 `LANGFUSE_INIT_USER_PASSWORD`。不要粘贴或提交该文件。
脚本生成随机密钥，文件权限 0600，整个 `.local/` 被 Git 忽略；重复运行保留原凭据和数据。
独立 Compose project `graphgpt-local-langfuse` 不复用其他项目的容器或数据卷。
只有 Web 3300 与对象存储 3390 绑定 127.0.0.1；数据库、Redis、worker 不开放宿主端口。
这是单机开发配置，不是生产 TLS、备份、授权隔离或高可用部署方案。

配置来源为 [官方 Compose](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml)，
脚本记录下载的精确提交到 `.local/langfuse/upstream.json`。
镜像仍采用上游标签，长期复现/部署应保存 image digest 并审查升级；不自动更新已有配置。
初始化采用 [官方 headless initialization](https://langfuse.com/self-hosting/administration/headless-initialization)。

停止服务但保留数据：

```bash
docker compose --project-directory .local/langfuse stop
```

## 验收结果与边界

`verify_local_langfuse.py` 使用合成输入和本地确定性 provider，无付费模型请求：

1. 编译仓库的 typed-decision 示例，异步运行决定节点和带前置 hook 的 Action。
2. 使用真实 Langfuse callback 写入并 flush；保留图、节点、编译器版本与本地环境标识。
3. 从真实 Observations v2 查询，最多等待 120 秒以容纳异步摄取。
4. 验证 decide/report 执行成功和 decide 类型正确；输出真实 trace/observation ID。

2026-11-05 首次验证三项 passed；`interrupt_resumed` 和
`rejection_has_no_side_effects` 为 `not_evaluated`，本次没有审批恢复，不冒充通过。
可重跑证据写入 `.local/langfuse/verification.json`（含本机 Trace 链接，不含密钥）。
Cloud 服务、真实模型质量、评分写回、跨服务器父子 Trace 和生产业务数据尚未在此测试。

## 在其他工作流中使用

配置 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY` 和
`LANGFUSE_BASE_URL=http://localhost:3300` 后：

```bash
graphgpt run workflow.yaml --trace langfuse --input '{}'
```

CLI 在运行成功或异常时都会 flush。Python 长驻应用自行管理客户端：将
`langfuse.langchain.CallbackHandler` 放入 RunnableConfig 的 callbacks，调用结束按需
`client.flush()`，应用退出 `client.shutdown()`。公共 `invoke_workflow` 自动合并图身份；
直接调用编译图时用 `graphgpt.tracing.merge_trace_config` 补齐根 Trace 身份。
评估适配器为只读；实际业务审批/安全结论需要显式自定义 evaluator。
