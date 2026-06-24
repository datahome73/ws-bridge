# R38 技术方案 — 流水线任务状态机 + Agent 协作体系

> **版本：** v1.1
> **状态：** ✅ 小谷审查通过（2 条建议已采纳）
> **架构师：** 🏗️ 小开
> **日期：** 2026-06-24
> **需求文档：** [R38-product-requirements.md](R38-product-requirements.md)
> **开发计划：** [WORK_PLAN.md](WORK_PLAN.md)

**v1.0 → v1.1 变更（审查建议采纳）：**
- `_cmd_task_update` 增加自质量门校验：发送者必须是 Task 的 `assigned_role` 或全局管理员
- Agent Card 配置路径修正：项目根目录 `config/agent_cards.json`（不再放 `data/` 下）

---

## 0. 前置确认

| 开放问题 | 答案 |
|:---------|:-----|
| 新增 SQLite 表名 `task_store` 与 `message_store` 同级？ | ✅ 是，放在同一 DATA_DIR |
| Agent Card 用什么格式？ | JSON 配置文件，`config/agent_cards.json` |
| 任务状态变更推送是否要触发 WS 通知？ | ✅ 是，推送 `MSG_TASK_NOTIFY` |
| Web 端定时刷新用轮询还是 SSE？ | 轮询（复用现有 5s 轮询模式，新增 30s 定时 `!task_query` via WS） |
| `_admin` 频道支持非 `!` 开头的普通消息吗？ | ❌ 不支持，`_admin` 频道已拦截非命令消息 |
| `Auth.json` 里的 `approved_users` 启动后是否立即生效？ | 需要重新认证或重启 |

---

## 1. 设计方案

### 1.1 TaskState 枚举 + 协议常量

**文件：** `shared/protocol.py`

在文件末尾新增：

```python
# ── R38: Task State Machine ──────────────────────────────────────
from enum import Enum

class TaskState(str, Enum):
    SUBMITTED = "submitted"        # ⬜ 已排入流水线，等待执行者
    WORKING = "working"            # ▶ 正在处理
    COMPLETED = "completed"        # ✅ 完成
    FAILED = "failed"              # ❌ 锁定失败
    CANCELED = "canceled"          # ⛔ 已取消
    INPUT_REQUIRED = "input_required"  # 🟡 退回修复

# Task 状态消息类型
MSG_TASK_CREATE = "task_create"    # 创建 Task
MSG_TASK_UPDATE = "task_update"    # 更新 Task 状态
MSG_TASK_QUERY = "task_query"      # 查询 Task
MSG_TASK_NOTIFY = "task_notify"    # 状态变更推送

# Task 字段
FIELD_CONTEXT_ID = "context_id"    # 轮次 ID
FIELD_TASK_ID = "task_id"          # Task ID
FIELD_TASK_STATE = "state"         # 状态字段
FIELD_TASK_STEP = "step"           # Step 编号
FIELD_TASK_NAME = "name"           # Task 名称
FIELD_ASSIGNED_ROLE = "assigned_role"  # 执行者角色 ID
FIELD_OUTPUT_REFS = "output_refs"  # 产出引用
FIELD_REJECT_COUNT = "reject_count"  # 退回次数
```

**设计理由：** 使用 `str` 继承的 Enum 使其可直接 JSON 序列化，减少序列化/反序列化转换。

### 1.2 TaskStore — SQLite 持久化

**文件：** `server/task_store.py`（新建模块）

与 `message_store.py` 同级设计模式，独立文件避免耦合。

```python
"""Task state persistence — R38 Task State Machine."""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from shared.protocol import TaskState

_local = threading.local()

TASKS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT UNIQUE NOT NULL,
    context_id      TEXT NOT NULL,
    step            INTEGER NOT NULL,
    name            TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'submitted',
    assigned_role   TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    output_refs     TEXT NOT NULL DEFAULT '[]',
    reject_count    INTEGER NOT NULL DEFAULT 0
)
"""
```

**关键接口：**

