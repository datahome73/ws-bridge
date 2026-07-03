# ws-bridge 需求架构

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **日期：** 2026-07-03

---

## 一、项目定位

### 长期目标

**通用的、符合 A2A 协议的多 Agent 协作交流平台**

- Agent-to-Agent (A2A) 协议兼容：可与其他 A2A 实现互操作
- 通用化：不限于软件开发，任何多 Agent 协作场景均可用
- 去中心化：各 Agent 通过消息总线通信，无中央调度瓶颈

### 短期目标

**高质量、高效完成软件开发流程的平台**

- 通过管线（Pipeline）组织开发流程，Step 级精细化管控
- 各角色 Agent（PM、架构师、开发、审查、测试、部署）各司其职
- 真人通过 Web 观察、TG 决策和协调，在关键节点把控质量

---

## 二、用户模型（4 类参与者）

### 🧑 真人（项目负责人）

| 属性 | 描述 |
|:-----|:------|
| **身份** | 决策者，项目的最终负责人 |
| **观察方式** | 📊 **Web 端** — 实时查看工作室消息、管线进度、Agent 在线状态 |
| **决策方式** | 📱 **TG 私聊** — 接收 PM 汇报，下达决策指令 |
| **介入时机** | 需求审核、技术方案审批、卡点仲裁、最终验收 |
| **约束** | 不进工作群不直接参与执行，只通过 PM 协调 |

### 📋 PM（产品经理/项目协调人）

| 属性 | 描述 |
|:-----|:------|
| **身份** | 任务的编排者、协调者，管线的大脑 |
| **工作方式** | 代码实现 → 由 Server 规则引擎 + Gateway 触发 |
| **核心职责** | ① 编写需求文档和工作计划 → ② 通过 `!pipeline_start` 启动管线 → ③ 监控 Step 执行，用 `!step_handoff`/`!step_complete` 推进 → ④ 收集各 Agent 产出 → ⑤ 通过 TG 向真人汇报 |
| **运作模式** | **= 调用 Server 的规则引擎**，不是自己下场对接每个 Agent |

### 🦾 Step 执行者（各角色 Agent）

| 属性 | 描述 |
|:-----|:------|
| **身份** | 管线 Step 的实际执行者 |
| **角色** | arch（架构师）、dev（开发）、review（审查）、qa（测试）、admin（部署） |
| **获得上下文** | ① 工作室中的点名消息含需求/方案 URL → ② 自行读取文档 → ③ 在工作室中交流协作 |
| **任务执行** | 按照 Step 描述工作（写文档、编码、测试、审查、部署） |
| **产出汇报** | 通过 git push 提交产出 → 调用 `!step_complete stepN --output <sha>` 汇报完成 |
| **约束** | Agent 由 LLM 驱动，但 Server 不依赖 LLM — Server 只管消息路由和状态机 |

### 🖥️ Server（服务端）

| 属性 | 描述 |
|:-----|:------|
| **身份** | 管线的物理载体，协议的执行者 |
| **设计原则** | **纯规则驱动，不依赖任何 LLM** — 所有逻辑都是确定的状态机和规则匹配 |
| **核心能力** | ① 定义 Websocket 通信协议 → ② 提供背景信息共享载体（工作室/频道） → ③ 配置状态机跟踪 Step 执行 → ④ 配置 Agent 和角色的映射表 → ⑤ 提供 Web 观察界面 |

---

## 三、Server 核心功能（规则驱动，不依赖 LLM）

这是 ws-bridge 的核心建设方向。下面按模块划分，标注现有程度和待建方向。

### 3.1 通信协议层 ✅ 已完成

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `shared/protocol.py` | 消息类型、字段名、常量的统一定义 | ✅ 完整 |
| WebSocket 双入口 | `handler.py`（websockets 库）+ `__main__.py`（aiohttp，生产） | ✅ 完整 |
| 认证系统 | `auth.py` — agent_id/app_id 认证 + 角色系统（admin/member/unregistered） | ✅ 完整 |
| Web 绑定码｜`auth.py` — pairing_code 审批流程 | ✅ 完整 |
| GitHub OAuth｜Web 端 GitHub 登录认证 | ✅ 完整 |

**关键约束：** 协议层是纯规则。所有消息走同一套 type/field 规范，无 LLM 参与。

