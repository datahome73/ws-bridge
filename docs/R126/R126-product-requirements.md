# R126 需求文档 — 场景匹配规则提取（场景匹配规则模块化）

> **轮次：** R126
> **类型：** 代码重构轮（细粒度提取）
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 草稿待审

---

## §1 背景与问题

### 现状

`main.py` 当前 **4934 行 / 97 个函数**，是 ws-bridge 项目中最大的文件。经历了 R82→R125 的功能叠加后，main.py 承担了三种不同的职责：

| 职责 | 行数估算 | 函数数 |
|:-----|:--------:|:------:|
| 🔌 WebSocket 连接管理（handler/注册/认证） | ~800 行 | ~12 |
| 📡 **场景匹配 + 路由规则（本轮目标）** | **~600 行** | **~20** |
| 🛠️ 管线状态机 + 工具函数 | ~3500 行 | ~65 |

其中 **场景匹配与路由规则** 是最适合独立和维护性收益最高的部分——因为它本质上是**声明式规则**（满足什么条件→做什么事），天然适合以「规则表」形式存在。

### 痛点

| 痛点 | 描述 | 影响 |
|:----|:-----|:------|
| **P1** | 当前有 7 条 inbox 中继规则（`收到 ✅`/`已完成 ✅`/`退回 🔄`/`失败 ❌`/`##命令`/`!命令`/`test ✅`）分散嵌入在 `_handle_server_relay()` 的 if/elif 链中，**增加一条规则需要全文理解 240 行连续逻辑** | 新规则难以添加，容易破坏现有规则的优先级 |
| **P2** | 大厅前缀分类（📢/📋/🆘/@mention/普通文本）实现在 `_classify_lobby_message()` + `handle_broadcast()` 的两个独立代码段中，**分类逻辑和路由动作未分离** | 修改大厅路由需要同时修改两处 |
| **P3** | `##` 命令的解析和路由（`_handle_hash_cmd` + 6 个子 handler）与 `inbox-message-protocol.md` §7 中的协议文档**格式不一致**——文档写的是协议规范，代码写的是实现细节，两者维护不同步 | 添加新 `##` 命令时文档和代码容易脱节 |
| **P4** | 每条规则的**优先级排序**（`_handle_server_relay` 中 test ✅ > to_agent > ## > PM 守卫 > 收到 ✅ > 已完成 ✅ > 退回 🔄 > 失败 ❌ > ! > 无匹配）没有显式声明，靠代码的顺序隐式表达 | 阅读者需要逐行阅读才能理解整个处理优先级 |

### 目标

```
当前                        →  目标
main.py (4934 行)              main.py (~4300 行)
├── WS 连接管理                  ├── WS 连接管理
├── 🔴 场景匹配规则 (~600 行)    ├── (调用规则引擎)
├── 管线状态机                   ├── 管线状态机
└── 工具函数                     └── 工具函数
                               +
                               scenario_matcher.py (~400 行)
                               ├── 规则表（显式声明优先级）
                               ├── 7 条 inbox 中继规则
                               ├── 4 条大厅前缀规则
                               └── 6 条 ## 命令规则
```

---

## §2 核心设计：HandlerRule Schema

### 2.1 规则定义

```python
@dataclass
class HandlerRule:
    """一条场景匹配规则。

    - match: 匹配函数 (content, msg, agent_id) → bool
    - handle: 处理函数 (ws, agent_id, msg, matched_info) → bool
    - priority: 优先级（数字越小越优先）
    - name: 规则名称（用于日志和调试）
    - protocol_ref: 对应的协议文档章节（可选）
    """
    match: Callable[[str, dict, str], bool | Any]
    handle: Callable[[Any, str, dict, Any], Awaitable[bool]]
    priority: int
    name: str
    protocol_ref: str = ""
```

### 2.2 规则表（规则表定义）

所有规则在模块加载时注册到 `_RULES: list[HandlerRule]` 列表，按 `priority` 升序排序。

### 2.3 现有规则的优先级映射

| 优先级 | 当前顺序 | 规则 | 协议文档 |
|:------:|:---------|:-----|:---------|
| 10 | 1st | `test ✅` 回路测试 | §7.1 |
| 20 | 2nd | `to_agent` 派活路由 | §7.2 |
| 30 | 3rd | `##` 命令 | §7.3 |
| 35 | — | PM 安全守卫（拒绝 PM 本人发 `_inbox:server`） | §7.4 |
| 40 | 4th | `收到 ✅` / `ACK ✅` PM 通知 | §7.5 |
| 50 | 5th | `已完成 ✅` / `✅ 完成` 自动确认 | §7.6 |
| 60 | 6th | `退回 🔄` 驳回回退 | §7.7 |
| 70 | 7th | `失败 ❌` 告警通知 | §7.8 |
| 80 | 8th | `!` 命令透传 | §7.9 |
| 90 | 9th | 无匹配 → 入库留痕 | §7.10 |

### 2.4 `##` 命令子规则（在 `##` 规则内部路由）

