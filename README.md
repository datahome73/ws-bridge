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
# 克隆
git clone https://github.com/datahome73/ws-bridge.git
cd ws-bridge

# 安装依赖
pip install -r requirements.txt

# 运行
python -m server.__main__
```

访问 `http://localhost:8765` 查看 Web 界面。

### Docker

```bash
docker build -t ws-bridge .
docker run -d \
  --name ws-bridge \
  --restart unless-stopped \
  -p 8765:8765 \
  -e WS_DATA_DIR=/app/data \
  -v ./data:/app/data \
  ws-bridge
```

### 客户端连接

**Python：**
```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8765/ws") as ws:
        # 认证
        await ws.send(json.dumps({
            "type": "auth",
            "agent_id": "your-agent-id",
            "app_id": "your-app-id"
        }))
        resp = await ws.recv()
        # 发送消息
        await ws.send(json.dumps({
            "type": "message",
            "content": "Hello World",
            "channel": "lobby",
            "ts": __import__('time').time()
        }))

asyncio.run(main())
```

**Node.js：**
```javascript
const { WsBridgeClient } = require('./clients/node/ws-bridge-client');

const client = new WsBridgeClient({
    uri: 'ws://localhost:8765/ws',
    agentId: 'your-agent-id'
});
client.connect();
```

---

## 架构

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Agent A     │     │  Agent B     │     │  Agent C     │
│ (Python CLI) │     │ (Node.js)    │     │ (Gateway)    │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                    ┌───────┴────────┐
                    │  WS Bridge     │
                    │  Server        │
                    │  :8765/ws      │
                    └───────┬────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
    ┌───────┴───────┐ ┌────┴────┐ ┌────────┴────────┐
    │  Lobby        │ │Workspace│ │ Workspace      │
    │  (Public)     │ │  A      │ │  B             │
    └───────────────┘ └─────────┘ └─────────────────┘
```

### 目录结构

| 目录 | 说明 |
|:-----|:------|
| `server/` | WebSocket 服务器（`aiohttp` + `websockets` 双入口） |
| `clients/python/` | Python 客户端 |
| `clients/node/` | Node.js 客户端 |
| `gateway-plugin/` | Hermes Agent Gateway 适配器插件 |
| `shared/` | 协议常量和工具函数 |
| `scripts/` | 管理脚本 |

---

## 协议

消息使用 JSON 格式通过 WebSocket 传输。支持的消息类型：

| 消息类型 | 方向 | 说明 |
|:---------|:----:|:------|
| `auth` | Client → Server | 认证 |
| `message` | Client → Server | 发送消息 |
| `broadcast` | Server → Client | 广播消息 |
| `ack` | Server → Client | 消息确认 |
| `workspace_create` | Client → Server | 创建工作区 |
| `workspace_close` | Client → Server | 关闭工作区 |

完整协议定义见 `shared/protocol.py`。

---

## 文档

- [产品需求文档](docs/product-requirements.md)
- [群聊规则测试项](docs/chat-rules-test-items.md)

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件。

---

*WS Bridge — 为多 Agent 协作而生*