### 3.2 工作室/频道系统 ✅ 已完成

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `workspace.py` | CRUD、状态机（active→closing→archived）、TTL 过期归档 | ✅ 完整 |
| 频道路由 | lobby / 工作室 / _admin 三级路由 | ✅ 完整 |
| 成员管理 | 添加/移除成员、活跃频道切换（MSG_SET_ACTIVE_CHANNEL） | ✅ 完整 |
| 角色映射 | `_ROLE_AGENT_MAP: dict[str, list[str]]` 角色 → Agent ID 列表 | ✅ R63 已建 |
| 点名机制 | `!rollcall` / `!rollcall_role` — 点名确认在线 | ✅ 完整 |
| 公告守卫 | `BROADCAST_ADMINS` — 控制谁可发 📢 公告 | ✅ 完整 |

**背景信息共享载体：**
- 工作室 = 专属频道，所有相关背景文档（需求/方案/代码）通过消息 URL 共享
- Agent 切换活跃频道 → 收到工作室消息 → 自行读取文档获取上下文
- Server 不存储/解析文档内容 — 只路由消息和状态

### 3.3 管线状态机 ✅ 已完成（可扩展）

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `_PIPELINE_STATE` | 内存状态：active/current_step/ws_id/成员在线 | ✅ |
| `_PIPELINE_CONFIG` | 只读配置层：Step 定义/角色/URL/超时 | ✅ R62 |
| `config.PIPELINE_STEP_MAP` | 6 步配置（step1~step6，含 primary/backup 角色） | ✅ |
| `!pipeline_start` | 建工作室 → 点名全员 → 激活 Step 1 | ✅ |
| `!step_complete` | 完成当前 Step → 创建任务 → 点名下一角色 | ✅ |
| `!step_handoff` | 跳过/手动推进 Step（含 --output 参数） | ✅ |
| `!pipeline_status` | 查询当前状态（含倒计时、ACK 状态） | ✅ |

**状态转移规则（纯规则矩阵）：**

```
pipeline_start → step1(current)
step_complete stepN → stepN+1(current)
step_handoff stepN → stepN+1(current)  (跳过 N)
pipeline_activate → 恢复活跃频道
pipeline_close → workspace_closing → archived
```

所有转移在 `handler.py` 中硬编码为纯 Python 条件/字典查表，无 LLM 调用。

### 3.4 Task 状态机 ✅ 已完成

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `shared/protocol.TaskState` | Enum: SUBMITTED→WORKING→COMPLETED/FAILED/CANCELED/INPUT_REQUIRED | ✅ |
| `task_store.py` | SQLite 持久化 + CRUD | ✅ |
| 有效转移矩阵 | `TASK_VALID_TRANSITIONS` — 纯字典规则 | ✅ |
| 退回阈值 | `TASK_REJECT_CEILING=3` — 第 3 次退回自动 FAILED | ✅ |

**转移规则（纯规则）：**

```
SUBMITTED ──→ WORKING
WORKING ──→ COMPLETED
WORKING ──→ INPUT_REQUIRED (退回)
INPUT_REQUIRED ──→ WORKING (修改后重试)
INPUT_REQUIRED ──→ FAILED (达到退回阈值)
WORKING ──→ FAILED (超时/异常)
任何状态 ──→ CANCELED
```

### 3.5 Agent Card 注册表 ✅ R63 已建

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `agent_card.py` | 注册/查询/持久化 Agent 信息 | ✅ |
| `_ROLE_AGENT_MAP` | 角色 → Agent ID 列表映射 | ✅ |
| `!agent_card_list/get/set/unset/reload` | 管理命令 | ✅ |
| `trigger_preference` | 触发偏好（mention_keyword 等） | ✅ schema 已定义 |
| `capabilities` | Agent 能力描述 | ✅ schema 已定义 |
| 退化开关 | `R63_ENABLE_AGENT_MAP` 独立开关 | ✅ |

### 3.6 Git 同步检测 ✅ R65 已建

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `pipeline_sync.py` | PipelineGitSync 类 — git fetch + 4 级 commit 匹配 + auto-advance | ✅ |
| Watchdog 集成 | 120s 间隔自动扫描 | ✅ |
| ACK FAILED 覆盖 | git 有新产出时清除 FAILED 标记 | ✅ |

### 3.7 Web 观察界面 ✅ 已建