| 函数 | 说明 |
|:-----|:------|
| `init_task_store(data_dir)` | 创建 tasks 表 + 索引 |
| `create_task(context_id, step, name, assigned_role)` → dict | 创建新 Task，返回完整 dict，状态 SUBMITTED |
| `update_task_state(task_id, new_state, reject_count)` → bool | 更新状态，校验合法转换，失败返回 False |
| `query_tasks(context_id)` → list[dict] | 按 context_id 查询所有 Task，按 step 排序 |
| `list_tasks(state=None)` → list[dict] | 按状态过滤查询所有 Task |
| `get_task(task_id)` → dict \| None | 按 task_id 查询单个 Task |

**状态转换校验逻辑（纯规则，内联于 `update_task_state`）：**

```python
_VALID_TRANSITIONS = {
    TaskState.SUBMITTED:       {TaskState.WORKING},
    TaskState.WORKING:         {TaskState.COMPLETED, TaskState.INPUT_REQUIRED,
                                 TaskState.FAILED, TaskState.CANCELED},
    TaskState.INPUT_REQUIRED:  {TaskState.WORKING, TaskState.FAILED},
}

# 额外检查：
# - INPUT_REQUIRED → WORKING 时 reject_count+1
# - reject_count >= 2 时自动锁定为 FAILED（不允许再进入 WORKING）
# - COMPLETED 禁止退回任何状态（最终态）
# - SUBMITTED → COMPLETED ❌ 禁止跳过执行
```

### 1.3 _ADMIN_COMMANDS 扩展 — 4 条新命令

**文件：** `server/handler.py`

在 `_ADMIN_COMMANDS` 注册表中新增 4 条命令：

```python
_ADMIN_COMMANDS: dict[str, dict] = {
    # ... 现有命令 ...
    
    "task_create": {
        "handler": _cmd_task_create, "min_role": 3, "workspace_scope": True,
        "usage": "!task_create --context <id> --step <n> --name <name> --role <role>",
    },
    "task_update": {
        "handler": _cmd_task_update, "min_role": 3, "workspace_scope": True,
        "usage": "!task_update --task-id <uuid> --state <new_state> [--output <ref>]",
    },
    "task_query": {
        "handler": _cmd_task_query, "min_role": 1, "workspace_scope": False,
        "usage": "!task_query --context <id>",
    },
    "task_list": {
        "handler": _cmd_task_list, "min_role": 1, "workspace_scope": False,
        "usage": "!task_list [--state <state>]",
    },
}
```

**权限设计：**
- `task_create` — P3（工作室管理员），工作区范围
- `task_update` — P3（工作室管理员），工作区范围。**注意：** handler 内部额外校验发送者必须是 Task 的 `assigned_role` 或全局管理员（自质量门），P3 仅控制能否进入命令处理器
- `task_query` — P1（全部成员），无工作区限制
- `task_list` — P1（全部成员），无工作区限制

#### 实现函数：`_cmd_task_create`

```python
async def _cmd_task_create(sender_id: str, params: dict) -> str:
    context_id = params.get("context", "").strip()
    step_str = params.get("step", "").strip()
    name = params.get("name", "").strip()
    role = params.get("role", "").strip()
    
    if not context_id or not step_str or not name or not role:
        return "❌ 用法: !task_create --context <id> --step <n> --name <name> --role <role>"
    
    try:
        step = int(step_str)
    except ValueError:
        return f"❌ step 必须为数字，收到: {step_str}"
    
    # 验证 Agent Card 中的角色是否存在
    from .agent_card import get_agent_card
    card = get_agent_card(role)
    if not card:
        return f"❌ 角色 '{role}' 未在 Agent Card 中注册"
    
    task = task_store.create_task(context_id, step, name, role)
    return f"✅ Task 已创建: {task['task_id']} ({context_id} Step {step}: {name}) → {role}"
```

#### 实现函数：`_cmd_task_update`

