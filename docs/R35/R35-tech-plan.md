# R35 技术方案 — 管理员触发词机制

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-23
> **需求文档：** `docs/R35/R35-requirements.md`
> **改动范围：** 第①类 `server/`（handler.py, protocol.py, audit.py 新）+ 第④类 `server/templates.py` + `server/web_viewer.py`

---

## 0. 方案总览

```
                        WebSocket 连接（已认证）
                              │
              ┌───────────────┼───────────────┐
              │               │               │
         大厅(lobby)    工作室(ws:*)    管理频道(_admin) 🆕
              │               │               │
              ▼               ▼               ▼
         标准路由        工作区路由       ! 触发词路由 🆕
     (📢/📋/🆘/@)                        │
                                    ┌───┴───┐
                               P4 超级管理员   P3 工作室管理员
                               (全部放行)      (仅限自己范围)
                                    │               │
                                    ▼               ▼
                             执行 → 审计日志 → 回复 _admin
```

**核心改动量估算：**

| 文件 | 新增 | 修改 | 净增 |
|:-----|:----:|:----:|:----:|
| `handler.py` | ~110 行 | ~15 行 | ~+125 |
| `server/audit.py` 🆕 | ~80 行 | — | ~+80 |
| `protocol.py` | ~3 行 | — | ~+3 |
| `templates.py` | ~60 行 | ~15 行 | ~+75 |
| `web_viewer.py` | ~25 行 | ~3 行 | ~+28 |
| `__main__.py` | ~8 行 | ~2 行 | ~+10 |
| **合计** | ~286 | ~35 | **~+321** |

---

## 1. 触发词协议设计

### 1.1 格式规范

```
触发词格式：  !<命令> [参数...]
         ^
         └─ ASCII 感叹号（U+0021）

频道约束： 仅 _admin 频道
路由触发：  消息 content 以 "!" 开头 AND channel == "_admin"
```

**设计理由：**
- `!` 前缀在现有协议中无特殊含义，不会与 `📢` / `📋` / `🆘` / `@` 冲突
- `_admin` 频道名以 `_` 开头避开 workspace `ws:` 命名空间，类似现有 `__registration__`
- 正向白名单匹配（`startswith("!")`），拒绝以 `!` 开头但不匹配任何命令的消息

### 1.2 参数解析规则

采用空格分隔的简单 token 解析，与现有 SSH 脚本的参数风格一致：

```
!create_workspace R35-dev --members pm-bot,dev-bot
!close_workspace ws:R35-dev --reason "开发完成"
!approve_pairing ABC12345 --role member
```

解析策略：
- 第 1 个 token = 命令名（去 `!` 前缀后）
- 后续 token 使用简单的 `--key value` / `--key "value"` 解析
- 位置参数按顺序映射（如 workspace name、code、agent_id）
- 不引入 argparse，避免依赖。用正则 + 字符串 split 完成

### 1.3 匹配与路由流程图

```
handle_broadcast(ws, sender_id, msg)
    │
    ├── content = msg.get("content")
    ├── channel = msg.get("channel") or agent_channel or "lobby"
    │
    ├── [现] 限流 → nonsense → 静默  → 📢 检查
    │
    ├── [新] ═══ _admin 频道拦截 ═══
    │   │
    │   │  if channel == "_admin" and content.startswith("!"):
    │   │      ├── 解析命令名 + 参数
    │   │      ├── 查找命令注册表 → 不存在 → "❌ 未知命令。可用命令：..."
    │   │      ├── 检查 sender_role 权限
    │   │      │     ├── P1 member → ❌ "权限不足：管理操作仅限管理员"
    │   │      │     ├── P3 workspace_admin → 检查命令 workspace_scope
    │   │      │     └── P4 global_admin → ✅ 全部放行
    │   │      ├── 执行业务函数
    │   │      ├── 写审计日志
    │   │      └── _send(ws, "✅/❌ 结果描述")
    │   │      return  ← 不走后续广播路由
    │   │
    │   │  if channel == "_admin" and NOT startswith("!"):
    │   │      → _send(ws, "ℹ️ _admin 频道仅支持 ! 命令")
    │   │      → return
    │
    ├── [现] Channel resolution + _can_broadcast
    │
    └── [现] Lobby / Workspace / Registration 路由（不变）
```

### 1.4 `_can_broadcast` 扩展

