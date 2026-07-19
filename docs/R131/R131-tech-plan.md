# R131 技术方案 — !命令规则化改造（Query-as-##）

> **起草人：** 📐 Arch（小开）
> **版本：** v1.0
> **基线：** dev `45c51ab`（R131 需求 + WORK_PLAN 已合入）

---

## 1. 问题概述

新增 `##query` 规则族到 `scenario_matcher.py`，将 5 个常用查询从 `!` 命令体系迁移到 `##` 规则表。

| # | 问题 | 影响 | 方案 |
|:-:|:-----|:------|:-----|
| P1 | `!` 命令拦截逻辑嵌在 `handle_broadcast()` 中 | 广播函数与命令路由耦合 | 新增 ##query 规则（保留 ! 兼容） |
| P2 | `!` 与 `##` 两套权限检查 | 权限体系割裂 | 统一走 scenario_matcher 规则表 |
| P3 | `_handle_server_query` 硬编码在 main.py | 新增查询需改 main.py | 规则表 + 子命令路由 |
| P4 | ##status/##help 功能不全 | 用户仍需 `!` 查询 | 补全 5 个查询命令 |

---

## 2. 代码审计 — 现有结构

### 2.1 `scenario_matcher.py` 当前结构（260 行）

| 组件 | 行号 | 说明 |
|:-----|:----:|:------|
| HandlerRule dataclass | L27-L41 | match/handle/priority/name/protocol_ref |
| register_rule() | L47-L50 | 注册规则 + 按 priority 排序 |
| dispatch() 引擎 | L60-L92 | 遍历规则表，R102 自动修正 channel |
| match_loopback | L96-L100 | 规则 10: test ✅ |
| match_to_agent | L102-L116 | 规则 20: to_agent 路由 |
| **match_hash_cmd** | **L118-L122** | **规则 30: ## 命令** |
| match_pm_guard → match_fail | L124-L159 | 规则 35-70 |
| match_exclamation | L155-L159 | 规则 80: ! 透传 |
| match_catchall | L161-L163 | 规则 90: 兜底 |
| **handle_hash_cmd** | **L167-L221** | **## 命令分发 + 6 个子路由** |
| classify_lobby_message | L225-L243 | 大厅分类 |
| **_send_reply** | **L247-L260** | **回复到发送者 inbox** |

### 2.2 现有优先级

```
10  loopback (test ✅)
20  to_agent
25  ← [NEW] ##query (本轮新增)
30  ## commands
35  PM guard
40  ACK (收到 ✅ / ACK ✅)
50  Complete (已完成 ✅ / ✅ 完成)
60  Reject (退回 🔄)
70  Fail (失败 ❌)
80  ! commands (透传)
90  Catch-all
```

### 2.3 `handle_hash_cmd` 的循环导入模式（复用）

当前 `handle_hash_cmd` (L167) 使用**函数体内延迟导入**规避循环依赖：

```python
from . import main as _main  # L194 — 函数体内导入，非模块级
# 然后调用:
return await _main._handle_hash_start(round_name, kv, agent_id, ws)
```

**R131 方案复用此模式**：`handle_query` 函数体内 `from . import main as _main`，调用 `_main._handle_server_query()` 或 `_main._ensure_engine().format_context()`。

---

## 3. 核心设计

### 3.1 新增 `match_query`（scenario_matcher.py）

```python
def match_query(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 25: ##query commands.
    Must be priority 25 (between to_agent 20 and ## 30) to intercept
    before the generic ## handler.
    """
    if content.startswith("##query"):
        return content  # pass the full content as matched info
    return False
```

### 3.2 新增 `handle_query`（scenario_matcher.py）

**流程：** 解析子命令 → 权限检查 → 执行 → 回复 inbox

