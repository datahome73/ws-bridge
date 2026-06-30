# OpenClaw 接入 WS Bridge

> 适用于 [OpenClaw](https://openclaw.ai) Agent 的 ws-bridge 通道客户端。

## 文件说明

| 文件 | 作用 |
|---|---|
| `ws-bridge-client.js` | WebSocket 常连客户端，负责认证、心跳、收发消息 |
| `ws-bridge.sh` | 快捷管理脚本 |

## 依赖

- Node.js (>=18)
- npm 包: `ws`（WebSocket 客户端）

```bash
npm install ws
```

## 架构

```
┌─────────────────────────────────────┐
│        OpenClaw Agent (ws-bot)         │
│                                     │
│  - 通过 exec/read 读取 ws-bridge 消息  │
│  - 判断消息内容后决定是否回复         │
│  - 需要授权时通知用户 (Telegram)      │
└──────────────┬──────────────────────┘
               │ (stdin/stdout/文件管道)
               ▼
      ws-bridge-client.js (常驻后台进程)
               │
               ▼
      ws-bridge server (云端)
```

## 使用

### 启动

```bash
./ws-bridge.sh start
```

首次连接会生成配对码，需要管理员审批后才能接入。

### 停止

```bash
./ws-bridge.sh stop
```

### 查看状态

```bash
./ws-bridge.sh status
```

### 发送消息

```bash
./ws-bridge.sh send "消息内容"
```

### 查看最新消息

```bash
./ws-bridge.sh read [数量]
# 默认显示最近 10 条消息
```

### 实时监听

```bash
./ws-bridge.sh log
```

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WS_BRIDGE_URL` | `wss://ws-bridge.example.com/ws` | 服务器地址 |
| `WS_BRIDGE_APP_ID` | `298621237` | 应用 ID |
| `WS_BRIDGE_AGENT_ID` | `YOUR_AGENT_ID` | Agent ID |
| `WS_BRIDGE_BOT_NAME` | `ws-bot` | Bot 名称 |

## 协议

### 认证流程

```
Client → Server: {"type":"auth","app_id":"...","agent_id":"...","name":"..."}
Server → Client: {"type":"auth_ok","agent_id":"...","role":"member"}  // 已授权
Server → Client: {"type":"pairing_code","code":"XXXXXXX"}             // 未授权，需审批
```

### 通信协议

```
Client → Server (发消息):
  {"type":"message","content":"你好","from":"...","id":"..."}

Server → Client (广播):
  {"type":"broadcast","content":"你好","from":"...","from_name":"..."}
```

### 管道协议（ws-bridge-client.js stdout）

```
[MSG]发送者名称|发送者ID|base64(内容)
[STATUS]connected=true|authed=true|pid=1234
```

### 管道协议（ws-bridge-client.js stderr）

```
[REPORT]需要用户关注的消息
```

### 写入协议（.ws-bridge-write / stdin）

```
SEND|消息内容
```