**位置：** `handler.py:878-905`

在现有 `_can_broadcast()` 开头增加 `_admin` 频道放行逻辑：

```python
def _can_broadcast(agent_id: str, channel: str, msg: dict) -> tuple[bool, str]:
    # R35: _admin channel — only admins (P3/P4) can send
    if channel == p.ADMIN_CHANNEL:
        if auth.is_global_admin(agent_id):
            return True, ""
        if _is_any_workspace_admin(agent_id):
            return True, ""
        users = auth.get_users()
        name = users.get(agent_id, {}).get("name", agent_id[:12])
        return False, f"{name} 无权访问管理频道"

    # ... 现有 L4 global admin → any channel
    # ... 现有 registration / lobby / workspace
```

**新增辅助函数 `_is_any_workspace_admin()`：**

```python
def _is_any_workspace_admin(agent_id: str) -> bool:
    """Check if agent is a workspace admin of ANY workspace (P3 level)."""
    for ws in ws_mod.get_all_workspaces():
        if agent_id in ws.admin_ids or agent_id == ws.owner_id:
            return True
    return False
```

---

## 2. 命令注册与分发

### 2.1 命令注册表

**位置：** `handler.py` 模块级（新增 ~200 行）

采用字典驱动的命令分发，每个命令绑定：
- `handler`: 异步函数 `(sender_id, params) → str` 返回结果文本
- `min_role`: 最低角色级别（4=P4 only, 3=P3+, 2=any but blocked by _can_broadcast）
- `workspace_scope`: True = P3 仅限自己管理的 workspace，False = 无限制

```python
# ── R35: Admin command registry ────────────────────────────────

_ADMIN_COMMANDS: dict[str, dict] = {
    # ── 4.1 工作室管理 ──
    "create_workspace": {
        "handler": _cmd_create_workspace,
        "min_role": 4,         # P4 only
        "workspace_scope": False,
        "usage": "!create_workspace <name> --members <ids>",
    },
    "close_workspace": {
        "handler": _cmd_close_workspace,
        "min_role": 3,         # P3+ (P4 all, P3 own scope)
        "workspace_scope": True,
        "usage": "!close_workspace <ws_id> [--reason <text>]",
    },
    "list_workspaces": {
        "handler": _cmd_list_workspaces,
        "min_role": 3,
        "workspace_scope": True,  # P3 sees own, P4 sees all
        "usage": "!list_workspaces",
    },

    # ── 4.2 成员管理 ──
    "list_agents": {
        "handler": _cmd_list_agents,
        "min_role": 3,
        "workspace_scope": True,
        "usage": "!list_agents [--role <role>]",
    },
    "agent_status": {
        "handler": _cmd_agent_status,
        "min_role": 3,
        "workspace_scope": True,
        "usage": "!agent_status <agent_id>",
    },
    "approve_pairing": {
        "handler": _cmd_approve_pairing,
        "min_role": 4,
        "workspace_scope": False,
        "usage": "!approve_pairing <code> [--role <role>]",
    },
    "approve_ws_admin": {
        "handler": _cmd_approve_ws_admin,
        "min_role": 4,
        "workspace_scope": False,
        "usage": "!approve_ws_admin --workspace <ws_id> --agent <agent>",
    },
    "reject_ws_admin": {
        "handler": _cmd_reject_ws_admin,
        "min_role": 4,
        "workspace_scope": False,
        "usage": "!reject_ws_admin --workspace <ws_id> --agent <agent> --reason <text>",
    },
    "list_pending": {
        "handler": _cmd_list_pending,
        "min_role": 4,
        "workspace_scope": False,
        "usage": "!list_pending",
    },

    # ── 4.3 审计与查询 ──
    "audit_log": {
        "handler": _cmd_audit_log,
        "min_role": 3,
        "workspace_scope": True,
        "usage": "!audit_log [--limit <n>]",
    },
    "list_workspace_admins": {
        "handler": _cmd_list_workspace_admins,
        "min_role": 3,
        "workspace_scope": True,
        "usage": "!list_workspace_admins [--workspace <ws_id>]",
    },
}
```

### 2.2 命令解析器