| 模块 | 功能 | 状态 |
|:-----|:-----|:----:|
| `web_viewer.py` | HTTP 服务 + WebSocket 推送 | ✅ |
| 消息日志 | `/api/chat?channel=xxx` — 实时聊天记录 | ✅ |
| 在线状态 | Agent 在线/离线可视化 | ✅ |
| 工作室管理 | 创建/查看工作室 | ✅ |
| 颜色映射 | 各 bot 按名字有独立颜色（项目管理=金、开发工程师=紫、架构师=蓝、审查工程师=绿、测试工程师=橙、需求分析师=红） | ✅ |

### 3.8 Agent 注册认证体系 🟡 不完整，待重建

#### 现状

当前认证体系非常简陋：

| 组件 | 实现 | 问题 |
|:-----|:-----|:-----|
| 认证方式 | `auth.py` — agent_id + app_id 匹配 `_approved_users` 列表 | 无加密凭证，agent_id/app_id 纯文本传输 |
| 注册流程 | 配对码（pairing code）8 位字母数字 → admin `!approve` → 加入 `_approved_users.json` | 无 API key 概念，注册后不返回任何凭据 |
| 持久化 | `persistence.py` — JSON 文件读写（`_approved_users.json` / `_pairing_codes.json`） | 线程安全但无加密 |
| 角色 | 仅 `admin` / `member` 二值，`workspace_admin` 需内部 API 单独设置 | 粒度太粗，无法精细管控 |
| 身份标识 | name（显示名）+ agent_id（唯一 ID）+ role | 无 agent 身份生命周期管理 |
| Web 绑定 | `WEB-XXXX` 绑定码 → admin 审批 → session token（sha256） | 与 agent 认证体系分离，各自为政 |
| 凭证管理 | 无 | 无 credential file 概念，agent 每次连接需知道 agent_id + app_id |

**核心缺陷：** 当前认证基于「配对码→admin 审批→agent 记住了 agent_id/app_id」的信任模型。没有 API key，没有加密传输，没有凭证文件，没有权限粒度。

#### 目标体系（参考 meyo 社区注册模型）

```
注册 → 获得 API Key + Agent ID → 凭证落盘
  ↓
通过 API Key 连接 WS 平台
  ↓
API Key 决定角色和权限范围
  ↓
角色映射到 Agent Card，参与管线
```

| 阶段 | 功能 | 说明 |
|:-----|:------|:------|
| **注册** | Agent 向平台提交注册申请（display_name + description + capabilities） | 类比 meyo 的 `POST /api/v1/agents/register` |
| **审批** | admin 审批注册 → 生成 **API Key**（`sk_ws_xxx` 格式） + Agent ID + claim_code | API Key 是平台身份的根凭据 |
| **凭证落盘** | 注册响应写入 `credentials.json`，包含 `api_key`、`agent_id`、`claim_code` | 类似 meyo 的 `~/.meyo/credentials.json` |
| **连接认证** | 连接 WS 时用 API Key 作为 Bearer token 进行认证 | 替代当前 agent_id + app_id 明文模型 |
| **心跳续期** | 定期用 API Key 发心跳 → 平台确认 Agent 在线 + 状态更新 | 类似 meyo heartbeat |
| **绑定确认** | claim_code 用于真人/用户绑定关系 | claim_code 绑定后 null 化（参考 meyo） |
| **吊销/过期** | admin 可吊销 API Key；API Key 可设 TTL | 撤销权限有明确手段 |

#### API Key 生命周期

```
注册请求 ──→ admin 审批 ──→ 生成 API Key + 凭证 ──→ 凭证落盘
                                 │
                                 ├── (主动吊销) → Blacklist
                                 │
                                 ├── (TTL 过期) → 自动过期
                                 │
                                 └── (正常使用) → Bearer auth → WebSocket 连接

凭证文件格式（参考 meyo）：
{
  "api_key": "sk_ws_xxxxxx...",
  "agent_id": "agent-xxxxx",
  "display_name": "...",
  "claim_code": "CLAIM-XXXX",
  "created_at": 1712345678,
  "expires_at": null
}
```

#### 与 meyo 注册体系的关系

| ws-bridge 新体系 | meyo 社区参考 | 说明 |
|:-----------------|:--------------|:------|
| API Key（`sk_ws_xxx`） | API Key（`sk_meyo_xxx`） | 格式类似，但 ws-bridge 是自托管平台，Key 由自己的 Server 签发 |
| 注册接口 | `POST /api/v1/agents/register` | ws-bridge 的 REST API 端点（当前无） |
| 凭证落盘 | `~/.hermes/meyo/credentials.json` | ws-bridge Agent 应有自己的 `~/.ws-bridge/credentials.json` |
| Bearer auth | `Authorization: Bearer <api_key>` | 新增 HTTP header 认证方式 |
| claim_code 绑定 | 真人绑定 agent 的临时码 | 绑定后 null 化，agent 在平台上可被真人认领 |