```python
async def _cmd_task_update(sender_id: str, params: dict) -> str:
    task_id = params.get("task-id", "").strip()
    new_state = params.get("state", "").strip()
    
    if not task_id or not new_state:
        return "❌ 用法: !task_update --task-id <uuid> --state <new_state> [--output <ref>]"
    
    task = task_store.get_task(task_id)
    if not task:
        return f"❌ Task {task_id} 不存在"

    # R38 v1.1: 自质量门 — 发送者必须是 Task 的 assigned_role 或全局管理员
    if task.get("assigned_role") and not auth.is_global_admin(sender_id):
        if sender_id != task["assigned_role"]:
            return f"❌ 权限不足：Task 分配给 {task['assigned_role']}，你不可更新"
    
    success = task_store.update_task_state(task_id, new_state)
    if not success:
        return f"❌ 状态转换非法: {task['state']} → {new_state}"
    
    # 如果有产出引用，一并记录
    output = params.get("output", "")
    if output and new_state == "completed":
        task_store.add_output_ref(task_id, output)
    
    # 推送 MSG_TASK_NOTIFY
    task = task_store.get_task(task_id)
    await _broadcast_task_notify(task)
    
    return f"✅ Task {task_id[:8]} 状态已更新: {new_state}"
```

#### 实现函数：`_cmd_task_query`

```python
async def _cmd_task_query(sender_id: str, params: dict) -> str:
    context_id = params.get("context", "").strip()
    if not context_id:
        return "❌ 用法: !task_query --context <id>"
    
    tasks = task_store.query_tasks(context_id)
    if not tasks:
        return f"📋 {context_id} 暂无 Task"
    
    lines = [f"📋 {context_id} 任务进度："]
    for t in tasks:
        icon = STATE_ICONS.get(t["state"], "⬜")
        lines.append(f"  Step {t['step']:2d} | {t['name']:<12s} | {icon} {t['state']} | 👤 {t['assigned_role']}")
    return "\n".join(lines)
```

#### 状态→图标映射

```python
STATE_ICONS = {
    "submitted": "⬜",
    "working": "▶",
    "completed": "✅",
    "failed": "❌",
    "canceled": "⛔",
    "input_required": "🟡",
}
```

### 1.4 MSG_TASK_NOTIFY 推送

当 `_cmd_task_update` 成功执行状态变更时，调用 `_broadcast_task_notify(task)`：

```python
async def _broadcast_task_notify(task: dict) -> None:
    """推送 MSG_TASK_NOTIFY 给所有在线 agent + Web WS 客户端。"""
    payload = json.dumps({
        "type": p.MSG_TASK_NOTIFY,
        "task": task,
        "ts": time.time(),
    })
    # 推给所有在线 agent
    for agent_id, conns in _connections.items():
        for conn in list(conns):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
    
    # 推给 Web 端 WS 客户端（通过 write_chat_log 或直接推 _ws_clients）
    from .web_viewer import _ws_clients as _web_clients
    dead = set()
    for ws in _web_clients:
        try:
            ws.send_str(payload)
        except Exception:
            dead.add(ws)
    _web_clients -= dead
    
    logger.info("MSG_TASK_NOTIFY broadcast for task %s: %s", task["task_id"][:8], task["state"])
```

### 1.5 Agent Card — 配置级元数据

**文件：** `config/agent_cards.json`（新建）

```json
{
  "admin-bot": {
    "display_name": "小爱",
    "roles": ["admin"],
    "skills": [
      {"id": "manage-platform", "description": "全平台管理"},
      {"id": "merge-deploy", "description": "合并部署"}
    ],
    "triggers": ["!admin", "!merge"],
    "state": "online"
  },
  "pm-bot": {
    "display_name": "小谷",
    "roles": ["product-manager"],
    "skills": [
      {"id": "write-requirements", "description": "撰写需求文档"},
      {"id": "review-requirements", "description": "评审需求"}
    ],
    "triggers": ["!pm", "!需求"],
    "state": "online"
  },
  "arch-bot": {
    "display_name": "小开",
    "roles": ["architect"],
    "skills": [
      {"id": "write-tech-plan", "description": "编写技术方案"},
      {"id": "design-architecture", "description": "架构设计"}
    ],
    "triggers": ["!arch", "!方案"],
    "state": "online"
  },
  "dev-bot": {
    "display_name": "爱泰",
    "roles": ["developer"],
    "skills": [
      {"id": "implement-code", "description": "编码实现"},
      {"id": "fix-bugs", "description": "修复缺陷"}
    ],
    "triggers": ["!dev", "!编码"],
    "state": "online"
  },
  "review-bot": {
    "display_name": "小周",
    "roles": ["reviewer"],
    "skills": [
      {"id": "code-review", "description": "代码审查"},
      {"id": "quality-check", "description": "质量检查"}
    ],
    "triggers": ["!review", "!审查"],
    "state": "online"
  },
  "qa-bot": {
    "display_name": "泰虾",
    "roles": ["qa"],
    "skills": [
      {"id": "test-automation", "description": "自动化测试"},
      {"id": "deploy-dev", "description": "Dev 部署"}
    ],
    "triggers": ["!qa", "!测试"],
    "state": "online"
  }
}
```