```python
def _parse_command(content: str) -> tuple[str | None, dict]:
    """Parse '!<command> [args...]' into (command_name, params dict).
    Returns (None, {}) if not a command.
    """
    if not content.startswith("!"):
        return None, {}

    parts = content[1:].strip().split()
    if not parts:
        return None, {}

    cmd = parts[0].lower()
    params = {"_raw": content}
    positional = []
    i = 1
    while i < len(parts):
        token = parts[i]
        if token.startswith("--"):
            key = token[2:]
            i += 1
            if i < len(parts):
                val = parts[i]
                # Strip surrounding quotes if present
                if (val.startswith('"') and val.endswith('"')) or \
                   (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                params[key] = val
            else:
                params[key] = ""
        else:
            positional.append(token)
        i += 1

    if positional:
        params["_positional"] = positional
    return cmd, params
```

### 2.3 权限检查路径

```python
def _check_command_permission(
    agent_id: str, cmd_name: str, cmd_meta: dict, params: dict
) -> tuple[bool, str]:
    """Check if agent has permission to run this command.
    Returns (allowed: bool, reason: str).
    """
    cmd = _ADMIN_COMMANDS.get(cmd_name)
    if not cmd:
        return False, f"未知命令: !{cmd_name}"
        return False, f"未知命令: !{cmd_name}"

    # P4 → always allowed
    if auth.is_global_admin(agent_id):
        return True, ""

    # P3 → check min_role and workspace_scope
    if cmd["min_role"] <= 3 and cmd["workspace_scope"]:
        return True, ""  # handler internally filters to own scope

    if cmd["min_role"] <= 3 and not cmd["workspace_scope"]:
        return False, "权限不足：该操作仅超级管理员可执行"

    return False, "权限不足"
```

### 2.4 命令路由入口

插入到 `handle_broadcast()` 中，在现有限流检查之后、频道解析之前：

```python
# ── R35: _admin channel command routing ──
if channel == p.ADMIN_CHANNEL:
    if content.startswith("!"):
        cmd_name, params = _parse_command(content)
        if cmd_name and cmd_name in _ADMIN_COMMANDS:
            cmd = _ADMIN_COMMANDS[cmd_name]
            allowed, reason = _check_command_permission(sender_id, cmd_name, cmd, params)
            if not allowed:
                await _send(ws, {"type": "broadcast", "channel": p.ADMIN_CHANNEL,
                    "from_name": "系统", "content": f"❌ {reason}", "ts": time.time()})
                return

            try:
                result = await cmd["handler"](sender_id, params)
                _log_audit(sender_id, cmd_name, params, "success", result)
                await _send(ws, {"type": "broadcast", "channel": p.ADMIN_CHANNEL,
                    "from_name": "系统", "content": result, "ts": time.time()})
            except Exception as e:
                err_msg = f"❌ 执行失败: {e}"
                _log_audit(sender_id, cmd_name, params, "error", err_msg)
                await _send(ws, {"type": "broadcast", "channel": p.ADMIN_CHANNEL,
                    "from_name": "系统", "content": err_msg, "ts": time.time()})
                logger.error("Admin cmd !%s failed: %s", cmd_name, e)
            return
        else:
            # Unrecognized ! command
            available = ", ".join(f"!{k}" for k in sorted(_ADMIN_COMMANDS))
            await _send(ws, {"type": "broadcast", "channel": p.ADMIN_CHANNEL,
                "from_name": "系统",
                "content": f"❌ 未知命令。可用命令：{available}", "ts": time.time()})
            return
    else:
        # Non-! message in _admin → reject
        await _send(ws, {"type": "broadcast", "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "content": "ℹ️ 管理频道仅支持 ! 命令。可用命令：!create_workspace, !list_agents, ...",
            "ts": time.time()})
        return
```

---

## 3. 各命令实现详述

### 3.1 工作室管理

#### `!create_workspace`

```python
async def _cmd_create_workspace(sender_id: str, params: dict) -> str:
    """Create a new workspace. P4 only."""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !create_workspace <name> --members <ids>"

    ws_name = positional[0]
    member_ids_raw = params.get("members", "")
    member_ids = [m.strip() for m in member_ids_raw.split(",") if m.strip()]

    # Generate workspace ID: ws:<sender_short>-<name>
    ws_id = f"{p.WORKSPACE_ID_PREFIX}{sender_id[:8]}-{ws_name[:20]}"

    users = auth.get_users()
    sender_name = users.get(sender_id, {}).get("name", sender_id[:12])

    result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
    if not result:
        return f"❌ 创建失败：{ws_name} 可能已存在，或管理员名下活跃工作区过多"

    # Add members
    for mid in member_ids:
        if mid in users:
            ws_mod.add_member(ws_id, mid)

    member_list = ", ".join(member_ids) if member_ids else "无"
    return f"✅ 工作室 {ws_name} 已创建。成员: {member_list}"
```

