# WS Bridge

**WebSocket 消息广播服务器 — 多 Agent 跨平台实时通信**

---

## 概述

WS Bridge 是一个轻量级的 WebSocket 消息广播服务器，专为多 Agent 跨平台实时通信设计。它提供了：

- **多频道消息路由** — 大厅广播 + 工作区（workspace）隔离
- **完整的 WebSocket 协议** — 认证、消息投递、状态同步
- **跨 Agent 通信** — 支持多个 bot 实例在同一频道中协作
- **Web 聊天界面** — 浏览器端实时消息查看
- **Gateway 插件** — 将 WS Bridge 集成到 Agent 消息路由
- **多语言客户端** — Python + Node.js

---

## 快速开始

### 服务端

```bash
git clone https://github.com/datahome73/ws-bridge.git
cd ws-bridge
pip install -r requirements.txt
python -m server.__main__
```

访问 `http://localhost:8765` 查看 Web 界面。

### Docker

```bash
docker build -t ws-bridge .
docker run -d --name ws-bridge --restart unless-stopped -p 8765:8765 \
  -e WS_DATA_DIR=/app/data -v ./data:/app/data ws-bridge
```

### 客户端连接

**Python：**
```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8765/ws") as ws:
        await ws.send(json.dumps({
            "type": "auth", "agent_id": "your-id", "app_id": "your-app"
        }))
        resp = await ws.recv()
        await ws.send(json.dumps({
            "type": "message", "content": "Hello", "channel": "lobby",
            "ts": __import__("time").time()
        }))

asyncio.run(main())
```

**Node.js：** 见 `clients/node/` 目录。

---

## 架构

```
Agent A ──┐
Agent B ──┼──> WS Bridge Server (:8765/ws) ──> Lobby (Public)
Agent C ──┘                              ──> Workspace A
                                          ──> Workspace B
```

### 目录结构

| 目录 | 说明 |
|:-----|:------|
| server/ | WebSocket 服务器（aiohttp + websockets 双入口） |
| clients/ | Python + Node.js 客户端 |
| gateway-plugin/ | Hermes Agent Gateway 适配器 |
| shared/ | 协议常量和工具函数 |
| scripts/ | 管理脚本 |

---

## 多人协作开发模式

本项目的多人多 Agent 协作开发流程和群聊规则，详见文档：

- **软件开发工作流程** (docs/WORKFLOW.md) — 多人流水线协作规范
- **工作群聊天规则** (docs/WORKSPACE_RULES.md) — 多 Agent 通信纪律
- **TODO** (docs/TODO.md) — 迭代计划与维护追踪

---

## 协议

消息使用 JSON 格式通过 WebSocket 传输。完整协议定义见 `shared/protocol.py`。

---

## 许可证

MIT License — 详见 LICENSE 文件。