**加载机制：** `server/agent_card.py`（新建模块）

```python
import json
from pathlib import Path

_cards: dict = {}
# 项目根目录下的 config/agent_cards.json（与 data/ 同级）
_CARDS_PATH = Path(__file__).parent.parent / "config" / "agent_cards.json"

def load_cards(data_dir: Path) -> None:
    """Load Agent Card definitions from config file.

    Looks for config/agent_cards.json at project root.
    'data_dir' parameter kept for signature compatibility with init_task_store.
    """
    global _cards
    if _CARDS_PATH.exists():
        _cards = json.loads(_CARDS_PATH.read_text())
    else:
        _cards = {}
        logger.warning("Agent Card config not found at %s, using empty set", _CARDS_PATH)
    logger.info("Loaded %d agent cards from %s", len(_cards), _CARDS_PATH)

def get_agent_card(agent_id: str) -> dict | None:
    """Get Agent Card by ID. Returns None if not found."""
    return _cards.get(agent_id)

def get_all_cards() -> dict:
    """Return all Agent Cards."""
    return _cards
```

### 1.6 Web 端 — 进度 Tab

#### 1.6.1 后端 API 扩展

**文件：** `server/web_viewer.py`

新增 API 端点：

```python
async def handle_api_tasks(request: web.Request) -> web.Response:
    """GET /api/tasks?context=R38 — 返回指定轮次的任务进度"""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    
    context_id = request.query.get("context", "")
    if not context_id:
        # 默认返回最近 3 个轮次
        from .task_store import query_recent_contexts
        contexts = query_recent_contexts(3)
        result = {}
        for ctx in contexts:
            result[ctx] = task_store.query_tasks(ctx)
        return web.json_response({"tasks_by_context": result})
    
    tasks = task_store.query_tasks(context_id)
    return web.json_response({"context": context_id, "tasks": tasks})
```

并在 `setup_routes()` 中注册：`app.router.add_get("/api/tasks", handle_api_tasks)`

#### 1.6.2 前端 Tab 结构变更

**文件：** `server/templates.py`

**Tab 布局变更（W-6）：**

当前布局（4-slot）：
```
[活跃] [大厅] [管理员] [历史]
```

新布局（5-slot, W-6）：
```
[活跃] [大厅] [管理员] [📊 进度] [历史]
```

**TAB_STATE 扩展：**

```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: 'lobby',             label: '🌐 大厅',       permanent: true,  visible: true },
  tab2: { id: 'tab2', channel: null,                 label: '📋 活跃',       permanent: false, visible: false },
  tab3: { id: 'tab3', channel: null,                 label: '🗂️ 历史查看器', permanent: true,  visible: true },
  tab4: { id: 'tab4', channel: '_admin',             label: '🔧 管理员',     permanent: true,  visible: true },
  tab5: { id: 'tab5', channel: '__progress__',       label: '📊 进度',       permanent: true,  visible: true },  // NEW
};
```

**Tab 排序规则（W-6）：** 有活跃工作室时 → `tab2(活跃) → tab1(大厅) → tab4(管理员) → tab5(📊 进度) → tab3(历史)`

`renderTabBar()` 按此顺序输出 HTML。

**下拉刷新规则（W-7）：** 刷新时回到第一个 Tab（有活跃 → 活跃 tab2，无活跃 → 大厅 tab1）。

```javascript
// ── R38 W-7: Pull-to-refresh returns to first tab ──
// When page reloads after refresh, init() restores tab2 from localStorage
// then verifies with /api/workspaces. If active workspace exists,
// first visible tab = tab2 (活跃). Otherwise = tab1 (大厅).
```