#### `!close_workspace`

```python
async def _cmd_close_workspace(sender_id: str, params: dict) -> str:
    """Close a workspace. P3+ (P3: own managed only)."""
    ws_id = params.get("_positional", [None])[0] or params.get("workspace")
    if not ws_id:
        return "❌ 用法: !close_workspace <ws_id> [--reason <text>]"

    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作室 {ws_id} 不存在"

    # P3 scope check: workspace_admin 只能关自己管理的
    if not auth.is_global_admin(sender_id):
        if not (sender_id in ws.admin_ids or sender_id == ws.owner_id):
            return "❌ 权限不足：你不是该工作室的管理员"

    reason = params.get("reason", "管理操作")
    ws_mod.close_workspace(ws_id)
    return f"✅ 工作室 {ws.name} 已归档。（原因：{reason}）"
```

#### `!list_workspaces`

```python
async def _cmd_list_workspaces(sender_id: str, params: dict) -> str:
    """List workspaces. P3 (own) / P4 (all)."""
    all_ws = ws_mod.get_all_workspaces()

    if auth.is_global_admin(sender_id):
        visible = all_ws
    else:
        # P3: only workspaces where sender is admin
        visible = [w for w in all_ws
                   if sender_id in w.admin_ids or sender_id == w.owner_id]

    if not visible:
        return "📋 暂无工作室"

    lines = ["📋 工作室列表："]
    for w in visible:
        status_icon = {"active": "🟢", "closing": "🟡", "archived": "⚫"}.get(
            w.state.value if hasattr(w.state, 'value') else str(w.state), "⚪")
        lines.append(f"  {status_icon} {w.id} \"{w.name}\" ({len(w.members)}人)")
    return "\n".join(lines)
```

### 3.2 成员管理

#### `!list_agents`

```python
async def _cmd_list_agents(sender_id: str, params: dict) -> str:
    """List approved agents with online status."""
    users = auth.get_users()
    online_ids = set(_connections.keys())

    role_filter = params.get("role", "").lower()
    lines = [f"📋 共 {len(users)} 个已认证 agent："]

    for aid, u in sorted(users.items()):
        role = u.get("role", "member")
        if role_filter and role != role_filter:
            continue
        name = u.get("name", aid[:12])
        status = "🟢" if aid in online_ids else "🟡"
        lines.append(f"  {status} {name} ({role})")

    return "\n".join(lines)
```

#### `!agent_status`

```python
async def _cmd_agent_status(sender_id: str, params: dict) -> str:
    """Show detailed agent info."""
    target = params.get("_positional", [None])[0] or params.get("agent")
    if not target:
        return "❌ 用法: !agent_status <agent_id|agent_name>"

    users = auth.get_users()
    # Find by name or ID
    found_id = target if target in users else None
    if not found_id:
        for aid, u in users.items():
            if u.get("name") == target:
                found_id = aid
                break

    if not found_id:
        return f"❌ 未找到 agent: {target}"

    u = users[found_id]
    channel = persistence.get_agent_channel(found_id) or "lobby"
    online = "🟢" if found_id in _connections else "🟡"
    ws_list = ws_mod.get_workspaces_for_agent(found_id)
    ws_names = ", ".join(w.id for w in ws_list) if ws_list else "无"

    return (f"🔍 {u.get('name', found_id)}：\n"
            f"  角色={u.get('role','member')}\n"
            f"  活跃频道={channel}\n"
            f"  所属工作室={ws_names}\n"
            f"  在线={online}")
```

#### `!approve_pairing`

```python
async def _cmd_approve_pairing(sender_id: str, params: dict) -> str:
    """Approve a pairing code. P4 only."""
    code = params.get("_positional", [None])[0]
    if not code:
        return "❌ 用法: !approve_pairing <code> [--role <role>]"

    role = params.get("role", "member")
    result = auth.approve(code, role)

    if result["type"] == "approve_ok":
        persistence.save_pairing_codes(config.DATA_DIR)
        persistence.save_approved_users(config.DATA_DIR)
        return f"✅ 配对码 {code} 已确认，{result['agent_id'][:12]} 已获得 {role} 角色。"
    else:
        return f"❌ {result.get('error', '审批失败')}"
```

