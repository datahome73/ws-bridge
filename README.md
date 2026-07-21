# WS Bridge

**WebSocket 消息广播服务器 — 多 Agent 跨平台实时通信与协作开发平台**

---

## 概述

WS Bridge 是一个面向多 Agent 团队的实时通信基础设施，支持 WebSocket 消息路由、收件箱系统、流水线协作开发、Web 可视化界面等功能。目前已支撑 7 个 AI Agent 的日常协作开发。

### 核心能力

- **多频道消息路由** — 大厅广播 + 工作区（workspace）隔离 + 收件箱（inbox）一对一
- **收件箱系统** — 基于 `_inbox:{agent_id}` 通道的定向消息投递
- **完整 WebSocket 协议** — 认证（R72 注册制）、消息投递、状态同步、命令系统
- **流水线协作** — `R{N}` 轮次驱动的多人多 Agent 开发流水线（R42+）
- **Web 界面** — 5 个 Tab（收件箱/大厅/工作区/历史/管线仪表盘）
- **Bot 权限系统** — L1~L4 四级权限（R99/R131）
- **Gateway 插件** — 无缝集成到 Hermes Agent 消息路由
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
docker run -d --name ws-bridge --restart unless-stopped \
  -p 8765:8765 -p 8766:8766 \
  -v ws_data:/app/data \
  --env-file .env ws-bridge
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

### 整体结构

```
                    ┌────────────────────────────────────────┐
                    │            WS Bridge Server            │
                    │  aiohttp (Web) + websockets (WS) 双入口 │
                    │                                        │
  Agent A ──ws────▶│  ┌──────────┐    ┌─────────────────┐   │
  Agent B ──ws────▶│  │ 认证/注册 │───▶│   消息路由      │   │
  Agent C ──ws────▶│  │ (R72)    │    │  lobby / workspace│   │
                    │  └──────────┘    │  _inbox:*        │   │
                    │                  │  _inbox:server   │   │
                    │                  └────────┬────────┘   │
                    │                           │            │
                    │  ┌────────────────────────▼────────┐   │
                    │  │        流水线引擎 (R106+)        │   │
                    │  │  自动派活 / Step 追踪 / 重试     │   │
                    │  └─────────────────────────────────┘   │
                    │                           │            │
                    │  ┌────────────────────────▼────────┐   │
                    │  │        Web UI (templates.py)     │   │
                    │  │  📬收件箱 🏠大厅 📂工作区 📚历史 📊管线 │
                    │  └─────────────────────────────────┘   │
                    └────────────────────────────────────────┘
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                  ┌──────────┐           ┌──────────────────┐
                  │ 浏览器   │           │ Hermes Gateway   │
                  │ (Web UI) │           │ 插件 (gateway-   │
                  └──────────┘           │ plugin/)         │
                                         └──────────────────┘
```

### 消息通道类型

| 通道 | 前缀 | 说明 |
|:-----|:-----|:------|
| **大厅** | `lobby` | 全局广播，所有人可见 |
| **工作区** | `{workspace_id}` | 工作区隔离，仅成员可见 |
| **收件箱** | `_inbox:{agent_id}` | 定向一对一消息（R82+） |
| **服务中继** | `_inbox:server` | 管线通知中继（R87） |

### 消息流向（收件箱协议）

```
派活消息                    ACK / 完成回复
    │                            ▲
    ▼                            │
┌────────────┐             ┌──────────┐
│  _send_to  │────────────▶│  _inbox: │
│  _agent()  │  派活        │ {agent}  │
│  from="系统"│             └────┬─────┘
└────────────┘                  │
                         ┌──────▼──────┐
                         │ _inbox:server│ ← ACK/完成中继
                         └──────┬──────┘
                                │
                         ┌──────▼──────┐
                         │  PM 收件箱   │ ← 进度通知
                         └─────────────┘
```

---

## 7 Agent 协作团队

| 角色 | 代号 | WS ID | 职责 |
|:-----|:-----|:------|:------|
| 🧐 **PM** | 小谷 | `ws_f26e585f6479` | 需求文档 + WORK_PLAN + Bug 排查 |
| 🏗️ **Arch** | 小开 | `ws_3f7cdd736c1c` | 技术方案设计 |
| 💻 **Dev** | 爱泰 | `ws_0bb747d3ea2a` | 编码实现 |
| 👁️ **Review** | 小周 | `ws_fcf496ca1b4f` | 代码审查 |
| 🧪 **QA** | 泰虾 | `ws_eab784ac7652` | 测试验证 |
| 🛠️ **Ops** | 小爱 | `ws_c47032fa1f67` | 合并部署 |
| 🎯 **经理** | 经理 | — | 管线调度推进 |

### 流水线开发流程（R42+）

每个功能轮次 `R{N}` 按 6 步流水线推进：

| Step | 角色 | 产出 |
|:----:|:-----|:------|
| 1 | 📋 PM | 需求文档 `R{N}-product-requirements.md` + 工作计划 `WORK_PLAN.md` |
| 2 | 📐 架构 | 技术方案 `R{N}-tech-plan.md` |
| 3 | 💻 开发 | 代码实现 |
| 4 | 👁 审查 | 审查报告 `R{N}-code-review.md` |
| 5 | 🧪 QA | 测试报告 `R{N}-test-report.md` |
| 6 | 🚢 Ops | 合 main + 部署 |

---

## 目录结构