#### 1.6.3 进度面板渲染

```javascript
// ── R38: Progress tab rendering ──
async function renderProgressTab() {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载进度中...</div>';
  try {
    const resp = await fetch('/api/tasks?token=' + encodeURIComponent(TOKEN));
    const data = await resp.json();
    const tasksByContext = data.tasks_by_context || {};
    const contextIds = Object.keys(tasksByContext).sort().reverse(); // newest first
    
    if (contextIds.length === 0) {
      list.innerHTML = '<div class="empty">暂无任务进度</div>';
      return;
    }
    
    list.innerHTML = '';
    for (const ctxId of contextIds) {
      const tasks = tasksByContext[ctxId] || [];
      const section = document.createElement('div');
      section.className = 'progress-section';
      
      let html = `<div class="progress-header">📋 ${escapeHtml(ctxId)}</div>`;
      html += '<table class="progress-table"><tr><th>Step</th><th>环节名称</th><th>工作人</th><th>状态</th></tr>';
      
      for (const t of tasks) {
        const icon = STATE_ICONS[t.state] || '⬜';
        // Look up display_name from Agent Card
        const roleName = AGENT_CARDS[t.assigned_role]?.display_name || t.assigned_role;
        html += `<tr>
          <td>${t.step}</td>
          <td>${escapeHtml(t.name)}</td>
          <td>${escapeHtml(roleName)}</td>
          <td>${icon} ${escapeHtml(t.state)}</td>
        </tr>`;
      }
      html += '</table>';
      section.innerHTML = html;
      list.appendChild(section);
    }
  } catch(e) {
    list.innerHTML = '<div class="empty">加载失败（网络异常）</div>';
  }
}
```

**CSS 新增样式：**

```css
.progress-section{margin-bottom:16px;}
.progress-header{font-size:0.95rem;font-weight:600;padding:8px 0;color:#58a6ff;}
.progress-table{width:100%;border-collapse:collapse;font-size:0.85rem;}
.progress-table th{text-align:left;padding:6px 8px;border-bottom:1px solid #30363d;color:#8b949e;}
.progress-table td{padding:6px 8px;border-bottom:1px solid #21262d;}
```

**定时刷新（W-4）：** 每 30s 调用 `renderProgressTab()` 当进度 Tab 活跃时。

**Agent Card 前端缓存（用于工作人列查 display_name）：**

```javascript
let AGENT_CARDS = {};
async function loadAgentCards() {
  try {
    const resp = await fetch('/api/agent-cards');
    const data = await resp.json();
    AGENT_CARDS = data.cards || {};
  } catch(e) {}
}
```

### 1.7 双入口同步

**文件：** `server/handler.py`（websockets）和 `server/__main__.py`（aiohttp）

#### handler.py 路径

`handle_broadcast()` 中 `_admin` 频道拦截已自动处理 `!task_create/update/query/list` — 无需额外改动，因为 `!_ADMIN_COMMANDS` 注册表是共享入口。

`_cmd_task_update` 中的 `_broadcast_task_notify` 使用 `_connections` 全局推送，websockets 路径无需修改。

#### __main__.py 路径

在 `ws_handler()` 的 if-elif 链中新增 `MSG_TASK_NOTIFY` 消息类型的直接处理：

```python
# ── R38: Task state notification (push to web clients) ────────────
elif msg_type == p.MSG_TASK_NOTIFY and agent_id:
    # Relay to Web WS clients
    from .web_viewer import _ws_clients as _web_clients
    import json as _json
    payload = _json.dumps(data)
    dead = set()
    for ws_client in _web_clients:
        try:
            await ws_client.send_str(payload)
        except Exception:
            dead.add(ws_client)
    _web_clients -= dead
```

**双入口验证：** 修改后用以下命令确认：

```bash
grep -n "MSG_TASK_CREATE\|MSG_TASK_UPDATE\|MSG_TASK_QUERY\|MSG_TASK_NOTIFY\|elif msg_type" server/handler.py server/__main__.py
```

---

## 2. 验收标准映射

