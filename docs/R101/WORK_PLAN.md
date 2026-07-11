---
pipeline:
  name: "R101 WSS/Web 解耦：Web 界面独立为服务 🧹"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R101/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R101/R101-product-requirements.md"

  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 架构设计方案
        context:
          requirements_url: "${pipeline.requirements_url}"
      - step: step3
        role: developer
        title: 编码拆分
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: qa
        title: 测试验证
        context:
          code_review_url: "docs/{round}/{round}-code-review.md"
      - step: step6
        role: operations
        title: 合并部署归档
        context:
          test_report_url: "docs/{round}/{round}-test-report.md"

  steps:
    step2:
      role: architect
      title: 架构设计方案
    step3:
      role: developer
      title: 编码拆分
    step4:
      role: reviewer
      title: 代码审查
    step5:
      role: qa
      title: 测试验证
    step6:
      role: operations
      title: 合并部署归档

  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: |
          基于 R101 需求文档 + server/README.md 架构全景，
          输出独立架构设计方案（R101-tech-plan.md），
          确定 WSS 核心与 Web 服务的边界、数据流、端口分配、文件变更清单。
      developer:
        mention_keyword: "developer;开发"
        rules: |
          按架构方案执行 6 步编码：
          清理 WSS 核心依赖 → 创建 web_service.py → 更新 __main__.py → 更新前端轮询 → 清理 web_viewer.py → 验证。
          每步提交、可回退。
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查解耦质量（核心无 web_viewer 依赖、inbox 通路保留、Web 服务独立可运行）"
      qa:
        mention_keyword: "qa;测试"
        rules: "执行验收 10 项：5 核心通路 + 5 Web 服务独立验证"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + 部署 + 验证解耦后双服务均正常"
---

# R101 工作计划 — WSS/Web 解耦：Web 界面独立为服务 🧹

> **版本：** v1.0
> **状态：** 📝 定稿
> **负责人：** 🧐 PM
> **前置条件：** R100 部署完成 ✅ (v2.69, main cefe7ef)

---

## 概述

将 Web HTTP 服务从 WSS 核心进程中解耦为独立的 HTTP-only 服务。WSS 核心只做 bot 消息路由，Web 服务从 DB 读取数据展示给人类用户。

### 核心判断

> **去掉 Web 界面，bot 之间还能正常收发 inbox 消息吗？**
> **能。** Bot 通信走 WSS，消息持久化走 `message_store.save_message()`（SQLite DB）。
> Web 界面只看已有数据，不参与通信逻辑。

### 改动范围

```
解耦前（同一进程）                     解耦后（两个独立服务）
                                      
__main__.py                          WSS 核心 (port 8765)
├── /ws                              ├── /ws
├── /api/chat                        ├── /api/status
├── /api/channels                    ├── /api/health
├── /, /chat                         └── /api/workspaces
├── /api/inbox                       
├── /api/bind, /api/check            Web 服务 (port 8766)
├── /api/agents/status               ├── /, /chat
├── /auth/github/*                   ├── /api/chat
├── /api/logout, /api/auth/me        ├── /api/channels
├── /api/archive                     ├── /api/inbox
└── /ws/chat                         ├── /api/bind, /api/check
                                      ├── /api/agents/status
                                      ├── /auth/github/*
                                      ├── /api/logout, /api/auth/me
                                      └── /api/archive
```

### 删除的耦合

| 耦合项 | 数量 | 说明 |
|:-------|:----:|:------|
| `write_chat_log()` 调用 | 23 处 | 分布在 main.py / command_utils.py / commands/pipeline.py / commands/workspace.py / __main__.py |
| `_ws_clients` 引用 | 3 处 | main.py + __main__.py |
| `from .web_viewer import ...` | 6 处 | 6 个文件中的 import |
| `setup_routes()` 调用 | 2 处 | __main__.py |
| WebSocket 前端推送 | 1 处 | templates.py 中的 WS 连接代码 |

