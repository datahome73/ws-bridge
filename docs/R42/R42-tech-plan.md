# R42 技术方案 — 管线自动触发与 Step 接力

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-27
> **需求文档：** [R42-product-requirements.md](R42-product-requirements.md)
> **工作计划：** [WORK_PLAN.md](WORK_PLAN.md)

---

## 目录

- [Part A — 方案设计](#part-a--方案设计)
  - [A-1 方向 A：`!pipeline_start` 管线入口](#a-1-方向-apipeline_start-管线入口)
  - [A-2 方向 B：`!step_complete` Step 接力](#a-2-方向-bstep_complete-step-接力)
  - [A-3 方向 C：`!pipeline_status` 管线状态查询](#a-3-方向-cpipeline_status-管线状态查询)
  - [A-4 方向 D：大厅隔离](#a-4-方向-d大厅隔离)
  - [A-5 配置文件：Step 映射表](#a-5-配置文件step-映射表)
- [Part B — 向后兼容分析](#part-b--向后兼容分析)
- [Part C — 验收标准映射](#part-c--验收标准映射)
- [附录](#附录)

---

## Part A — 方案设计

### 核心架构图

```
_admin 频道
    │
    ├─ !pipeline_start R42
    │     │
    │     ├─ ① 验证前置决策（docs/R42/WORK_PLAN.md ✅）
    │     ├─ ② 暂停大厅接收（global flag → handler.py:1084）
    │     ├─ ③ 调用 !create_workspace R42-dev --members <角色>
    │     ├─ ④ 工作室自动点名（已有 _auto_rollcall_notify）
    │     ├─ ⑤ 自动点名架构师（!rollcall_next arch-bot --context <URL+WORK_PLAN>）
    │     └─ ⑥ 创建 Step Task（!task_create --context R42 --name step3 --role arch-bot）
    │
    ├─ !step_complete Step3 --output 342c794
    │     │
    │     ├─ ① 标记当前 Task completed
    │     ├─ ② 查 Step 映射表 → 找下一角色
    │     ├─ ③ 调用 !rollcall_next <下一角色> --context <产出摘要>
    │     └─ ④ 通知 PM（_admin 频道发送进度更新）
    │
    ├─ !pipeline_status
    │     │
    │     └─ 聚合所有 Step Task → 输出进度表
    │
    └─ !step_complete Step7 --output done
          │
          ├─ ① 标记管线结束 Task completed
          ├─ ② 恢复大厅接收（global flag → false）
          └─ ③ 关闭工作室（!close_workspace）
```

---

### A-1 方向 A：`!pipeline_start` 管线入口

#### 新增命令

```python
# handler.py: _ADMIN_COMMANDS 新增
"pipeline_start": {
    "handler": _cmd_pipeline_start,
    "min_role": 3,       # P3+ (workspace admin)
    "workspace_scope": False,  # _admin 频道触发，非工作区
    "usage": "!pipeline_start <R{N}> [--from <step>]",
},
```

#### 函数逻辑

```python
# handler.py: ~L920 新增
async def _cmd_pipeline_start(sender_id: str, params: dict) -> str:
    """启动管线。
    用法：!pipeline_start <R{N}> [--from <step>]
    仅在 _admin 频道可用。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_start <R{N}> [--from <step>]"

    round_name = positional[0].upper()  # e.g. "R42"
    from_step = params.get("from", "")  # "--from step3" (可选)

    # ① 验证前置决策状态
    work_plan_path = f"docs/{round_name}/WORK_PLAN.md"
    # 检查 WORK_PLAN 是否存在且有 ✅ 标记（文件存在检查）
    if not os.path.exists(work_plan_path):
        return f"❌ {round_name} 未找到 WORK_PLAN.md，请先完成 Step A/B"

    # ② 锁定管线（防重复）
    if pipeline_is_active(round_name):
        return f"❌ {round_name} 管线已活跃，不可重复启动"

    # ③ 暂停大厅接收（方向 D）
    set_lobby_paused(True, round_name)

    # ④ 创建工作室
    from server.handler import _cmd_create_workspace
    create_params = {
        "_positional": [f"{round_name}-dev"],
        "members": "",  # 角色自动加入
    }
    create_result = await _cmd_create_workspace(sender_id, create_params)
    # 从结果提取 ws_id
    ws_id = f"{p.WORKSPACE_ID_PREFIX}{sender_id[:8]}-{round_name}-dev"

    # ⑤ 派发 Step 上下文
    # 查 Step 映射表，找到起始角色
    step_map = _load_step_config()
    start_step = from_step if from_step else "step3"  # 默认从架构师开始
    target_role = step_map[start_step]["role"]

    context_urls = f"需求: docs/{round_name}/R42-product-requirements.md | WORK_PLAN: docs/{round_name}/WORK_PLAN.md"
    rollcall_result = await _cmd_rollcall_next(sender_id, {
        "_positional": [target_role],
        "context": f"R42 {start_step}: {context_urls}",
    })

    # ⑥ 创建 Step Task
    task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": start_step,
        "role": target_role,
    })

    # 设置活跃管线状态
    _set_pipeline_state(round_name, {
        "active": True,
        "current_step": start_step,
        "ws_id": ws_id,
        "started_at": time.time(),
    })

    return (
        f"🚀 **{round_name} 管线已启动**\n"
        f"  Step: {start_step} → {target_role}\n"
        f"  工作室: {ws_id}\n"
        f"  {create_result}\n"
        f"  {rollcall_result}\n"
        f"  {task_result}"
    )
```

#### 关键状态变量

新增两个全局状态（handler.py 模块级）：

```python
# handler.py: 管线全局状态
_PIPELINE_STATE: dict[str, dict] = {}  # round_name → {active, current_step, ws_id, ...}
_LOBBY_PAUSED: bool = False            # 方向 D：大厅暂停标志
_LOBBY_PAUSED_ROUND: str = ""          # 锁定的轮次名
```

#### 锁机制

- `_PIPELINE_STATE` 字典：round_name → pipeline dict
- `pipeline_is_active(round_name)`: 检查该轮次是否已有活跃管线
- 同一轮次不可重复启动；不同轮次可独立（但大厅暂停是全局的）

#### 文件变更

| 文件 | 变更 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` | 新增 `_cmd_pipeline_start` + 状态变量 + 辅助函数 | ~50 行 |
| `server/handler.py` | 新增 `_load_step_config()` 读取 Step 映射表 | ~15 行 |
| `server/handler.py` | `_ADMIN_COMMANDS` 注册 `pipeline_start` | ~5 行 |

---

### A-2 方向 B：`!step_complete` Step 接力

#### 新增命令

```python
"step_complete": {
    "handler": _cmd_step_complete,
    "min_role": 3,       # P3+ (workspace admin)
    "workspace_scope": True,  # 工作室中执行
    "usage": "!step_complete <step_name> --output <commit/file>",
},
```

#### 函数逻辑

```python
# handler.py: 新增
async def _cmd_step_complete(sender_id: str, params: dict) -> str:
    """标记 Step 完成，自动点名下一人。
    用法：!step_complete <step_name> --output <commit/file>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_complete <step_name> --output <commit/file>"
    step_name = positional[0]
    output_ref = params.get("output", "")
    if not output_ref:
        return "❌ --output 为必填参数，请提供 commit SHA 或文件路径"

    # 获取当前所在的轮次和工作区
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    # 从 ws name 提取 round_name
    round_name = None
    for rname, pstate in _PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    # ① 标记当前 Task completed
    tasks = ts.get_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ 未找到 Step「{step_name}」的活跃 Task（可能已完成）"

    task_result = await _cmd_task_update(sender_id, {
        "_positional": [current_task["id"]],
        "state": p.TaskState.COMPLETED.value,
        "output": output_ref,
    })

    # ② 查 Step 映射表 → 找下一角色
    step_config = _load_step_config()
    step_keys = sorted(step_config.keys(), key=lambda k: _step_sort_key(k))
    current_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            current_idx = i
            break
    if current_idx is None or current_idx + 1 >= len(step_keys):
        # 最后一步 → 管线结束
        await _cmd_close_workspace(sender_id, {"_positional": [sender_ch]})
        set_lobby_paused(False)
        _clear_pipeline_state(round_name)
        return (
            f"🏁 **{round_name} 管线已完成！**\n"
            f"  {task_result}\n"
            f"  工作室已关闭，大厅已恢复接收"
        )

    next_step = step_keys[current_idx + 1]
    next_role = step_config[next_step]["role"]

    # ③ 调用 !rollcall_next 点名下一角色
    context_summary = f"上一 Step「{step_name}」产出: {output_ref}"
    rollcall_result = await _cmd_rollcall_next(sender_id, {
        "_positional": [next_role],
        "context": f"{round_name} {next_step}: {context_summary}",
    })

    # ④ 创建下一步的 Task
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": next_step,
        "role": next_role,
    })

    # 更新管线状态
    _update_pipeline_step(round_name, next_step)

    # ⑤ 通知 PM（在 _admin 频道发进度）
    try:
        admin_channel = p.ADMIN_CHANNEL
        notify_msg = f"📋 {round_name} 进度：{step_name} ✅ → 下一棒 {next_role}（{next_step}）产出: {output_ref}"
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=notify_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    return (
        f"✅ **{step_name} 完成** → 交接给 {next_role} {next_step}\n"
        f"  {task_result}\n"
        f"  {rollcall_result}\n"
        f"  {next_task_result}"
    )
```

#### Step 映射表的排序辅助函数

```python
def _step_sort_key(step_name: str) -> tuple:
    """将 step1, step2, ..., step10 正确排序"""
    import re
    m = re.match(r'step(\d+)', step_name.lower())
    return (int(m.group(1)),) if m else (0, step_name)
```

#### 文件变更

| 文件 | 变更 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` | 新增 `_cmd_step_complete` + `_step_sort_key` | ~80 行 |
| `server/handler.py` | `_ADMIN_COMMANDS` 注册 `step_complete` | ~5 行 |

---

### A-3 方向 C：`!pipeline_status` 管线状态查询

#### 新增命令

```python
"pipeline_status": {
    "handler": _cmd_pipeline_status,
    "min_role": 3,       # P3+
    "workspace_scope": False,  # _admin 频道或任意频道
    "usage": "!pipeline_status",
},
```

#### 函数逻辑

```python
async def _cmd_pipeline_status(sender_id: str, params: dict) -> str:
    """查询当前所有活跃管线的 Step 进度表。"""
    if not _PIPELINE_STATE:
        return "📊 当前无活跃管线"

    lines = []
    for round_name, pstate in sorted(_PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        lines.append(f"📊 **{round_name} 管线状态**")
        # 读取该轮次的 Step 配置
        step_config = _load_step_config()
        tasks = ts.get_tasks_by_context(round_name, config.DATA_DIR)

        for step_key, step_info in sorted(
            step_config.items(),
            key=lambda x: _step_sort_key(x[0]),
        ):
            role = step_info["role"]
            task_name = step_info.get("name", step_key)

            # 查找对应的 task
            task_state = "⏳"
            matched = [t for t in tasks if t.get("name") == step_key]
            if matched:
                t = matched[0]
                ts_state = t.get("state", "")
                if ts_state == p.TaskState.COMPLETED.value:
                    task_state = "✅"
                elif ts_state == p.TaskState.WORKING.value:
                    task_state = "🟢"
                elif ts_state == p.TaskState.FAILED.value:
                    task_state = "❌"
                else:
                    task_state = "⏳"

            # 当前活跃 Step 标记
            current = " ◀ 当前" if step_key == pstate.get("current_step") else ""
            lines.append(f"  {task_state} {step_key} — {role}{current}")

    if len(lines) == 0:
        return "📊 当前无活跃管线"
    return "\n".join(lines)
```

#### 文件变更

| 文件 | 变更 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` | 新增 `_cmd_pipeline_status` | ~35 行 |
| `server/handler.py` | `_ADMIN_COMMANDS` 注册 `pipeline_status` | ~5 行 |

---

### A-4 方向 D：大厅隔离

#### 设计思路

管线启动时暂停大厅消息路由，所有消息强制走工作室。管线结束时恢复。

#### 全局标志

```python
# handler.py: 模块级
_LOBBY_PAUSED: bool = False
_LOBBY_PAUSED_ROUND: str = ""
```

#### 拦截点：`handle_broadcast()` 路由前

在 `handle_broadcast()` 的 channel 解析后、workspace routing 之前增加拦截。精确位置是 **L1084（Channel resolution 之后）和 L1109（广播权限检查之前）之间**。

```python
# ── R42 D: Lobby pause intercept ──
if _LOBBY_PAUSED and channel == p.LOBBY:
    # 如果发送者有活跃工作区，自动路由到工作区
    agent_workspaces = ws_mod.get_workspaces_for_agent(sender_id)
    active = [w for w in agent_workspaces if w.state == ws_mod.WorkspaceState.ACTIVE]
    if active:
        channel = active[0].id
        resolved_workspace = active[0]
        logger.info("R42 lobby-pause: routed %s to workspace '%s'", sender_id[:12], channel)
    else:
        await _send(ws, {
            "type": "error",
            "error": f"🔒 管线 {_LOBBY_PAUSED_ROUND} 进行中，大厅已暂停接收消息。请在工作区中发言。",
        })
        return
```

**为什么插在 L1084：** Channel resolution 已经解析了当前频道。如果解析结果是 lobby（无工作区），拦截触发；如果解析结果已经是工作区（有 active workspace），拦截不触发——**D-2（自动路由到工作室）天然满足**。

#### 辅助函数

```python
def set_lobby_paused(paused: bool, round_name: str = "") -> None:
    global _LOBBY_PAUSED, _LOBBY_PAUSED_ROUND
    _LOBBY_PAUSED = paused
    _LOBBY_PAUSED_ROUND = round_name if paused else ""
    logger.info("R42 lobby-pause: %s (round=%s)", paused, _LOBBY_PAUSED_ROUND)
```

#### 管线状态管理辅助函数

```python
def _set_pipeline_state(round_name: str, state: dict) -> None:
    _PIPELINE_STATE[round_name] = state

def _update_pipeline_step(round_name: str, step: str) -> None:
    if round_name in _PIPELINE_STATE:
        _PIPELINE_STATE[round_name]["current_step"] = step

def _clear_pipeline_state(round_name: str) -> None:
    _PIPELINE_STATE.pop(round_name, None)

def pipeline_is_active(round_name: str) -> bool:
    state = _PIPELINE_STATE.get(round_name)
    return bool(state and state.get("active"))
```

#### D-4 恢复后历史不受影响

暂停期间 `save_message()` 和 `write_chat_log()` 走工作室频道，大厅的已有聊天记录（历史消息）在数据库中保持不变。暂停只影响新消息的路由，不删除或修改已有记录。

#### D-6 异常终止恢复

服务器重启后 `_LOBBY_PAUSED` 会重置为 `False`（模块变量重新初始化）。这是天然行为——重启后大厅自动恢复接收。D-6 无需额外代码。

#### 文件变更

| 文件 | 变更 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` | 模块级 `_LOBBY_PAUSED` + `_LOBBY_PAUSED_ROUND` | 3 行 |
| `server/handler.py` | `handle_broadcast()` 大厅暂停拦截（L1084 附近） | ~15 行 |
| `server/handler.py` | 新增 `set_lobby_paused()` + 管线状态管理函数 | ~15 行 |

---

### A-5 配置文件：Step 映射表

#### 方案

映射表放在 `server/config.py` 中，作为 Python 变量（与应用现有模式一致，参考 `OAUTH_NAME_MAP`）。

```python
# config.py: R42 Step 映射表
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "admin", "name": "创建工作室"},
    "step2": {"role": "qa", "name": "点名报道"},
    "step3": {"role": "arch", "name": "技术方案"},
    "step4": {"role": "dev", "name": "编码"},
    "step5": {"role": "review", "name": "代码审查"},
    "step6": {"role": "qa", "name": "测试验证"},
    "step7": {"role": "admin", "name": "合并部署归档"},
}
```

**为什么不放 JSON/YAML 文件？**
- 当前项目已使用 `config.py` 模式（`OAUTH_NAME_MAP`、`ADMIN_AGENTS` 等），一致性好
- 硬编码 Python dict 在启动时加载，零额外 IO
- 无需额外文件读取逻辑

#### 增加可覆盖性

环境变量 `PIPELINE_STEP_MAP_OVERRIDE` 允许按 JSON 格式覆盖（与 `OAUTH_NAME_MAP` 模式一致）：

```python
# config.py
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "admin", "name": "创建工作室"},
    "step2": {"role": "qa", "name": "点名报道"},
    "step3": {"role": "arch", "name": "技术方案"},
    "step4": {"role": "dev", "name": "编码"},
    "step5": {"role": "review", "name": "代码审查"},
    "step6": {"role": "qa", "name": "测试验证"},
    "step7": {"role": "admin", "name": "合并部署归档"},
}
_override_raw = os.environ.get("PIPELINE_STEP_MAP_OVERRIDE", "")
if _override_raw.strip():
    import json as _j
    try:
        override = _j.loads(_override_raw)
        PIPELINE_STEP_MAP.update(override)
    except _j.JSONDecodeError:
        pass
```

#### 文件变更

| 文件 | 变更 | 行数 |
|:-----|:-----|:----:|
| `server/config.py` | 新增 `PIPELINE_STEP_MAP` + 环境变量覆盖逻辑 | ~18 行 |

---

## Part B — 向后兼容分析

### B-1 已有命令不受影响

| 已有命令 | 影响 | 说明 |
|:---------|:----|:------|
| `!create_workspace` | ✅ 无影响 | 新命令内部调用它，不变更其行为 |
| `!close_workspace` | ✅ 无影响 | 管线结束时调用 |
| `!rollcall_role` | ✅ 无影响 | 方向 B 用 `!rollcall_next` 而非 `!rollcall_role` |
| `!rollcall_next` | ✅ 无影响 | 新命令复用其签到通知逻辑 |
| `!task_create/list/update/query` | ✅ 无影响 | 新命令复用其创建/更新逻辑 |
| `!approve_pairing` | ✅ 无影响 | 不涉及 |
| `!list_agents` | ✅ 无影响 | 不涉及 |
| `!agent_status` | ✅ 无影响 | 不涉及 |
| `!audit_log` | ✅ 无影响 | 不涉及 |

### B-2 旧流程继续可用

人工流程（code 块 → TG DM 转发 → 人工 @mention）完全不受影响：
- `_admin` 频道入口已存在且不变
- `!create_workspace` 依然在工作群可用
- 手动点名流程不变

### B-3 大厅暂停的向后兼容

- 无活跃管线时，`_LOBBY_PAUSED = False`，大厅行为零变化
- 有活跃管线时，大厅暂停消息路由。但用户在工作室中可正常发言
- 异常重启后 `_LOBBY_PAUSED` 自动重置为 `False`

---

## Part C — 验收标准映射

### 方向 A

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| A-1 | `_admin` 发 `!pipeline_start R42` → 工作室创建 | 执行命令，检查返回 ✅ | 🔴 P1 |
| A-2 | 创建后自动发起点名报道 | 观察 `_auto_rollcall_notify` 调用 | 🔴 P1 |
| A-3 | 点名完成后自动点名架构师，附带需求文档 URL | 观察 `!rollcall_next arch-bot --context <URL>` | 🔴 P1 |
| A-4 | 架构师 task 可通过 `!task_query` 查到 | 执行 `!task_query --context R42` | 🟡 P2 |
| A-5 | 非 `_admin` 频道发 `!pipeline_start` 返回拒绝 | 在工作室/大厅尝试 | 🟡 P2 |
| A-6 | 重复调用返回「已完成」 | 调两遍 `!pipeline_start R42` | 🟡 P2 |

### 方向 B

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| B-1 | `!step_complete Step3 --output 342c794` → 点名开发工程师 | 执行后观察 `!rollcall_next dev-bot` | 🔴 P1 |
| B-2 | 开发工程师收到点名含 commit 引用 | 检查点名消息中 `342c794` 出现 | 🔴 P1 |
| B-3 | Step Task 被标记 completed | 执行 `!task_query <task_id>` | 🔴 P1 |
| B-4 | `--output` 缺省返回用法提示 | 执行 `!step_complete Step3` 不带参数 | 🟡 P2 |
| B-5 | Step 7 完成标记管线结束 | 执行后检查工作室关闭+大厅恢复 | 🟡 P2 |

### 方向 C

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| C-1 | `!pipeline_status` 返回 Step 进度表 | 执行后观察输出表格 | 🟡 P2 |
| C-2 | 活跃 Step 🟢，已完成 ✅，未轮到 ⏳ | 观察输出中的状态图标 | 🟢 P3 |
| C-3 | 无活跃管线时返回「当前无活跃管线」 | 无管线时执行 | 🟢 P3 |

### 方向 D

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| D-1 | `!pipeline_start` 后大厅停止接收新消息 | 在发令后从大厅发言，观察被拒 | 🔴 P1 |
| D-2 | 消息自动路由到工作室 | 在管线期间发言，检查路由到工作室 | 🔴 P1 |
| D-3 | Step 7 完成后大厅恢复接收 | 管线结束后从大厅发言，检查正常 | 🔴 P1 |
| D-4 | 恢复后已有历史不受影响 | 暂停前后查 `!task_query` | 🔴 P1 |
| D-5 | 工作室在管线结束时自动关闭 | 观察 `!close_workspace` 自动调用 | 🟡 P2 |
| D-6 | 异常终止（重启）自动恢复大厅 | 重启服务后大厅消息正常 | 🟡 P2 |

---

## 附录

### 附录 A — 代码变更汇总

| 文件 | 新增/修改 | 估算行数 |
|:-----|:----------|:--------:|
| `server/handler.py` | `_cmd_pipeline_start` 函数 | ~50 行 |
| `server/handler.py` | `_cmd_step_complete` 函数 | ~80 行 |
| `server/handler.py` | `_cmd_pipeline_status` 函数 | ~35 行 |
| `server/handler.py` | `_step_sort_key` 辅助函数 | ~5 行 |
| `server/handler.py` | 管线状态变量 + 管理函数 | ~20 行 |
| `server/handler.py` | `handle_broadcast()` 大厅拦截 | ~15 行 |
| `server/handler.py` | `_ADMIN_COMMANDS` 注册 3 条命令 | ~15 行 |
| `server/config.py` | `PIPELINE_STEP_MAP` + 环境变量覆盖 | ~18 行 |
| **合计** | | **~238 行** |

### 附录 B — 双入口同步检查

| 代码点 | handler.py | __main__.py | 说明 |
|:-------|:----------:|:-----------:|:-----|
| `_cmd_pipeline_start` | 新增 | — | 纯 admin 命令，不走 ws_handler |
| `_cmd_step_complete` | 新增 | — | 纯 admin 命令 |
| `_cmd_pipeline_status` | 新增 | — | 纯 admin 命令 |
| `handle_broadcast()` 大厅拦截 | L1084 插入 | — | ws_handler 中无等价 lobby routing |
| `_LOBBY_PAUSED` 全局变量 | 模块级 | — | 无状态复制需要 |

> **注意：** 所有新命令通过 `_ADMIN_COMMANDS` 注册，由 `handle_broadcast()` 中的 `_admin` channel 拦截统一分发。`__main__.py::ws_handler()` 中的 `MSG_ADMIN_REQUEST` 路径（L2345）不涉及这些命令——四命令均在 `_admin` 频道由 `handle_broadcast()` 解析。因此**无双入口同步问题**。

### 附录 C — Step 映射表参考

| Key | 角色 | 显示名 |
|:----|:----:|:-------|
| step1 | admin | 创建工作室 |
| step2 | qa | 点名报道 |
| step3 | arch | 技术方案 |
| step4 | dev | 编码 |
| step5 | review | 代码审查 |
| step6 | qa | 测试验证 |
| step7 | admin | 合并部署归档 |