```python
async def handle_query(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    content = matched  # "##query##status##R130"
    parts = content.split("##")
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "📋 **##query 命令**\\n\\n"
            "`##whoami` — 查看自己信息\\n"
            "`##agents` — 列出所有 bot\\n"
            "`##status [R{N}]` — 查询管线状态\\n"
            "`##agent_info <agent_id>` — 查询 bot 详情\\n"
            "`##audit [--limit N]` — 审计日志 (L4+)\\n"
            "`##help` — 显示本帮助"
        )
        return True

    sub_cmd = parts[2].lower()
    params = parts[3] if len(parts) > 3 else ""

    # 权限检查
    level = _get_agent_level(agent_id)
    if level < 1:
        await _send_reply(ws, agent_id, "❌ 权限不足：未注册 bot")
        return True
    if level == 1 and sub_cmd not in ("whoami", "help"):
        await _send_reply(ws, agent_id, f"❌ 权限不足：L1 仅允许 ##whoami 和 ##help")
        return True
    if level < 4 and sub_cmd == "audit":
        await _send_reply(ws, agent_id, "❌ 权限不足：##audit 需要 L4")
        return True

    # 6 个子命令路由（复用 main.py 函数）
    from . import main as _main

    if sub_cmd == "whoami":
        from server.common import auth
        users = auth.get_users()
        info = users.get(agent_id, {})
        name = info.get("name", agent_id[:12])
        await _send_reply(ws, agent_id,
            f"🆔 agent_id: `{agent_id}`\\n"
            f"📛 名称: {name}\\n"
            f"🎚️ 级别: L{level}")
    elif sub_cmd == "status":
        reply = await _format_pipeline_status(params, _main)
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "agents":
        reply = _format_agent_list()
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "agent_info":
        reply = _format_agent_info(params)
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "audit":
        reply = _format_audit_log(params)
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "help":
        await _send_reply(ws, agent_id,
            "📋 **##query 命令**\\n\\n"
            "`##whoami` — 查看自己信息\\n"
            "`##agents` — 列出所有 bot\\n"
            "`##status [R{N}]` — 查询管线状态\\n"
            "`##agent_info <agent_id>` — 查询 bot 详情\\n"
            "`##audit [--limit N]` — 审计日志 (L4+)\\n"
            "`##help` — 显示本帮助")
    else:
        await _send_reply(ws, agent_id,
            f"❌ 未知子命令: {sub_cmd}")

    return True
```

### 3.3 权限辅助函数

```python
def _get_agent_level(agent_id: str) -> int:
    """获取 agent 权限级别 (1-4)，默认 1。"""
    from server.common import persistence as _p
    users = _p.get_approved_users()
    info = users.get(agent_id, {})
    return info.get("level", 1)
```

### 3.4 查询数据函数

| 函数 | 数据源 | 代码 |
|:-----|:--------|:------|
| `_format_pipeline_status(params, main_mod)` | `main_mod._ensure_engine().format_context()` / `main_mod._ensure_pipeline_manager().get_all_active()` | 复用 `_handle_server_query` L2117-2135 的逻辑 |
| `_format_agent_list()` | `auth.get_users()` + `ac_mod.get_all_cards()` + `_connections` | 复用 `_handle_server_query` L2101-2115 的逻辑 |
| `_format_agent_info(agent_id)` | `auth.get_agent_name()` + `ac_mod.get_agent_card()` | 简单查询，内联 |
| `_format_audit_log(limit_str)` | `AuditLogger.tail()` + `config.DATA_DIR` | 简单查询，内联 |

```python
async def _format_pipeline_status(round_name: str, main_mod) -> str:
    """Return pipeline status text."""
    mgr = main_mod._ensure_pipeline_manager()
    if round_name:
        ctx = mgr.get(round_name)
        if ctx:
            engine = main_mod._ensure_engine()
            return engine.format_context(ctx)
        return f"❌ 管线 {round_name} 不存在"
    active = mgr.get_all_active()
    if active:
        lines = ["📋 活跃管线:"]
        for ctx in sorted(active, key=lambda c: c.round_name):
            lines.append(
                f"  {ctx.round_name} [{ctx.task_kind.value}] "
                f"{ctx.status.value} step={ctx.current_step}/{ctx.total_steps}"
            )
        return "\n".join(lines)
    return "📋 当前无活跃管线"