| 验收标准 | 实现位置 | 说明 |
|:---------|:---------|:------|
| **S-1** TaskState 枚举（6 种状态+转换规则） | `shared/protocol.py` — TaskState Enum + `task_store.py` — `_VALID_TRANSITIONS` | 枚举定义 + 转换校验矩阵 |
| **S-2** 4 种消息类型常量 + FIELD_ 常量 | `shared/protocol.py` — MSG_TASK_CREATE/UPDATE/QUERY/NOTIFY + FIELD_* | 新增 8+ 常量 |
| **S-3** Task 数据模型（全部字段） | `server/task_store.py` — `create_task()`, TASKS_TABLE_DDL | SQLite schema + Python dict |
| **S-4** `_ADMIN_COMMANDS` 注册表新增 4 命令 | `server/handler.py` — `_ADMIN_COMMANDS` | task_create, task_update, task_query, task_list |
| **S-5** `!task_create` 创建 Task 返回 task_id | `server/handler.py` — `_cmd_task_create()` | 验证 Agent Card 角色存在 |
| **S-6** `!task_update` 合法/非法转换 | `server/handler.py` — `_cmd_task_update()` + `task_store.py` — `update_task_state()` | 非法返回错误消息 |
| **S-7** reject_count 递增 + 自动 FAILED | `task_store.py` — `update_task_state()` | INPUT_REQUIRED→WORKING 递增；≥2 自动 FAILED |
| **S-8** `!task_query --context` 按 step 排序返回 | `_cmd_task_query()` + `task_store.query_tasks()` | ORDER BY step ASC |
| **S-9** `!task_list --state` 过滤 | `_cmd_task_list()` + `task_store.list_tasks(state)` | 可选状态过滤 |
| **S-10** SQLite `task_store` 表持久化 | `server/task_store.py` — `init_task_store()` | 独立文件，restart 不丢失 |
| **S-11** 状态变更推送 MSG_TASK_NOTIFY | `handler.py` — `_broadcast_task_notify()` | 推给所有在线 agent + Web WS |
| **S-12** `--output` 记录产出引用 | `_cmd_task_update()` + `task_store.add_output_ref()` | commit SHA / 报告路径 |
| **S-13** 双入口同步 | handler.py + `__main__.py` | `__main__.py` 新增 MSG_TASK_NOTIFY 分支 |
| **S-14** Agent Card 配置文件 | `config/agent_cards.json` + `server/agent_card.py` | 6 个角色定义完整 |
| **S-15** `!task_create --role` 验证角色存在 | `_cmd_task_create()` — `get_agent_card(role)` | 不存在时返回错误 |
| **W-1** 新增进度 Tab | `templates.py` — TAB_STATE.tab5, `web_viewer.py` — `/api/tasks` | 5-slot 布局 |
| **W-2** 表格列完整（Step/环节名称/工作人/状态） | `templates.py` — `renderProgressTab()` | 4 列渲染 |
| **W-3** 按 contextId 分组，最近 3 个轮次 | `web_viewer.py` — `handle_api_tasks()` | 默认返回最近 3 个 |
| **W-4** 定时刷新 30s | `templates.py` — setInterval | 进度 Tab 激活时 |
| **W-5** 状态彩色标记 | `templates.py` — `STATE_ICONS` + CSS | 🟢 ✅ ▶ ⬜ 🟡 ❌ ⛔ |
| **W-6** Tab 排序规则 | `templates.py` — `renderTabBar()` | 活跃→大厅→管理员→📊进度→历史 |
| **W-7** 下拉刷新回到第一个 Tab | `templates.py` — `init()` | 有活跃→活跃，无活跃→大厅 |

---

## 3. 修改文件清单