| 子命令 | 去往 | 协议文档 |
|:-------|:-----|:---------|
| `##start##R{N}` | `_handle_hash_start` | §7.3.1 |
| `##status##R{N}` | `_handle_hash_status` | §7.3.2 |
| `##stop##R{N}` | `_handle_hash_stop` | §7.3.3 |
| `##advance##R{N}` | `_handle_hash_advance` | §7.3.4 |
| `##archive##R{N}` | `_handle_hash_archive` | §7.3.5 |
| `##help` | 显示帮助 | §7.3.6 |

### 2.5 大厅前缀规则

| 优先级 | 前缀 | 动作 |
|:------:|:-----|:-----|
| 100 | `📢` 公告 | admin-only 广播 |
| 110 | `📋` 点名 | admin/ws-admin 可发 |
| 120 | `🆘` 求助 | admin-only |
| 130 | `@mention` | 定向发送 + admin 副本 |
| 140 | 普通文本 | 拒绝（拦截） |

---

## §3 集成方案

### 3.1 改动点

| 文件 | 操作 | 说明 |
|:-----|:------|:------|
| `server/ws_server/**scenario_matcher.py**` | **新建** | 规则表 + 调度引擎 ~400 行 |
| `server/ws_server/main.py` | 修改 | 替换 `_handle_server_relay` 为 `scenario_matcher.dispatch()` |
| `server/ws_server/main.py` | 删除 | 移除 `_handle_server_relay()` / `_handle_hash_cmd()` / `_classify_lobby_message()` 中的硬编码规则体 |
| `server/ws_server/main.py` | 保留存根 | 保留 `_handle_hash_start()` / `_handle_hash_advance()` / `_handle_hash_archive()` / `_handle_hash_status()` / `_handle_hash_stop()` / `_handle_reject()` 等**具体处理函数**（这些是业务逻辑，不是规则） |
| `docs/inbox-message-protocol.md` | 同步 | §7 规则表链接到 scenario_matcher.py 的规则定义 |
| `docs/R126/WORK_PLAN.md` | 新建 | Step 分派计划 |

### 3.2 集成步骤

```
Step 1: PM 审核本需求文档 → 推 dev
Step 2: Arch 编写 scenario_matcher.py 的规则表架构
Step 3: Dev 将现有规则逐一搬入 scenario_matcher.py + 验证无退化
Step 4: Review 审查代码结构
Step 5: QA 验收 + 双向通信测试
Step 6: Ops 合入 main 部署
```

### 3.3 向前兼容保证

| 保证 | 说明 |
|:-----|:------|
| **消息格式零变更** | 每条规则处理的 content 格式不变，`to_agent` 字段不变，所有协议不变 |
| **优先级零变更** | 规则表显式声明优先级，与现有代码顺序完全一致 |
| **handler 签名零变更** | `_handle_server_relay` 的调用方（`handler()` 和 `ws_handler()`）只改调用名，不改签名 |
| **双入口同步** | `handler()` 和 `ws_handler()` 两处都改为调用 `scenario_matcher.dispatch()`，不再需要维护两份 `_handle_server_relay` 副本 |

### 3.4 双入口同步（关键）

当前 `_handle_server_relay` 在 `main.py` 中有**两份完全相同的副本**（L3179 和未知位置）。R126 提取后：

```python
# main.py handler() 和 ws_handler() 两处统一调用：
if await scenario_matcher.dispatch(ws, agent_id, msg):
    continue
```

**不再需要维护两份副本。** 这是本次提取的核心收益之一。

---

## §4 改动范围估算

| 文件 | 新增 | 删除 | 修改 | 净变化 |
|:-----|:----:|:----:|:----:|:------:|
| `scenario_matcher.py` | ~400 行 | — | — | +400 |
| `main.py` | 调用 ~5 行 | `_handle_server_relay` ~240 行 | ~10 行 | **-225 行** |
| `docs/inbox-message-protocol.md` | §7 映射表 ~30 行 | — | 小幅更新 | ~+30 |
| **合计** | **~435** | **~240** | **~40** | **~+235 净增** |

> 净增 235 行主要来自规则表的结构化定义、文档和注释。每新增一条规则只需在表中加一行，不需要理解 240 行 if/elif 链。

---

## §5 验收标准

### SC-N: 场景匹配规则提取（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| SC-1 | `scenario_matcher.py` 存在且可导入，`from .. import scenario_matcher` 无 ImportError | 功能 | P0 |
| SC-2 | 规则表 `_RULES` 按 priority 升序排序，遍历时按顺序检查匹配 | 功能 | P0 |
| SC-3 | `test ✅` 回路测试：向 `_inbox:server` 发 `test ✅`，收到回路确认 | 功能 | P0 |
| SC-4 | `to_agent` 派活：向 `_inbox:server` 发带 `to_agent` 的消息，目标 agent 收到 | 功能 | P0 |
| SC-5 | `##` 命令：`##status##R125` 返回管线状态 | 功能 | P0 |
| SC-6 | `##start##R126##task=xxx` 创建管线并派活 Step 1 | 功能 | P0 |
| SC-7 | `##archive##R125` 归档已完成管线 | 功能 | P0 |
| SC-8 | `收到 ✅` / `ACK ✅` 转发 PM | 功能 | P0 |
| SC-9 | `已完成 ✅` / `✅ 完成` 推进管线 step | 功能 | P0 |
| SC-10 | `退回 🔄` 触发状态回退 | 功能 | P0 |
| SC-11 | `失败 ❌` 转发 PM | 功能 | P0 |