def _format_agent_list() -> str:
    """Return agent list text."""
    from server.common import auth as _auth
    from . import agent_card as _ac
    from . import state as _st
    users = _auth.get_users()
    cards = _ac.get_all_cards()
    lines = ["📇 Agents:"]
    seen = set()
    for aid, info in sorted(users.items()):
        name = info.get("name", aid[:12])
        role = info.get("role", "member")
        online = "🟢" if aid in _st._connections else "🔴"
        card = cards.get(aid, {})
        roles = ", ".join(card.get("pipeline_roles", []))
        roles_str = f" [{roles}]" if roles else ""
        lines.append(f"  {online} {name} ({aid[:12]}...) L{info.get('level', 1)}{roles_str}")
        seen.add(aid)
    return "\n".join(lines)

def _format_agent_info(agent_id: str) -> str:
    """Return single agent info text."""
    from server.common import auth as _auth
    from . import agent_card as _ac
    from . import state as _st
    users = _auth.get_users()
    info = users.get(agent_id, {})
    if not info:
        return f"❌ Agent {agent_id} 未找到"
    name = info.get("name", agent_id[:12])
    role = info.get("role", "member")
    level = info.get("level", 1)
    online = "🟢 在线" if agent_id in _st._connections else "🔴 离线"
    card = _ac.get_agent_card(agent_id)
    card_info = ""
    if card:
        card_info = (
            f"\\n  📇 display_name: {card.get('display_name', '')}"
            f"\\n  🎭 角色: {', '.join(card.get('pipeline_roles', []))}"
        )
    return (
        f"📋 Agent 信息: {name}\\n"
        f"  🆔 agent_id: `{agent_id}`\\n"
        f"  🎚️ 级别: L{level} / 角色: {role}\\n"
        f"  📡 状态: {online}"
        f"{card_info}"
    )

def _format_audit_log(limit_str: str) -> str:
    """Return audit log tail."""
    from .audit import AuditLogger
    from server.common.config import DATA_DIR as _dd
    limit = 20
    if limit_str and limit_str.isdigit():
        limit = min(int(limit_str), 100)
    auditor = AuditLogger(_dd)
    lines = auditor.tail(limit)
    if not lines:
        return "📋 审计日志为空"
    return "📋 最近审计日志:\\n" + "\\n".join(
        f"  {l}" for l in lines[-limit:]
    )
```

### 3.5 规则注册

在 `scenario_matcher.py` 模块级注册在 `_RULES` 中，与其他规则并列。新的注册顺序：

```python
# 在模块加载时注册（在已有规则后追加）
register_rule(HandlerRule(
    match=match_query,
    handle=handle_query,
    priority=25,
    name="##query 命令",
    protocol_ref="§R131",
))
```

### 3.6 回复机制

复用现有的 `_send_reply()`（L247-260），该函数已正确向发送者 inbox 发送私信，不广播。

---

## 4. 改动清单

### 4.1 `server/ws_server/scenario_matcher.py`（+~120 行）

| 组件 | 行数 | 说明 |
|:-----|:----:|:------|
| `match_query()` | ~5 行 | content.startswith("##query") |
| `handle_query()` | ~50 行 | 子命令解析 + 权限检查 + 6 路由 |
| `_get_agent_level()` | ~8 行 | 权限级别查询 |
| `_format_pipeline_status()` | ~15 行 | 管线状态查询 |
| `_format_agent_list()` | ~15 行 | agent 列表 |
| `_format_agent_info()` | ~15 行 | 单个 agent 详情 |
| `_format_audit_log()` | ~10 行 | 审计日志 |
| rule 25 注册 | ~5 行 | `register_rule(HandlerRule(...))` |
| **合计** | **~120 行** | |

### 4.2 `server/ws_server/main.py`（无改动）

`handle_query` 通过运行时 `from . import main as _main` 调用 `_main._ensure_engine()`、`_main._ensure_pipeline_manager()` 等函数。main.py 无需新增代码。

---

## 5. 数据流图

```
Bot ──##query##whoami──→ _inbox:server
                              │
                          dispatch()
                              │
                    match_query() matches → rule 25
                              │
                    handle_query(ws, agent_id, msg, matched)
                        ├─ content.split("##") → ["", "query", "whoami"]
                        ├─ _get_agent_level(agent_id) → L3
                        ├─ sub_cmd == "whoami":
                        │   ├─ auth.get_users()
                        │   └─ _send_reply(ws, agent_id, "🆔 ...")
                        └─ return True  (handled)

