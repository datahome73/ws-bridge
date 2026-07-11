---
pipeline:
  name: "R102 Server 转发体系：派活→过滤→自动触发 🚉"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R102/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R102/R102-product-requirements.md"

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
        title: 编码
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
      title: 编码
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
          基于 R102 需求文档 + server/README.md 架构全景，
          输出技术方案（R102-tech-plan.md），
          确定 _handle_server_query 扩展点、to_agent 路由逻辑、
          前缀匹配过滤流程、DISPATCH_SENDER_ID 配置项。
      developer:
        mention_keyword: "developer;开发"
        rules: |
          按架构方案执行编码：
          ① 扩展 _handle_server_query 处理 to_agent 派活
          ② 新增 _handle_bot_reply 处理 bot 回复前缀匹配
          ③ config.py 新增 DISPATCH_SENDER_ID
          ④ 前缀匹配转发通知到 PM inbox
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: |
          审查：发件人是否隐藏、前缀是否精准匹配、无关消息是否入库不转发、
          DISPATCH_SENDER_ID 配置是否正确、to_agent 字段安全校验。
      qa:
        mention_keyword: "qa;测试"
        rules: "执行 8 项验收：派活路由 + 隐藏发件人 + ACK/完成/退回/失败 PM 通知 + 无前缀入库 + 回路测试兼容"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + 部署 + 验证 R102 派活全链路正常"
---

# R102 工作计划 — Server 转发体系：派活→过滤→自动触发 🚉

> **版本：** v1.0
> **状态：** 📝 定稿
> **负责人：** 🧐 PM
> **前置条件：** R101 (WSS/Web 解耦) 已部署 ✅

---

## 概述

将当前「直达派活」（PM → `_inbox:bot_id`）改为「Server 中介派活」（PM → `_inbox:server` → Server 转发 → Bot）。Server 由此获得完整消息链视角，为后续 auto 机制打下基础。

### 核心变更

| 维度 | 当前 (R101) | 目标 (R102) |
|:-----|:------------|:------------|
| 派活方式 | PM 直接发 `_inbox:ws_xxx` | PM 发 `_inbox:server` + `to_agent` 字段 |
| 发件人 | 暴露 PM 身份 | 隐藏为 `系统`/`server` |
| Bot 回复 | 回 PM 私聊，Server 无感知 | 回 `_inbox:server`，Server 前缀匹配 |
| 无关消息 | 全部转发 | 仅入库，不转发不回复 |
| PM 掌握进度 | 靠自己收消息 | Server 自动转发 ACK/完成/退回/失败通知 |

### 改动规模

| 文件 | 动作 | 估算 |
|:-----|:-----|:------|
| `server/main.py` | `_handle_server_query` 扩展：支持 `to_agent` 派活路由 + `_handle_bot_reply` 前缀匹配过滤 + 通知 PM | ~+120 行 |
| `server/config.py` | 新增 `DISPATCH_SENDER_ID` 配置项 | ~+3 行 |
| 客户端 | **零改动** — PM 改发送目标即可 | 0 行 |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 |
|:----:|:-----|:---------|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 需求文档 + 工作计划 | R102-product-requirements.md + WORK_PLAN.md |
| **Step 2** ⏳ | 👷 小开 | 架构设计方案 | R102-tech-plan.md |
| **Step 3** ⏳ | 👨‍💻 爱泰 | 编码实现 | commit 推 dev |
| **Step 4** ⏳ | 👀 小周 | 代码审查 | R102-code-review.md |
| **Step 5** ⏳ | 🦐 泰虾 | 测试验证 | R102-test-report.md |
| **Step 6** ⏳ | 🛠️ 小爱 | 合并 dev→main + 部署 | Docker 新镜像 + TODO.md 更新 |

> **注意：** 需求文档（§三-§四）已包含详细数据流图、伪代码、文件变更清单。如项目负责人确认 Step 2 可跳过，则直接进入 Step 3 编码。

---

## Step 1 产出 ✅