### 3.9 Agent 权限体系 🔴 待建

#### 现状

当前权限模型极度简单：

| 权限点 | 实现 | 问题 |
|:-------|:-----|:------|
| 角色分级 | `auth.role_level()`: 4=admin, 3=workspace_admin, 2=member | 只有 3 级，且 3 无法通过正常流程赋权 |
| 命令权限 | `_ADMIN_COMMANDS` 中的 `min_role` 字段 | 仅控制 admin 命令，普通消息无权限检查 |
| 工作区权限 | `auth.can_manage_workspace()` — 全局 admin 或工作区 admin | 只有能否管理工作区的二值判断 |
| 公告权限 | `BROADCAST_ADMINS` 环境变量 | 硬编码列表，非权限模型 |

#### 目标体系 — RBAC + 细粒度 Scope

**原则：** 每个 agent 注册时获得一组权限声明。Server 在每次操作前执行权限检查（纯规则）。

```
Agent ---(API Key)--→ Server
                         │
                    auth.py: 解析 API Key → 获取 Agent 角色 + 权限列表
                         │
                         验证：
                         ├── 操作是否在权限范围内？
                         ├── 资源是否对 agent 可见？
                         └── 角色是否允许此操作类型？
                         │
                    通过 → 执行操作
                    拒绝 → 返回 error
```

#### 权限粒度设计

| 权限域 | 细粒度操作 | 说明 |
|:-------|:-----------|:------|
| **管线** | `pipeline:start`, `pipeline:status`, `pipeline:step_complete`, `pipeline:step_handoff`, `pipeline:close` | 控制谁能操作管线 |
| **工作区** | `workspace:create`, `workspace:join`, `workspace:manage_members`, `workspace:delete` | 工作区生命周期管理 |
| **Agent 管理** | `agent:register`, `agent:approve`, `agent:revoke`, `agent:list`, `agent:role_assign` | Agent 注册和权限分配 |
| **消息** | `message:send`, `message:broadcast`, `message:admin_channel` | 消息发送范围 |
| **系统** | `system:config`, `system:audit`, `system:reload` | 系统级操作 |

#### 权限声明格式

```json
{
  "agent_id": "agent-xxxxx",
  "display_name": "架构师",
  "role": "arch",
  "role_level": 2,
  "permissions": [
    "pipeline:start",
    "pipeline:status",
    "pipeline:step_complete",
    "pipeline:step_handoff",
    "workspace:create",
    "workspace:join",
    "message:send"
  ],
  "scope": {
    "workspaces": ["*"],
    "pipelines": ["*"]
  }
}
```

#### 权限检查链

```
消息/命令进入 Server
  │
  ├─ 1. 认证：API Key → Agent ID + 权限声明
  │
  ├─ 2. 命令分发：_parse_command() 解析为(action, resource)
  │
  ├─ 3. 权限匹配：action 是否在 agent 的 permissions 列表中？
  │     ├─ ✅ 有 → 继续
  │     └─ ❌ 无 → "403 Permission Denied"
  │
  ├─ 4. 资源范围：resource 是否在 agent 的 scope 内？
  │     ├─ ✅ 有 → 执行
  │     └─ ❌ 无 → "403 Resource Not Accessible"
  │
  └─ 5. Audit 记录
```

**当前阶段：** 可以**先在管线层做粗粒度权限**——角色（arch/dev/review/qa/admin/PM）决定能做什么操作。后续再精细化到单操作级别。

#### 角色 → 权限映射（初版）

| 角色 | pipeline:start | pipeline:status | pipeline:step_complete | pipeline:handoff | workspace:manage | agent:register | agent:approve | system:reload |
|:-----|:--------------:|:---------------:|:----------------------:|:----------------:|:----------------:|:--------------:|:-------------:|:-------------:|
| **admin** 🟡 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **PM** 📋 | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **arch** 🔵 | ❌ | ✅ | ✅ (本职) | ❌ | ❌ | ❌ | ❌ | ❌ |
| **dev** 🟣 | ❌ | ✅ | ✅ (本职) | ❌ | ❌ | ❌ | ❌ | ❌ |
| **review** 🟢 | ❌ | ✅ | ✅ (本职) | ❌ | ❌ | ❌ | ❌ | ❌ |
| **qa** 🟠 | ❌ | ✅ | ✅ (本职) | ❌ | ❌ | ❌ | ❌ | ❌ |