### LO-N: 大厅前缀（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| LO-1 | `📢` 公告：admin 可发，member 拒绝 | 功能 | P0 |
| LO-2 | `📋` 点名：admin/ws-admin 可发 | 功能 | P0 |
| LO-3 | `🆘` 求助：admin-only | 功能 | P0 |
| LO-4 | `@mention`：定向发送 | 功能 | P0 |
| LO-5 | 普通文本：拒绝（"需要明确类型"） | 功能 | P0 |

### RV-N: 回归验证（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| RV-1 | `handler()` 入口（legacy websockets）和 `ws_handler()` 入口（aiohttp 生产）都走 scenario_matcher.dispatch()，不再维护两份 `_handle_server_relay` | 校验 | P0 |
| RV-2 | 所有 10 条规则的 **返回语义不变**：`True` = 已处理（continue），`False` = 未匹配（继续路由） | 验收 | P0 |
| RV-3 | PM 安全守卫：PM 本人（agent_id == DISPATCH_SENDER_ID）发普通消息到 `_inbox:server` 时返回错误 | 功能 | P0 |

### DO-N: 文档同步（P1）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| DO-1 | `inbox-message-protocol.md` §7 新增规则优先级表 | 文档 | P1 |
| DO-2 | 每条规则的 `protocol_ref` 字段指向协议文档对应章节 | 代码+文档 | P1 |
| DO-3 | `scenario_matcher.py` 模块 docstring 含「协议文档见 docs/inbox-message-protocol.md」指引 | 文档 | P1 |

---

## §6 不做事项（不做事项）

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不搬业务逻辑函数** | `_handle_hash_start()`、`_handle_reject()`、`_try_advance_pipeline()` 等业务执行函数继续留在 `main.py`（或后续搬入 `commands/`）。本轮只搬**匹配规则 + 调度引擎** |
| ❌ | **不改变 handler() 整体结构** | `handle_broadcast()` 中的大厅路由（📢📋🆘@）暂不提取。原因是这些规则依赖 handle_broadcast 的局部变量（`users`、`admin_ids`、`_connections`），提取收益不如 inbox 中继规则高。留待 R127+ 处理 |
| ❌ | **不引入插件机制** | 暂不做热加载 / 动态注册 / 插件发现。规则表在模块初始化时静态构建即可 |
| ❌ | **不重构大厅前缀分类** | `_classify_lobby_message()` 和 `handle_broadcast` 的大厅路由段逻辑提取后移 |
| ❌ | **不改 inbox-message-protocol.md 的协议定义** | 只加规则映射表，不改已有的协议格式（§1-§6、§8 不动） |
| ❌ | **不在 scenario_matcher 中新增规则** | 只搬现有规则，不新增。新增规则（如 `##resume` / `##skip`）是另一轮的事 |
| ❌ | **不改变 `_handle_server_query`（!命令）** | `!` 命令在 `_handle_server_relay` 中只做了透传（return False），不解处理。实际处理在 `handle_broadcast` 的 `_handle_server_query` 中，不在本轮范围 |

---

## §7 验收检查表（汇总）

### 提取前 → 提取后对比

| 维度 | 提取前 | 提取后 |
|:-----|:-------|:-------|
| `main.py` 行数 | 4934 行 | ~4300 行（-225 规则代码 + ~50 调用/导入） |
| 规则新增难度 | 理解 240 行 if/elif 链 | 在表中加一行 `HandlerRule(...)` |
| 规则优先级 | 靠代码顺序隐式表达 | `priority` 字段显式声明 |
| 文档同步 | 手动维护 | `protocol_ref` 字段链接到协议文档 |
| 双入口维护 | 两份 `_handle_server_relay` 副本 | 一份 `scenario_matcher.dispatch()` |
| 协议文档版本 | v3.1 | v3.2（+ 规则优先级映射表） |

### 文件改动清单

| 操作 | 文件 | 估算行数 |
|:-----|:-----|:--------:|
| ✅ 新建 | `server/ws_server/scenario_matcher.py` | ~400 行 |
| ✅ 修改 | `server/ws_server/main.py` | ~15 行（替换调用 + 清理） |
| ✅ 修改 | `docs/inbox-message-protocol.md` | ~+30 行 |
| ✅ 新建 | `docs/R126/WORK_PLAN.md` | — |
| ❌ 不碰 | `server/ws_server/handler.py`（已不存在） | — |

### 验收计数

| 分组 | P0 项 | P1 项 | 合计 |
|:-----|:-----:|:-----:|:----:|
| SC 规则提取 | 11 | 0 | 11 |
| LO 大厅前缀 | 5 | 0 | 5 |
| RV 回归验证 | 3 | 0 | 3 |
| DO 文档同步 | 0 | 3 | 3 |
| **合计** | **19** | **3** | **22** |