#### `!approve_ws_admin` / `!reject_ws_admin`

直接调用现有 `workspace.approve_admin_request()` / `workspace.reject_admin_request()`。

#### `!list_pending`

调用 `workspace.get_pending_requests()`，格式化输出。

### 3.3 审计与查询

#### `!audit_log`

```python
async def _cmd_audit_log(sender_id: str, params: dict) -> str:
    """Query audit log. P3 (own) / P4 (all)."""
    limit = int(params.get("limit", "10"))

    if auth.is_global_admin(sender_id):
        entries = _audit_logger.query(tail=limit)
    else:
        # P3: only entries related to sender
        all_entries = _audit_logger.query(tail=100)
        entries = [e for e in all_entries
                   if e.get("agent_id") == sender_id][:limit]

    if not entries:
        return "📋 暂无审计记录"

    lines = [f"📋 最近 {len(entries)} 条操作记录："]
    for i, e in enumerate(entries, 1):
        ts_str = time.strftime("%H:%M", time.localtime(e.get("ts", 0)))
        op = e.get("agent_name", e.get("agent_id", "")[:12])
        action = e.get("command", e.get("action", "?"))
        result = e.get("result", "")
        lines.append(f"  {i}. [{ts_str}] {op} → {action} ({result})")
    return "\n".join(lines)
```

---

## 4. 审计日志方案

### 4.1 审计模块迁移

**从：** `scripts/admin/lib/audit.py` → `server/audit.py`

迁移时做以下适配：
1. 日志文件路径改为 `DATA_DIR / "_audit_log.jsonl"`（JSON Lines，每行一条）
2. `log()` 签名增加 `command` 字段
3. `query()` 支持 `agent_id` 过滤

```python
# server/audit.py (新增)
class AuditLogger:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "_audit_log.jsonl"

    def log(self, agent_id: str, command: str, params: dict,
            result: str, detail: str = "") -> None:
        entry = {
            "ts": time.time(),
            "agent_id": agent_id,
            "command": command,
            "params": params,
            "result": result,       # "success" | "error"
            "detail": detail,       # human-readable result text (truncated)
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, tail: int = 100, agent_id: str | None = None,
              command: str | None = None) -> list[dict]:
        """Read back audit entries. Newest first when tail is set."""
        ...
```

### 4.2 handler.py 中的审计触发

每次命令执行后，在 handler 中调用：

```python
from .audit import AuditLogger
_audit_logger = AuditLogger(config.DATA_DIR)

def _log_audit(sender_id: str, cmd: str, params: dict,
               result: str, detail: str = "") -> None:
    _audit_logger.log(sender_id, cmd, params, result, detail[:200])
```

### 4.3 审计日志存储

| 项目 | 详情 |
|:-----|:-----|
| **文件名** | `_audit_log.jsonl` |
| **位置** | `DATA_DIR`（Docker volume） |
| **格式** | JSON Lines（一条一行，append-only） |
| **轮转** | 本期不做。后续可用 `!audit_log --purge` 手动清理 |
| **安全** | 文件在 Docker volume 中，与 `workspaces.json` 同级 |

---

## 5. Web 端扩展 — 管理员 Tab

### 5.1 TAB_STATE 扩展

**位置：** `templates.py:149-154`

```javascript
// 从 3-slot → 4-slot
const TAB_STATE = {
  tab1: { id: 'tab1', channel: 'lobby',       label: '🌐 大厅',     permanent: true, visible: true },
  tab2: { id: 'tab2', channel: null,           label: '📋 活跃',     permanent: false, visible: false },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史查看器', permanent: true, visible: true },
  // R35: 🆕 管理员 Tab（纯查看，无输入框）
  tab4: { id: 'tab4', channel: '_admin',       label: '🔧 管理员',   permanent: true, visible: true },
};
```

**Tab 顺序（按需求：活跃 | 大厅 | 管理员 | 历史）：**

```javascript
function renderTabBar() {
  // Tab 2: 活跃工作室 (conditional)
  // Tab 1: 大厅 (always)
  // Tab 4: 管理员 🆕
  // Tab 3: 历史查看器 (always)
  ...
}
```