Bot ←── inbox ── "🆔 agent_id: ws_xxx | 名称: 小开 | 级别: L3"
```

---

## 6. 侧效应分析

| 变动 | 侧效应 | 风险 |
|:-----|:-------|:----:|
| rule 25 在 rule 30 之前匹配 | 所有 `##query` 开头的消息被 rule 25 拦截，rule 30 的 `##` 处理不到 `##query` | 🟢 需确保 `match_query` 在 `match_hash_cmd` 之前注册（priority 25 < 30） |
| 函数体内 import main | 运行时导入，无模块级循环依赖风险 | 🟢 与现有 `handle_hash_cmd` 模式一致 |
| `_get_agent_level` 首次导入 `persistence` | 首次调用时可能触发外部 I/O（读文件） | 🟢 仅读缓存，无性能问题 |
| `!` 命令仍可用 | 旧路径不变，双通道并存 | 🟢 显式保留兼容 |

---

## 7. 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | 删除 `!` 命令 | 保留兼容，下轮迁移 |
| ❌ | 修改 `_handle_server_query` | 保持旧路径可用 |
| ❌ | 修改 `handle_hash_cmd` | 不触发现有 `##` 命令 |
| ❌ | 新增后端 `/api/*` 路由 | 纯后端命令，无 Web UI |
| ❌ | 修改 `docs/inbox-message-protocol.md` | 本期只加代码规则 |

---

## 8. 验收检查表（11 项）

| # | 验收项 | 验证方法 | 优先级 |
|:-:|:-------|:---------|:------:|
| F1 | L1 发 `##whoami` → 收到 agent_id + 级别 | 发送到 `_inbox:server` | 🟢 P0 |
| F2 | L3 发 `##agents` → 收到 bot 列表 | 检查回复内容 | 🟢 P0 |
| F3 | L3 发 `##status` → 收到活跃管线 | 检查回复 | 🟢 P0 |
| F4 | L3 发 `##status##R130` → 收到指定管线详情 | 检查回复 | 🟢 P0 |
| F5 | L3 发 `##agent_info ws_xxx` → 收到 bot 详情 | 检查回复 | 🟢 P0 |
| F6 | L4 发 `##audit` → 审计日志；L3 发 → 权限拒绝 | 分别用 L4/L3 测试 | 🟢 P0 |
| R1 | `##start`/`##stop`/`##advance`/`##archive` 不受影响 | 正常执行 | 🟢 P0 |
| R2 | `!` 命令仍可用 | 发 `!pipeline_status` | 🟢 P0 |
| R3 | `_handle_server_query` 仍可用 | 发 `!my_id` → 正常回复 | 🟢 P0 |
| R4 | to_agent 派活不受影响 | 带 to_agent 消息 → 正常路由 | 🟢 P0 |
| R5 | `##query` 回复仅到发送者 inbox | 发 + 检查其他 bot 收不到 | 🟢 P0 |

---

## 9. 执行顺序

| 步骤 | 操作 | 依赖 |
|:----:|:-----|:-----|
| 1 | `scenario_matcher.py` 新增 `match_query()` + `handle_query()` | — |
| 2 | `scenario_matcher.py` 新增 `_get_agent_level()` | — |
| 3 | `scenario_matcher.py` 新增 4 个 `_format_*` 查询函数 | 1 |
| 4 | `scenario_matcher.py` 注册 rule 25 | 1-3 |
| 5 | 验证 import 无错误：`python3 -c "from server.ws_server.scenario_matcher import dispatch, match_query, handle_query"` | 4 |
| 6 | 全量回归验证（11 项验收表） | 5 |