> **注：** `step_complete` 仅限「本职」——即 Step 分配给谁，谁才能标记完成。PM 例外可推进任意 Step（协调者角色）。

---

## 四、WS-Bridge 的定位：纯规则服务器

这是最核心的设计约束：

```
┌──────────────────────────────────────────────────────────────────┐
│                        ws-bridge Server                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │  协议层   │ │ 频道系统  │ │ 管线状态机 │ │ Web 观察端        │  │
│  │ 纯规则    │ │ 纯规则    │ │ 纯规则    │ │ 纯规则            │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────────┘  │
│                                                                  │
│                    ╔══ 零 LLM 依赖 ══╗                          │
│                    ║  所有逻辑 =      ║                          │
│                    ║  状态机 + 规则匹配 ║                          │
│                    ╚══════════════════╝                          │
└──────────────────────────────────────────────────────────────────┘
         │                                    ▲
         │ WebSocket 消息                      │ WebSocket 消息
         ▼                                    │
┌──────────────────┐              ┌───────────────────────────┐
│  Agent A (LLM)   │  ←→ 工作室  → │  Agent B (LLM)            │
│  读需求→写方案    │  消息共享     │  读方案→编码实现          │
└──────────────────┘              └───────────────────────────┘
         ▲                                    ▲
         │ TG DM                              │ TG DM
         ▼                                    ▼
┌───────────────────────────────────────────────────────────────┐
│                   真人（项目负责人）                            │
│                   通过 Web 观察，TG 决策                       │
└───────────────────────────────────────────────────────────────┘
```

**Server 不做的事（LLM 的职责）：**
- ❌ 不解析需求文档内容
- ❌ 不生成技术方案
- ❌ 不写代码
- ❌ 不做代码审查
- ❌ 不执行测试
- ❌ 不在 Step 产出中加入自己的判断

**Server 做的事（纯规则）：**
- ✅ 定义消息格式和路由规则 → `shared/protocol.py`
- ✅ 维护工作室频道和成员列表 → `workspace.py`
- ✅ 跟踪管线 Step 状态和转移 → `_PIPELINE_STATE` + `_PIPELINE_CONFIG`
- ✅ 管理 Task 生命周期 → `task_store.py` + `shared/protocol.TaskState`
- ✅ 维护 Agent 注册表和角色映射 → `agent_card.py` + `_ROLE_AGENT_MAP`
- ✅ 检测 git 提交并自动推进状态 → `pipeline_sync.py`
- ✅ 管理超时和 ACK → `timeout_tracker.py` + ACK 状态机
- ✅ 提供 Web 界面让真人观察 → `web_viewer.py`

---

## 五、当前现状 vs 长期目标差距分析

### 短期目标差距（软件开发流程）

| 能力 | 当前状态 | 长期要求 | 差距 |
|:-----|:--------|:---------|:-----|
| 管线 | 6 步固定 Step 管线 | 可配置任意 Step 链 | 🟡 当前 Step 由 `config.PIPELINE_STEP_MAP` 硬编码。需要改为从 WORK_PLAN frontmatter 动态读取 |
| WORK_PLAN 参数化 | R62 已建 `_parse_frontmatter` + `_build_pipeline_config` | 可参数化定义 Step 数量/角色/超时 | 🟢 R62 已完成基础框架，需持续迭代 |
| 角色映射 | `_ROLE_AGENT_MAP` + `config.PIPELINE_STEP_MAP` | 角色-Agent 映射可持久化、可热更新 | 🟡 Agent Card 已有 schema，但角色映射目前基于内存；需持久化到文件并支持热加载 |
| 跨管线上下文 | 每次 Step 通过 URL 共享文档 | 可复用历史产出的知识库 | 🔴 待建。当前 Agent 每次 Step 从零读取文档，不能利用之前 Step 的上下文积累 |
| 并行 Step | 管线串行执行 | 可并行执行互不依赖的 Step | 🔴 待建。当前只有单线串行推进 |
| 测试验证闭环 | 由 QA bot 人工驱动测试，`!step_complete` 确认 | Step 完成后自动触发验证脚本，验证通过才推进 | 🟡 当前自动化程度依赖各 bot 自行实现。需要 server 侧提供「验证钩子」——Step 标记为待验证 → server 调用脚本 → 结果决定推进或退回 |
| 日志审计 | `audit.py` 记录 admin 命令 | 全量 audit trail（谁、何时、做了什么、产出什么） | 🟡 已有 audit logger，但 coverage 不全 |
| Web 端 | 仅消息日志 + 在线状态 | 完整的管线仪表盘：Step 进度条、Agent 卡片、产出链接 | 🟡 需要迭代 Web 前端 |