### 5.2 管理员 Tab 可见性控制

管理员 Tab 仅项目负责人（web 用户）可见。通过 JavaScript 检查当前用户身份：

```javascript
// R35: admin tab visibility — only for web viewer owner (项目负责人)
const SHOW_ADMIN_TAB = true;  // Web viewer user = 项目负责人, always show
```

如果后续需要角色判断，可通过 `TOKEN` 后端的角色信息传入。

### 5.3 `/api/admin/channel` 端点

**位置：** `web_viewer.py`（新增路由）

```python
async def handle_admin_channel(request):
    """Return _admin channel messages (read-only for web viewer)."""
    token = request.query.get("token", "")
    name = validate_token(token)
    if not name:
        return web.json_response({"error": "Unauthorized"}, status=401)

    limit = int(request.query.get("limit", "50"))
    channel = "_admin"

    messages = ms.get_messages(channel=channel, limit=limit, data_dir=config.DATA_DIR)
    return web.json_response({"messages": messages, "channel": channel})
```

对应的 `message_store.py::get_messages()` 需支持 `channel` 参数（若已支持则直接使用）。

### 5.4 Web 端 `loadMessages()` 支持 `_admin`

`loadMessages()` 已接受 `channel` 参数，无需改动。轮询中当 `activeTabId === 'tab4'` 时自动拉取 `_admin` 频道消息。

### 5.5 样式区分

管理员 Tab 有轻微视觉区分：

```css
.tab.admin-tab { color: #f0a040; }
.tab.admin-tab.active { border-bottom-color: #f0a040; background: rgba(240,160,64,0.15); }
```

HTML 中 Tab4 使用 `class="tab admin-tab"` 渲染。

---

## 6. 管线集成：`__main__.py` 同步

### 6.1 双 handler 路径

`handler.py::handler()`（websockets 库）和 `__main__.py::ws_handler()`（aiohttp）都需要对 `_admin` 频道进行拦截处理。

**__main__.py 改动：** 在 `ws_handler()` 的消息分发循环中，`msg_type == "message"` 分支调用 `handle_broadcast()` — 无需额外改动，因为 `_admin` 频道路由已内聚在 `handle_broadcast()` 中。

**仅需确保 `__main__.py` 导入 `p.ADMIN_CHANNEL`，且 `_can_broadcast` 放行。**

### 6.2 审计日志初始化

在 `__main__.py` 启动时初始化审计日志：

```python
# __main__.py near line 695 (after init_db)
from .audit import AuditLogger
_audit_log = AuditLogger(config.DATA_DIR)
```

---

## 7. 协议常量

**文件：** `shared/protocol.py`

```python
# ── R35: Admin Channel ──────────────────────────────────────────
ADMIN_CHANNEL = "_admin"
```

---

## 8. 不改的内容

| 事项 | 原因 |
|:-----|:-----|
| 现有 SSH 脚本 (`scripts/admin/`) | 保留用于故障恢复，暂不删除 |
| `handler.py` 现有 lobby/workspace 路由 | 新增 `_admin` 为独立分支，不修改现有逻辑 |
| Docker Compose / 部署配置 | 基础设施，不属于代码修复 |
| gateway 插件 | 不属本轮范围 |
| P3 角色体系全面重构 | 本期复用现有 role 体系 |

---

## 9. 测试要点（给 🦐 测试工程师）

### A 组 — 基础鉴权

| # | 用例 | 对应 PRD | 预期 |
|:-:|:-----|:-------:|:-----|
| A-T1 | P1 member 在 _admin 发 `!create_workspace` | A-T1 | ❌ 拒绝 |
| A-T2 | P1 member 在大厅发 `!create_workspace` | A-T2 | ❌ 拒绝（非 _admin 频道） |
| A-T3 | P4 admin 在 _admin 发 `!create_workspace R35-dev --members pm,dev` | A-T3 | ✅ 创建成功 |
| A-T4 | P3 workspace_admin 关自己管理的 workspace | A-T4 | ✅ 关闭成功 |
| A-T5 | P3 workspace_admin 关非自己管理的 workspace | A-T5 | ❌ 拒绝 |

### B 组 — 工作室管理