| 产出 | 路径 | GitHub 预览 |
|:-----|:------|:------------|
| 需求文档 | `docs/R102/R102-product-requirements.md` | [预览](https://github.com/datahome73/ws-bridge/blob/dev/docs/R102/R102-product-requirements.md) |
| 工作计划 | `docs/R102/WORK_PLAN.md` | [预览](https://github.com/datahome73/ws-bridge/blob/dev/docs/R102/WORK_PLAN.md) |

---

## Step 2 架构设计（小开）

### 阅读资料

| 资料 | 内容 |
|:-----|:------|
| `docs/R102/R102-product-requirements.md` | 需求文档（背景/目标/方案/验收标准/伪代码） |
| `server/main.py` | 核心消息路由，`_handle_server_query` 是入口 |
| `server/config.py` | 环境变量配置 |
| `server/__main__.py` | `_api_status` 已实现 /api/status |

### 产出 `docs/R102/R102-tech-plan.md`

需包含：

- **扩展点分析**
  - `_handle_server_query` 当前支持 `!` 命令 + `test ✅` 回路测试
  - 新增 `to_agent` 分支的插入位置和优先级
  - Bot 回复到 `_inbox:server` 的处理位置（`handle_broadcast` 还是新增函数）

- **消息处理流程**
  - 派活流程：接收 → 检测 `to_agent` → 隐藏发件人 → 广播到目标
  - Bot 回复流程：接收 → 前缀匹配 → 通知 PM / 入库（无匹配）
  - PM 通知流程：构造通知 payload → `_broadcast_to_channel` → PM inbox

- **DISPATCH_SENDER_ID 配置**
  - config.py 环境变量名、默认值、读取方式

- **文件修改清单**
  - `server/main.py` 具体插入行号和逻辑
  - `server/config.py` 新增配置项

- **安全考虑**
  - `to_agent` 字段校验（防止伪造/注入）
  - 隐藏发件人字段覆盖不泄露原始 `from_agent`
  - 无关消息不漏转

---

## Step 3 编码（爱泰）

等待 Step 2 架构方案确定后执行。预计 4 个子步骤：

| 子步 | 内容 | 涉及文件 |
|:----:|:-----|:---------|
| **3.1** | config.py 新增 `DISPATCH_SENDER_ID` | `server/config.py` |
| **3.2** | `_handle_server_query` 扩展 — 检测 `to_agent` 字段，派活路由，隐藏发件人 | `server/main.py` |
| **3.3** | 新增 Bot 回复处理 — `_inbox:server` 消息前缀匹配、PM 通知、无关消息入库 | `server/main.py` |
| **3.4** | 本地验证 — 用测试脚本走一遍完整派活→ACK→完成→退回→无前缀链路 | 测试脚本 |

**注意事项：**

- 每子步独立提交
- 已有功能不受影响：`test ✅` 回路测试、`!` 查询命令保持正常
- 旧直达派活继续可用（兼容期），直到全部切换后删除

---

## Step 4 代码审查（小周）

审查重点：

| 审查项 | 说明 |
|:-------|:------|
| 发件人隐藏 | 转发 payload 的 `from_name`/`from_agent` 是否被正确替换 |
| 前缀匹配 | `startswith()` 匹配是否精准，会不会误触发 |
| 无关消息 | 无匹配前缀的消息是否仅入库，不转发不回复 |
| DISPATCH_SENDER_ID | 配置读取是否正确，PM inbox 地址是否正确 |
| `to_agent` 校验 | 是否有基本的字段存在性校验，防空值 |

---

## Step 5 测试验证（泰虾）

### 8 项验收

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | PM 发 `_inbox:server` 带 `to_agent: ws_xxx`，目标 bot 收到任务 | WS 直连测试 |
| 2 | 目标 bot 收到消息 `from_name` 是 `系统`，不是 `小谷` | 检查 payload |
| 3 | Bot 回复 `收到 ✅` → Server 转发通知到 PM inbox | 检查 PM 收件箱 |
| 4 | Bot 回复 `已完成 ✅` → Server 转发通知到 PM inbox | 检查 PM 收件箱 |
| 5 | Bot 回复 `退回 🔄` → Server 转发通知到 PM inbox | 检查 PM 收件箱 |
| 6 | Bot 回复 `失败 ❌` → Server 转发通知到 PM inbox | 检查 PM 收件箱 |
| 7 | Bot 回复无前缀消息 → 不转发不回复，但 DB 可查 | 查 messages.db |
| 8 | `test ✅` 回路测试 + `!` 查询命令照常工作 | 发 test / ! 验证 |

---

## Step 6 部署（小爱）

1. 合并 `dev` → `main`
2. Docker build 新镜像
3. 启动容器（WSS 核心 8765 + Web 服务 8766）
4. 设置环境变量 `DISPATCH_SENDER_ID=ws_f26e585f6479`
5. 验证全链路

---

## 已知风险

| 风险 | 缓解 |
|:-----|:------|
| `to_agent` 字段为空时误触派活分支 | 代码中检查 `to_agent` 有效性（非空 + 合法 agent_id） |
| Bot 回复无前缀消息以为 server 没收到 | 消息已入库，可查 `messages.db` 确认 |
| 隐藏发件人后 bot 不知上下文 | 任务内容在 `content` 中完整传递；如需追问，bot 回复到 `_inbox:server`，Server 中继给 PM |
| 前缀匹配过于严格导致误判 | 前缀含特殊符号（✅、🔄、❌），减少自然语言误触发 |