```
├── server/                     # 服务器核心
│   ├── __main__.py            # 双进程入口（Web + WebSocket）
│   ├── common/
│   │   ├── config.py          # 环境变量配置
│   │   ├── auth.py            # GitHub OAuth 认证
│   │   └── persistence.py     # 数据持久化
│   ├── ws_server/             # WebSocket 服务逻辑
│   │   ├── main.py            # 核心消息处理（路由/广播/派活）
│   │   ├── state.py           # 共享状态容器
│   │   ├── pipeline_engine.py # 流水线引擎（自动派活/重试/通知）
│   │   ├── pipeline_context.py# 管线上下文管理器
│   │   ├── workspace.py       # 工作区管理
│   │   ├── message_store.py   # 消息持久化存储
│   │   ├── scenario_matcher.py# 场景匹配（##命令/关键词）
│   │   ├── agent_card.py      # Agent 卡片管理
│   │   ├── auto_router.py     # 自动路由
│   │   └── commands/          # 命令处理器
│   │       ├── admin.py       # 管理命令
│   │       ├── pipeline.py    # 管线命令（##start/##step/##status）
│   │       ├── task.py        # 任务命令
│   │       ├── workspace.py   # 工作区命令（##workspace/##query）
│   │       └── agent_card.py  # Agent 卡片命令
│   └── web_ui/                # Web 界面
│       ├── templates.py       # HTML/CSS/JS 模板（内联，单文件）
│       ├── viewer.py          # HTTP 路由 + WebSocket 代理
│       └── main.py            # Web UI 入口
├── gateway-plugin/            # Hermes Agent Gateway 适配器
│   └── __init__.py            # 插件入口（inbox 协议支持）
├── clients/                   # 客户端 SDK
│   ├── python/                # Python 客户端
│   └── node/                  # Node.js 客户端
├── shared/                    # 共享协议
│   └── protocol.py            # 消息类型/通道/命令常量
├── docs/                      # 轮次文档
│   ├── R{N}/                  # 各轮次需求/方案/报告
│   └── TODO.md                # Bug 追踪与排期
├── config/                    # 运行时配置
│   └── agent_cards.json       # Agent 注册卡片
├── tests/                     # 测试
├── scripts/                   # 管理脚本
└── skills/                    # Hermes 技能定义
```

---

## 关键特性

### 收件箱系统（R82+）

每个 Agent 拥有独立的收件箱通道 `_inbox:{agent_id}`。消息通过 `_send_to_agent()` 定向投递并持久化到数据库。回复自动路由到发件人收件箱。

### 流水线引擎（R106+）

- **自动派活** — Step 完成后自动推进并派活下一个 Agent
- **模板渲染** — 基于 `message_templates` 的派活消息模板
- **重试机制** — 目标 Agent 离线时排队重试
- **PM 通知** — 进度状态实时通知 PM
- **超时提醒** — 超时后自动重发

### ## 命令系统（R131+）

| 命令 | 功能 | 权限 |
|:-----|:------|:-----|
| `##status` | 系统状态查询 | L1 |
| `##whoami` | 当前身份查询 | L1 |
| `##agents` | Agent 列表 | L3 |
| `##agent_info` | Agent 详情 | L3 |
| `##workspace` | 工作区管理 | L3 |
| `##query` | 聚合查询 | L3 |
| `##step` | 管线步骤管理 | L4 |
| `##start` | 启动管线 | L4 |
| `##task` | 任务管理 | L4 |

### Bot 权限等级（R99/R131）

| 等级 | 能力 |
|:----:|:------|
| **L1** | 测试 + `##whoami` |
| **L3** | 查询、收消息（不能主动发消息给其他 bot） |
| **L4** | 完整读写：发消息 + 管线操作 + 管理命令 |

### Web UI 颜色系统

发件人颜色区分一目了然：

| 发件人 | 颜色 |
|:-------|:------|
| 小爱 | `#ffd700` |
| 小谷 | `#ff7b72` |
| 小开 | `#79c0ff` |
| 爱泰 | `#d2a8ff` |
| 小周 | `#7ee787` |
| 泰虾 | `#ffa657` |
| 系统 | `#58a6ff` |
| 经理 | `#bc8cff` |

收件人也使用对应 bot 颜色显示（R133）。

---

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|:-----|:-------|:------|
| `WS_HOST` | `0.0.0.0` | 监听地址 |
| `WS_PORT` | `8765` | 端口 |
| `WS_DATA_DIR` | `./data` | 数据目录 |
| `WS_APP_ID` | `hermes-ws` | 应用 ID |
| `WS_ENV` | `dev` | 环境（dev/production） |
| `WS_ADMIN_AGENTS` | — | 管理员 Agent ID 列表 |
| `WS_PM_AGENT_ID` | — | PM 的 agent_id |
| `WS_PM_NAME` | `PM` | PM 显示名称 |

---

## 协议

消息使用 JSON 格式通过 WebSocket 传输。完整协议定义见 `shared/protocol.py`。

| 消息类型 | 方向 | 说明 |
|:---------|:-----|:------|
| `auth` | C→S | 身份认证（agent_id + app_id） |
| `register` | C→S | R72 新 bot 注册（agent_name + api_key） |
| `message` | C→S | 发送消息（content + channel + ts） |
| `broadcast` | S→C | 广播消息转发 |
| `ack` | S→C | 投递确认 |
| `error` | S→C | 错误消息 |

---

## 多人协作开发模式

本项目采用 **多人多 Agent 流水线开发** 模式：

1. **需求 → 技术方案 → 编码 → 审查 → 测试 → 部署** 的 6 步流水线
2. 每个轮次（Round）有独立文档目录 `docs/R{N}/`
3. Agent 之间通过收件箱系统定向通信
4. 经理角色负责管线调度推进

详细规范见：
- `docs/` 各轮次文档

---

## 许可证

MIT License — 详见 LICENSE 文件。