| # | 用例 | 对应 PRD | 预期 |
|:-:|:-----|:-------:|:-----|
| B-T1 | `!close_workspace ws:xxx --reason "done"` | B-T1 | 归档，成员收到 closing |
| B-T2 | `!list_workspaces` | B-T2 | 返回列表（id+name+count+status） |

### C 组 — 成员管理

| # | 用例 | 对应 PRD | 预期 |
|:-:|:-----|:-------:|:-----|
| C-T1 | `!list_agents` | C-T1 | 返回 agent 列表 |
| C-T2 | `!agent_status pm-bot` | C-T2 | 返回详情 |
| C-T3 | `!approve_pairing ABC12345 --role member` | C-T3 | 配对生效 |
| C-T4 | `!approve_ws_admin --workspace ws:xx --agent pm` | C-T4 | 升级成功 |
| C-T5 | `!reject_ws_admin --workspace ws:xx --agent pm --reason "trial"` | C-T5 | 拒绝成功 |

### D 组 — 审计

| # | 用例 | 对应 PRD | 预期 |
|:-:|:-----|:-------:|:-----|
| D-T1 | 执行 `!create_workspace` 后检查审计日志 | D-T1 | 日志写入 `_audit_log.jsonl` |
| D-T2 | `!audit_log --limit 10` | D-T2 | 返回最近 10 条 |
| D-T3 | P3 workspace_admin 查询 `!audit_log` | D-T3 | 仅看到自己相关记录 |

### E 组 — 安全

| # | 用例 | 对应 PRD | 预期 |
|:-:|:-----|:-------:|:-----|
| E-T1 | 未认证连接发 `!` 命令到 _admin | E-T1 | 无响应 |
| E-T2 | P1 member 切活跃频道到 `_admin` | E-T2 | 被拒绝 |
| E-T3 | P4 执行 `!create_workspace` 后 _admin 收到回复 | E-T3 | ✅ 回复可见 |
| E-T4 | P4 降权后再执行 `!` 命令 | E-T4 | 返回权限错误 |

---

## 10. 向后兼容

| 检查项 | 结论 |
|:-------|:----:|
| `!` 前缀在现有协议中有意义？ | ✅ 否 — 当前无特殊处理 |
| `_admin` 频道名与现有冲突？ | ✅ 否 — 不在 `ws:` 命名空间 |
| 现有 lobby/workspace 路由受影响？ | ✅ 否 — `_admin` 分支在 channel resolution 之前 return |
| 现有 bot 能否发消息到 `_admin`？ | ✅ 不会 — `_can_broadcast` 阻止非管理员 |
| `message_store` 支持 `_admin` channel？ | ✅ `save_message()` 接受任意 channel |
| 审计日志文件冲突？ | ✅ 新文件 `_audit_log.jsonl`，不与现有文件冲突 |
| Web 端 Tab 破坏现有 Tab 切换？ | ✅ 新 Tab 序号 tab4，不影响 tab1-3 |
| 双 handler 路径 (_\_main\_\_.py) 需改动？ | ✅ 否 — `_admin` 逻辑内聚在 `handle_broadcast()` |

---

## 11. 实施顺序

```
Step 4 编码顺序：
  ┌──────────────────────────┐
  │ 1. 基础设施              │
  │    - protocol.py: ADMIN_CHANNEL 常量  │
  │    - server/audit.py: 迁移 AuditLogger│
  ├──────────────────────────┤
  │ 2. 服务端核心            │
  │    - handler.py: _admin 频道拦截      │
  │    - handler.py: 命令注册表 + 解析器   │
  │    - handler.py: _can_broadcast 扩展  │
  ├──────────────────────────┤
  │ 3. 各命令实现            │
  │    - 工作室管理 (3个)    │
  │    - 成员管理 (6个)      │
  │    - 审计查询 (2个)      │
  ├──────────────────────────┤
  │ 4. Web 端                │
  │    - templates.py: TAB_STATE 扩展     │
  │    - templates.py: renderTabBar 重排   │
  │    - web_viewer.py: /api/admin/channel│
  ├──────────────────────────┤
  │ 5. __main__.py 集成      │
  │    - 审计初始化 + ADMIN_CHANNEL 导入  │
  └──────────────────────────┘
```

---

> **方案交付状态：** ✅ 待全员讨论评审
> **产出文件：** `docs/R35/R35-tech-plan.md`