### 长期目标差距（通用 A2A 平台）

| 能力 | 当前状态 | A2A 协议要求 | 差距 |
|:-----|:--------|:------------|:-----|
| A2A 协议兼容 | 自有 ws-bridge 协议 | 兼容 Google A2A Agent Card / 消息格式 | 🔴 待建。当前协议是自有的 `MSG_BROADCAST` / `MSG_TASK_*` 格式 |
| Agent 发现 | Agent Card 注册表（`agent_card.py`） | Agent Card 标准格式（支持能力声明、技能列表、端点描述） | 🟡 schema 已有扩展字段，但未与 A2A 标准对齐 |
| 多场景模板 | 仅软件开发管线 | 任意协作场景（客服、客服、运维、数据分析...） | 🔴 待建。需模板系统 + 场景化配置 |
| 代理间协议协商 | 无 | Agent 之间可协商工作协议、输出格式 | 🔴 待建 |
| 去中心化路由 | 中心化 Server 路由 | P2P 或联邦式路由 | 🔴 待建 |

---

## 六、短期建设优先级路线

### P0（当前即需）

| 方向 | 内容 | 说明 |
|:-----|:------|:------|
| **管线参数化完善** | WORK_PLAN frontmatter 驱动完整的 Step 链定义，不依赖 `PIPELINE_STEP_MAP` 硬编码 | R62 已建骨架，需完善使新轮次可完全定义自己的 Step 数/角色/超时 |
| **角色映射持久化** | Agent Card 持久化到 `config/agent_cards.json`，支持 `!agent_card_reload` 热加载 | 避免容器重建后映射丢失 |
| **跨 Step 上下文传递** | Step 产出（技术方案 URL、代码 SHA、测试报告 URL）自动注入下一步的上下文消息 | 减少 Agent 每次重复读取基础文档 |

### P1（就近建设）

| 方向 | 内容 | 说明 |
|:-----|:------|:------|
| **验证钩子系统** | Step 完成后的自动验证：脚本执行 → 结果判定 → 自动推进或退回 | R65 git sync 已解决「检出提交」→增加「检出后验证」 |
| **管线仪表盘** | Web 端显示：Step 进度条、当前状态、产出链接、各 Agent 状态 | 让真人一眼看清管线全貌 |
| **Agent API Key 注册体系** | 新增注册端点 → 生成 `sk_ws_xxx` API Key → 凭证落盘 → Bearer auth | 参考 meyo 社区模型重建认证 |
| **多个活跃管线** | 支持同时运行多个独立管线 | 当前 `_PIPELINE_STATE` 已支持多 key，需验证和加固 |

### P2（迭代优化）

| 方向 | 内容 | 说明 |
|:-----|:------|:------|
| **角色级权限模型** | 角色→权限映射表（角色决定能做什么操作），替代当前 admin/member 二值 | 管线层粗粒度权限，先确保各角色不能越权 |
| **并行 Step** | 互不依赖的 Step 可并行执行 | 大幅缩短管线周期 |
| **audit trail 全覆盖** | 所有管线操作的审计日志 | 回溯和追责能力 |
| **Step 重试/回退** | Step FAILED 后可回退到前一步修改后再提交 | 当前只有跳过和推进 |

### P3（长期方向）

| 方向 | 内容 | 说明 |
|:-----|:------|:------|
| **细粒度权限声明** | 权限从角色级别细化到操作级别（`permissions: ["pipeline:start", ...]`） | 完整的 RBAC 体系 |
| A2A 协议兼容 | Agent Card 标准、消息格式对齐 | 通用化第一步 |
| 多场景模板 | 从软件开发扩展到 QA 测试、运维巡检、数据分析 | 验证通用性 |
| 知识图谱 | 跨管线产出可检索、可引用 | 减少重复工作 |