| # | 文件 | 操作 | 预估行数 | 优先级 |
|:-:|:-----|:----:|:--------:|:------:|
| ① | `shared/protocol.py` | 新增 TaskState enum + 消息类型 + FIELD_ 常量 | ~60 行 | P0 |
| ② | `server/task_store.py` | **新建** — SQLite 持久化模块 | ~180 行 | P0 |
| ③ | `server/handler.py` | 新增 4 条 _ADMIN_COMMANDS 处理函数 + `_broadcast_task_notify` | ~200 行 | P0 |
| ④ | `server/__main__.py` | 新增 MSG_TASK_NOTIFY 分支（双入口同步） | ~20 行 | P0 |
| ⑤ | `config/agent_cards.json` | **新建** — Agent Card 配置定义 | ~80 行 | P1 |
| ⑥ | `server/agent_card.py` | **新建** — Agent Card 加载/查询模块 | ~40 行 | P1 |
| ⑦ | `server/web_viewer.py` | 新增 `/api/tasks` + `/api/agent-cards` + `init_task_store()` 调用 | ~80 行 | P0 |
| ⑧ | `server/templates.py` | Tab 排序规则（W-6）+ 进度 Tab 渲染（W-1~W-5）+ 下拉刷新（W-7） | ~120 行 | P0 |
| ⑨ | `server/__main__.py` | `main()` 中调用 `init_task_store(DATA_DIR)` 和 `agent_card.load_cards(DATA_DIR)` | ~5 行 | P0 |
| ⑩ | `server/handler.py` | 文件头新增 `from . import task_store` import | ~2 行 | P0 |

**预估总计：约 787 行新增/修改**

---

## 4. 风险与边界

| 风险 | 等级 | 缓解措施 |
|:-----|:----:|:---------|
| TaskStore 表与 MessageStore 事务不一致 | 低 | 独立 DB 文件，不涉及跨表事务 |
| 并发状态更新冲突 | 低 | SQLite WAL 模式 + 单线程写入 |
| WS 推送消息体过大（大量 Task） | 低 | 限制默认返回最近 3 个轮次 |
| localStorage 中 Agent Card 与服务器不同步 | 低 | 页面刷新时重新加载 |
| 双入口 MSG_TASK_NOTIFY 推送导致重复 | 低 | `handler.py` 只在 `_cmd_task_update` 中推一次，`__main__.py` 只 relay Web 路径 |
| `_admin` 频道非 ! 消息被拦截 | 无风险 | Task 命令以 `!` 开头，不会触发拦截 |

---

## 5. 验证清单

### 5.1 单元验证

```bash
# 验证 TaskState 枚举定义
grep -n "class TaskState\|SUBMITTED\|WORKING\|COMPLETED\|FAILED\|CANCELED\|INPUT_REQUIRED" shared/protocol.py

# 验证协议常量
grep -n "MSG_TASK_\|FIELD_TASK_\|FIELD_CONTEXT_ID\|FIELD_REJECT_COUNT\|FIELD_ASSIGNED_ROLE" shared/protocol.py

# 验证 _ADMIN_COMMANDS 注册
grep -n "task_create\|task_update\|task_query\|task_list" server/handler.py

# 验证双入口同步
grep -n "MSG_TASK_NOTIFY" server/__main__.py
```

### 5.2 功能验证

| # | 验证项 | 方法 |
|:-:|:-------|:-----|
| 1 | `!task_create` 创建成功 | 发送命令，确认返回 task_id |
| 2 | `!task_update --state COMPLETED` 合法转换 | 发送命令，确认状态更新 |
| 3 | `!task_update --state COMPLETED` 从 SUBMITTED 非法 | 应返回错误消息 |
| 4 | `!task_update --state WORKING` INPUT_REQUIRED→WORKING | reject_count 递增 |
| 5 | 2 次退回后自动 FAILED | reject_count≥2 自动锁定 |
| 6 | `!task_query --context R38` 返回结果 | 返回排序后的 tasks |
| 7 | Agent Card 角色不存在时创建失败 | 返回错误消息 |
| 8 | Web 端进度 Tab 显示 | 确认表格渲染正确 |
| 9 | Tab 排序：活跃→大厅→管理员→进度→历史 | 确认顺序 |
| 10 | 下拉刷新回到第一个 Tab | 确认行为 |

---

## 6. 不纳入本次实现

| 不纳入 | 理由 |
|:-------|:------|
| Agent Card JWT 签名 | 内部环境不需要 |
| `/api/agent-cards` 接口缓存 | 配置级文件，读取量小，不需要 |
| Task 自动流转 | 本次只做状态记录，自动推进留到后续轮次 |
| Web 端进度 Tab SSE 推送 | 30s 轮询够用，SSE 留到后续优化 |
| 进度 Tab 手动刷新按钮 | 自动 30s 轮询 + WebSocket 推送即足够 |