### 改动规模

| 文件 | 动作 | 行数变化 |
|:-----|:-----|:---------|
| `server/__main__.py` | 大幅精简 | 832 → ~50 行 |
| `server/main.py` | 删 13 处 write_chat_log + _ws_clients | ~-50 行 |
| `server/command_utils.py` | 删 2 处 write_chat_log + import | ~-10 行 |
| `server/commands/pipeline.py` | 删 4 处 write_chat_log + import | ~-20 行 |
| `server/commands/workspace.py` | 删 wv import + 1 处 write_chat_log | ~-10 行 |
| `server/web_viewer.py` | 清理 _ws_clients / _chat_buffers / handle_ws_chat / write_chat_log | ~-150 行 |
| `server/templates.py` | WS 连接 → fetch 轮询 | ~-50 行/+30 行 |
| `server/web_service.py` | **🔺 新增** — HTTP 服务独立入口 | ~+30 行 |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 需求文档 + 工作计划 | R101-product-requirements.md + WORK_PLAN.md | 推 dev |
| **Step 2** ✅ 完成 | 👷 小开 | 架构设计方案 | R101-tech-plan.md | 推 dev ✅ |
| **Step 3** ✅ 完成 | 👨‍💻 爱泰 | 编码 — 6 步执行（清理依赖→创建 web 服务→精简核心→前端轮询→清理 web_viewer→验证） | commit `0baddc8` | 推 dev ✅ |
| **Step 4** ✅ 完成 | 👀 大宏 | 代码审查 | R101-code-review.md | 推 dev ✅ |
| **Step 5** ⏳ | 🦐 QA | 测试验证 | R101-test-report.md（10 项验收） | 推 dev |
| **Step 6** ⏳ | 🛠️ Ops | 合并 dev→main + 部署 | Docker 新镜像 + 生产验证 | TODO.md 更新 |

---

## Step 1 产出（PM — 已完成 ✅）

