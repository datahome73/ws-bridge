# R120 系统架构概览

> **轮次：** R120
> **作者：** 小开（Arch）
> **内容：** ≤ 10 句
> **日期：** 2026-07-16

---

ws-bridge 由 5 个核心组件构成：

1. **Gateway** — WebSocket 入口层，负责 bot 身份验证（api_key 校验）、连接生命周期管理（register/disconnect/health check）、以及消息的初步路由分发。

2. **WS Server** (`main.py`) — 核心业务逻辑层，处理所有 WS 消息类型（`_inbox:server` 中继、`##` 命令管线、广播/定向发送），是自动派活管道的执行引擎。

3. **Pipeline Manager** (`pipeline_context.py`) — 管线上下文管理器，负责 PipelineContext 的 CRUD、Step 状态推进（pending → in_progress → done）、自动派活触发（`_auto_dispatch`）、以及状态持久化落盘。

4. **Web UI** (`web_ui/`) — 浏览器端仪表盘，提供聊天界面和管线 Tab（Tab 4），通过 `/api/pipelines` 拉取管线列表，前端排序展示（R118 改为 `created_at DESC`）。

5. **Bot Client** (`clients/python/`) — Python SDK，封装了 ws-bridge 协议（register/ack/send_message），提供自动重连和 inbox 消息监听能力，是每个 bot 的运行时基础。