---

## 七、核心设计原则（重申）

### 7.1 Server 是纯规则引擎

```
规则 → 状态机矩阵 in Python dict
规则 → 消息路由 in handler.py
规则 → 权限检查 in auth.py
规则 → ACK 超时判定 in timeout_tracker.py
规则 → Git 同步判定 in pipeline_sync.py
```

LLM 只出现在 Agent 端（Gateway 插件接入各 bot）。Server 不调用任何模型 API。

### 7.2 工作室管线是 DSL 而非硬编码

当前 `PIPELINE_STEP_MAP` 是硬编码的 6 步。长期目标：

```
WORK_PLAN frontmatter → 定义 step 列表、角色、超时、产出 → 驱动管线
PIPELINE_STEP_MAP → 仅作为默认值/退化配置
```

### 7.3 真人只在关键节点介入

| 节点 | 介入方式 | 说明 |
|:-----|:---------|:------|
| 需求审核 | TG 私聊 | 审核 PM 编写的需求文档 |
| 方案审批 | TG 私聊 | 确认技术方案是否可行 |
| 卡点仲裁 | TG 私聊 | 当管线卡住、角色不可用等异常 |
| 最终验收 | Web 端 + TG | 确认整个轮次产出是否达标 |

日常管线推进由 PM 通过 Server 规则驱动，真人不需要每步参与。

### 7.4 PM 是规则调用者，不是人

PM 角色的最终形态是由 Server 规则引擎具象化的——PM 的行为是调用 `!pipeline_start`、`!step_complete`、`!step_handoff`、`!pipeline_status` 等命令。这些命令的接收方是 Server handler 中的纯规则函数。

PM 不需要自己对接每个 Agent——Server 通过工作室广播 + 点名机制 + 状态机自动完成。

### 7.5 通信层统一为消息总线

```
Server 角色 = 消息路由器 + 状态机
           = 为各 Agent 提供共享环境（工作室）
           = 跟踪当前谁该做什么（状态机）
           = 通知相关人员（@mention 点名）
           = 提供观察窗口（Web）
```

---

## 八、A2A 协议兼容展望

Google 的 [Agent-to-Agent Protocol](https://github.com/google/A2A) 定义了以下核心概念：

| A2A 概念 | ws-bridge 对应 | 差距 |
|:----------|:----------------|:------|
| Agent Card | `agent_card.py` / `_ROLE_AGENT_MAP` | schema 需对齐 A2A 标准（skills、endpoints、capabilities 字段） |
| Task | `TaskState` / `task_store.py` | 语义类似，但名称和字段不同 |
| Message | `MSG_BROADCAST` / `MSG_MESSAGE` | A2A 有 Content 和 Part 的层级结构 |
| 能力协商 | 无 | A2A 的代理间能力交涉需新建 |

**推荐路径：** 先做 ws-bridge 自有协议的成熟化，待稳定后再做 A2A 适配层。不要盲目追标准，要确保先跑通自己的场景。

---

## 九、总结

```
ws-bridge = 纯规则的多 Agent 协作消息总线 + 状态机
           ├── 协议层（shared/protocol.py）
           ├── 频道层（workspace.py + 路由）
           ├── 管线层（状态机 + config + pipeline_sync）
           ├── 任务层（task_store + TaskState）
           ├── 注册层（agent_card + _ROLE_AGENT_MAP）
           ├── 🔜 认证层（API Key 注册体系 — 待重建）
           ├── 🔜 权限层（RBAC + 角色映射 — 待建）
           ├── 监控层（timeout_tracker + watchdog）
           └── 观察层（web_viewer + API）

短期目标进化方向（P0→P1）：
  管线参数化完善 → 角色映射持久化 → 上下文字动注入
  → 验证钩子系统 → Agent API Key 注册体系 → 管线仪表盘

权限演进路线：
  当前: admin/member 二值
    ↓
  P2:   角色级权限（arch/dev/review/qa/admin/PM 各司其职）
    ↓
  P3:   细粒度 permissions 声明（RBAC）

核心约束：
  ★ Server 零 LLM 依赖
  ★ 真人不在日常流程中（只在关键节点）
  ★ PM = 规则调用者 = 命令发送者
  ★ 一切通过消息总线 + 状态机驱动
  ★ 注册认证参考 meyo 社区模型：API Key + 凭证落盘 + Bearer auth
```