| 产出 | 路径 | GitHub 预览 |
|:-----|:------|:------------|
| 需求文档 | `docs/R101/R101-product-requirements.md` | [预览](https://github.com/datahome73/ws-bridge/blob/dev/docs/R101/R101-product-requirements.md) |
| 工作计划 | `docs/R101/WORK_PLAN.md` | [预览](https://github.com/datahome73/ws-bridge/blob/dev/docs/R101/WORK_PLAN.md) |

---

## Step 2 架构设计（小开 — 待执行）

小开需要：

### 1. 阅读参考资料

| 资料 | 内容 |
|:-----|:------|
| `docs/R101/R101-product-requirements.md` | 需求文档（背景/目标/方案/验收标准） |
| `server/__main__.py` | 当前入口，832 行，了解全部路由注册 |
| `server/web_viewer.py` | 当前 Web 后端 725 行，了解全部 API handler |
| `server/main.py` | WSS 核心，了解 write_chat_log 调用点 |
| `server/message_store.py` | DB API，Web 服务将依赖此模块 |
| `server/templates.py` | 前端 HTML/JS，需改为轮询 |

### 2. 产出 `docs/R101/R101-tech-plan.md`

需包含：

- **服务边界确认**
  - WSS 核心仅保留哪些路由
  - Web 服务接管哪些路由
  - 共享模块清单（message_store / persistence / auth / config）

- **数据流设计**
  - WSS 核心：消息路由 → `save_message(DB)` 后结束
  - Web 服务：`GET /api/chat?since=ts` → `get_messages_since(DB)` → 返回 JSON
  - 无实时推送通道

- **write_chat_log 调用 23 处逐一确认** — 每处是纯日志写入还是有关联逻辑？纯日志的全部删除

- **文件修改清单** — 每个文件的精确修改内容、行数

- **端口分配**
  - WSS 核心：`WS_PORT` 环境变量，默认 8765
  - Web 服务：`WS_HTTP_PORT` 环境变量，默认 8766

- **部署拓扑**
  - 两个独立 systemd 服务 / Docker 容器
  - 共享 `DATA_DIR` 数据卷

- **执行顺序建议**
  - Step 3 的 6 个子步顺序和依赖关系

---

## Step 3 编码（Dev — 待执行）

等待 Step 2 架构方案确定后执行。预计 6 个子步骤：

| 子步 | 内容 | 涉及文件 |
|:----:|:-----|:---------|
| **3.1** | 清理 WSS 核心依赖 | main.py / command_utils.py / commands/pipeline.py / commands/workspace.py — 删除全部 write_chat_log 调用 + import |
| **3.2** | 创建 web_service.py | `server/web_service.py` — 独立 HTTP 入口，复用 web_viewer.setup_routes |
| **3.3** | 精简 __main__.py | 删除 setup_routes / web_viewer import / write_chat_log / _ws_clients，只留 WSS 路由 |
| **3.4** | 更新前端模板 | templates.py — WebSocket 连接代码 → fetch 轮询 (5s interval + 下拉刷新) |
| **3.5** | 清理 web_viewer.py | 删除 write_chat_log / _chat_buffers / _ws_clients / handle_ws_chat，保留所有 API handler |
| **3.6** | 本地验证 | 启动 WSS 核心 + Web 服务，验证双服务独立运行 + 双向通信测试 |

**注意事项：**

- 每子步独立提交，可回退
- 验证时不需部署到生产，本地起两个进程即可
- `write_chat_log` 被完全移除后，旧的聊天日志文件（`data/chat_logs/`）仍是可读的，`read_channel_logs` 作为 fallback 保留在 web_viewer.py 中
- 确认 `message_store.save_message()` 在 `handle_broadcast()` 中被调用（走 DB 路径），不依赖日志文件

---

## 验收标准

### 核心通路（5 项）

```
1. Bot A 连接 WSS → 认证成功
2. Bot A 向 Bot B 发 _inbox 消息 → Bot B 收到并回复
3. _inbox:server 中继功能正常
4. 大厅 lobby 消息广播正常
5. 停 Web 服务后 bot 通信不受影响（kill web_service → bot 收发正常）
```

### Web 服务验证（5 项）

```
6. Web 服务独立启动 → http://host:8766/ 可访问
7. 聊天页面能显示消息历史（从 DB 读取）
8. 发一条新消息 → 5 秒内轮询自动显示
9. 手机下拉刷新 → 消息更新
10. 停 WSS 核心后 Web 服务仍能显示已有历史数据
```

### 代码质量验证

```
11. grep -rn 'web_viewer' server/main.py server/__main__.py server/command_utils.py server/commands/ → 0
12. grep -rn 'write_chat_log' server/main.py server/__main__.py server/command_utils.py server/commands/ → 0
13. grep -rn '_ws_clients' server/main.py server/__main__.py → 0
14. __main__.py 中只有 /ws + 3 个极简 API 路由
15. 所有现有 !命令功能不变
```

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | server/ 下 1 新增文件 + 7 修改文件，零行为变更（bot 通信不变） |
| 测试 | 全部 10+5 项验收 🟢 通过 |
| 文档 | 架构方案 + 审查报告 + 测试报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启双服务 |

---

## 已知风险

| 风险 | 缓解 |
|:-----|:------|
| 删除 23 处 write_chat_log 可能漏删 | 子步 3.1 后立即 grep 验证，确认 0 残留 |
| web_viewer 中 write_chat_log 被其他模块引用 | web_viewer 内的 write_chat_log 定义保留到子步 3.5 才删，确保 3.1-3.3 改完后再无引用 |
| 前端模板 WS 代码与轮询并跑 | 确保子步 3.4 完全替换，避免双路逻辑冲突 |
| 外部脚本依赖日志文件 | 已有日志文件继续存在（只读），写操作停止。需确认无自动化脚本依赖新写入 |
