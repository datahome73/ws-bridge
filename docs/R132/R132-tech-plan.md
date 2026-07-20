# R132 技术方案 — `##step` 命令迁移（`!` 命令统一化收官）

> **起草人：** 📐 Arch（小开）
> **版本：** v1.0
> **基线：** `origin/dev` (当前 HEAD)
> **参考：** `docs/R132/R132-product-requirements.md` v2.0, `docs/R132/WORK_PLAN.md` v2.0

---

## §1 改动文件总览

| 文件 | 改动 | 估算行 |
|:-----|:------|:------:|
| `server/ws_server/scenario_matcher.py` | 新增 `match_step` + `handle_step` | **~+60 行** |
| `server/ws_server/main.py` | 注册 rule 28 + handler 包装 | **~+15 行** |
| `server/ws_server/scenario_matcher.py` | `_QUERY_LEVEL_MAP` 追加 `step: 4` | **+1 行** |
| **总量** | | **~+76 行** |

---

## §2 当前代码审计

### 2.1 规则引擎架构（R126 + R131 已就绪）

`scenario_matcher.py`（684 行）已提供完整的规则引擎基础设施：

| 组件 | 行号 | 说明 |
|:-----|:----:|:------|
| `HandlerRule` dataclass | L27-L41 | match + handle + priority + name + protocol_ref |
| `register_rule()` | L47-L50 | 追加规则并排序 |
| `dispatch()` | L60-L92 | 遍历 `_RULES` 按优先级匹配并执行 |
| `_RULES` 列表 | L45 | 排序后的规则表 |
| `_send_reply()` | L660-L673 | 发送回复到 agent inbox |

### 2.2 规则注册位置（`main.py` L4860-L4938）

所有规则在 `main.py` 模块级注册：

| 优先级 | 规则名 | match 函数 | handle 函数 | 行号 |
|:------:|:-------|:-----------|:------------|:----:|
| 10 | 回路测试 | `match_loopback` | `_sm_handle_loopback` | L4860 |
| 20 | to_agent 派活 | `match_to_agent` | `_sm_handle_to_agent` | L4867 |
| **25** | **##query** | **`match_query`** | **`_sm_handle_query`** | **L4875** |
| **30** | **##命令** | **`match_hash_cmd`** | **`_sm_handle_hash`** | **L4882** |
| 35 | PM 守卫 | `match_pm_guard` | `_sm_handle_pm_guard` | L4889 |
| 40 | ACK | `match_ack` | `_sm_handle_ack` | L4896 |
| 50 | 完成 | `match_complete` | `_sm_handle_complete` | L4903 |
| 60 | 退回 | `match_reject` | `_sm_handle_reject` | L4910 |
| 70 | 失败 | `match_fail` | `_sm_handle_fail` | L4917 |
| 80 | !命令 | `match_exclamation` | `_sm_handle_exclamation` | L4924 |
| 90 | 入库留痕 | `match_catchall` | `_sm_handle_catchall` | L4931 |

**插入点：** `##step` 规则优先级 **28**，插在 rule 25 (##query) 和 rule 30 (##hash_cmd) 之间。

### 2.3 `_QUERY_LEVEL_MAP`（`scenario_matcher.py` L177-L184）

```python
_QUERY_LEVEL_MAP = {
    "whoami": 1,
    "help": 1,
    "status": 3,
    "agents": 3,
    "agent_info": 3,
    "audit": 4,
}
```

**插入点：** L184 追加 `"step": 4,`。

### 2.4 `handle_hash_cmd` 当前 `##` 命令分发（`scenario_matcher.py` L391-L445）

当前 `match_hash_cmd` (rule 30) 拦截 **全部** `##` 前缀消息（L120: `if content.startswith("##")`）。新增的 `match_step`（rule 28）需要在 `match_hash_cmd` 之前拦截 `##step` 消息，规则 28 优先级高于 30 可自然实现。

当前 `handle_hash_cmd` 中的 `##` 命令列表：
- `##start`
- `##status`
- `##stop`
- `##advance`
- `##archive`
- `##help`

`##step` 不由 `handle_hash_cmd` 处理，由 rule 28 优先拦截。

### 2.5 旧 `!step_*` 命令（`commands/__init__.py` L144-L196）

| 旧命令 | 注册 handler | 行号 | 最低角色 |
|:-------|:-------------|:----:|:--------:|
| `!step_complete` | `_cmd_step_complete` | L149 | 1 |
| `!step_handoff` | `_cmd_step_handoff` | L162 | 3 |
| `!step_reject` | `_cmd_step_reject` | L167 | 1 |
| `!step_force` | `_cmd_step_force` | L187 | 3 |
| `!step_verify` | `_cmd_step_verify` | L192 | 2 |

这些旧 `!` 命令经 `match_exclamation` (rule 80) 返回 False 透传到旧路由体系。**本轮不删除旧命令**（向前兼容）。

### 2.6 `_ensure_pipeline_manager()` 访问模式（`main.py` L69-L73）

```python
def _ensure_pipeline_manager() -> PipelineContextManager:
    if state._pipeline_manager is None:
        state._pipeline_manager = PipelineContextManager(data_dir=config.DATA_DIR)
    return state._pipeline_manager
```

`handle_step` 需要通过 `from . import main as _main; mgr = _main._ensure_pipeline_manager()` 获取管理器（与 `handle_query` L280 模式一致）。

---

## §3 改造方案

### 3.1 `_QUERY_LEVEL_MAP` 追加（`scenario_matcher.py` L184）

```python
_QUERY_LEVEL_MAP = {
    "whoami": 1,
    "help": 1,
    "status": 3,
    "agents": 3,
    "agent_info": 3,
    "audit": 4,
    # R132
    "step": 4,               # ← 新增
}
```

### 3.2 新增 `match_step()`（`scenario_matcher.py`，rule 28，L184–L192 区域）

在 `match_query` 函数之前，或 `_QUERY_LEVEL_MAP` 之后插入：

```python
# ── R132: ##step match ───────────────────────────────────────────────
def match_step(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 28: ##step commands. Priority 28 — between query (25) and hash_cmd (30)."""
    if content.startswith("##step"):
        return content
    return False
```

**位置选择：** 插入 `_QUERY_LEVEL_MAP` 之后、`get_agent_level()` 之前（L185附近），保持 match 函数集中在前部。

### 3.3 新增 `handle_step()`（`scenario_matcher.py`，~L197 区域）

在 `handle_query` 函数之前插入：

```python
# ── R132: ##step handler ─────────────────────────────────────────────
_STEP_ACTIONS = ("complete", "reject", "restart", "force", "pause", "resume")

async def handle_step(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Handle ##step commands: ##step##<action>##<args>
    Priority 28 — between query (25) and hash_cmd (30).
    """
    content = matched
    parts = content.split("##")
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "📋 **##step 命令**\n\n"
            "`##step##complete##<id>` — 步骤完成 (L4)\n"
            "`##step##reject##<id>##<原因>` — 步骤打回 (L4)\n"
            "`##step##restart##<id>` — 步骤回退重启 (L4)\n"
            "`##step##force##<id>` — 强制推进 (L4)\n"
            "`##step##pause##<id>` — 暂停步骤 (L4)\n"
            "`##step##resume##<id>` — 恢复步骤 (L4)"
        )
        return True

    action = parts[2].lower()
    args = parts[3] if len(parts) > 3 else ""

    # ── Permission check ──
    level = _get_agent_level(agent_id)
    min_level = _QUERY_LEVEL_MAP.get("step", 4)
    if level < min_level:
        await _send_reply(ws, agent_id,
            f"❌ 权限不足: 需要 L{min_level} 级别，你当前 L{level}"
        )
        return True

    # ── Route actions ──
    from . import main as _main

    if action == "complete":
        # Map to _cmd_step_complete logic
        params = {"step_name": args}
        result = await _main._cmd_step_complete(agent_id, params)
        await _send_reply(ws, agent_id, result)

    elif action == "reject":
        # ##step##reject##R131##bug太多
        step_parts = args.split("##", 1)
        step_id = step_parts[0]
        reason = step_parts[1] if len(step_parts) > 1 else ""
        params = {"step_name": step_id, "reason": reason}
        result = await _main._cmd_step_reject(agent_id, params)
        await _send_reply(ws, agent_id, result)

    elif action == "restart":
        # Map to step_back logic
        result = await _main._cmd_step_restart(agent_id, args)
        await _send_reply(ws, agent_id, result)

    elif action == "force":
        params = {"step_name": args}
        result = await _main._cmd_step_force(agent_id, params)
        await _send_reply(ws, agent_id, result)

    elif action == "pause":
        result = await _main._cmd_step_pause(agent_id, args)
        await _send_reply(ws, agent_id, result)

    elif action == "resume":
        result = await _main._cmd_step_resume(agent_id, args)
        await _send_reply(ws, agent_id, result)

    else:
        await _send_reply(ws, agent_id,
            f"❌ 未知步骤操作: {action}，可用: {' / '.join(_STEP_ACTIONS)}"
        )

    return True
```

### 3.4 main.py 注册 rule 28（`main.py` L4874-L4881 区域，在 rule 25 之后、rule 30 之前）

```python
# ── R131: ##query commands (rule 25) ──
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_query,
    handle=_sm_handle_query,
    priority=25,
    name="##query命令",
    protocol_ref="§R131",
))
# ── R132: ##step commands (rule 28) ──
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_step,
    handle=_sm_handle_step,
    priority=28,
    name="##step命令",
    protocol_ref="§R132",
))
```

### 3.5 main.py handler 包装（L4709 区域，在 `_sm_handle_hash` 之后）

```python
async def _sm_handle_step(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 28: ##step commands → scenario_matcher.handle_step."""
    return await _sm.handle_step(ws, agent_id, msg, matched)
```

**注意：** `handle_step` 直接调用 `main._cmd_step_*` 函数。这些函数本身校验权限（`_can_execute`），但 `handle_step` 的权限检查已在函数内通过 `_get_agent_level` + `_QUERY_LEVEL_MAP` 完成。双层检查是安全的——函数内权限宽了也不影响，窄了则补一层保护。

### 3.6 旧 `_cmd_step_*` 函数签名确认

`commands/pipeline.py` 中 `_cmd_step_complete`、`_cmd_step_reject`、`_cmd_step_force` 均接受 `(sender_id, params)` 签名。`restart` / `pause` / `resume` 需确认是否存在或需新增：

| action | 对应函数 | 状态 |
|:-------|:---------|:-----|
| `complete` | `_cmd_step_complete(sender_id, params)` | ✅ 已存在 L596 |
| `reject` | `_cmd_step_reject(sender_id, params)` | ✅ 已存在 L1349 |
| `force` | `_cmd_step_force(sender_id, params)` | ✅ 已存在 L1054 |
| `restart` | 无直接等价，可调用 `_cmd_step_handoff` 或新建 | ❌ 待 Dev 确认 |
| `pause` | 不存在 | ❌ 需新增 |
| `resume` | 不存在 | ❌ 需新增 |

**对 `restart` / `pause` / `resume`：** 若对应 `_cmd_step_*` 函数不存在，`handle_step` 中直接返回占位回复（暂不实现后端逻辑），注明「R132 仅注册命令路由，具体实现待后续轮次」。

---

## §4 插入点汇总

| 位置 | 文件 | 行号 | 改动 |
|:-----|:-----|:----:|:-----|
| `_QUERY_LEVEL_MAP` | `scenario_matcher.py` | **L184** | 追加 `"step": 4` |
| `match_step` 定义 | `scenario_matcher.py` | **L185–L192** | 新增 match 函数 |
| `handle_step` 定义 | `scenario_matcher.py` | **L195–L260** | 新增 handler 函数 |
| `_sm_handle_step` 定义 | `main.py` | **L4712–L4717** | 新增 handler 包装 |
| rule 28 注册 | `main.py` | **L4882–L4890** | 注册规则 |

---

## §5 执行顺序

| 顺序 | 改动 | 说明 |
|:----:|:-----|:------|
| 1 | `scenario_matcher.py` L184: 追加 `"step": 4` | 权限配置先行 |
| 2 | `scenario_matcher.py` L185+: 新增 `match_step` | match 函数 |
| 3 | `scenario_matcher.py` L195+: 新增 `handle_step` | handler 函数（含 6 action 路由） |
| 4 | `main.py` L4712+: 新增 `_sm_handle_step` | handler 包装 |
| 5 | `main.py` L4882+: 注册 rule 28 | 注册到规则引擎 |
| 6 | 验证：`##step##complete##R131` | 测试完整链路 |

---

## §6 安全边界

| # | 边界 | 说明 | 风险 |
|:-:|:-----|:------|:----:|
| 1 | **rule 28 vs rule 30 优先级** | `##step` 在 `##` 通用匹配之前拦截，不误拦截非 step 的 `##` 命令 | 🟢 |
| 2 | **L4 权限** | `step` 设为 `_QUERY_LEVEL_MAP` 中最高级别 4，仅 PM/高级 bot 可操作 | 🟢 |
| 3 | **双层权限校验** | `handle_step` 内部用 `_get_agent_level` 检查，旧 `_cmd_step_*` 也有 `_can_execute` 检查 | 🟢 |
| 4 | **向前兼容** | `!step_*` 旧命令完好保留，不受影响 | 🟢 |
| 5 | **未知 action** | `else` 分支返回 `❌ 未知步骤操作`，不静默忽略 | 🟢 |

---

## §7 grep 验证清单

```bash
# 7.1 match_step 存在
grep -c "def match_step" scenario_matcher.py          # → 1

# 7.2 handle_step 存在
grep -c "def handle_step" scenario_matcher.py         # → 1

# 7.3 _QUERY_LEVEL_MAP 包含 step
grep '"step"' scenario_matcher.py                      # → "step": 4

# 7.4 rule 28 已注册
grep "priority=28" main.py                             # → 1

# 7.5 _sm_handle_step 存在
grep -c "_sm_handle_step" main.py                     # → 2（定义 + 注册）

# 7.6 旧 !step 命令不受影响（无删除）
grep -c "step_complete" commands/__init__.py          # → ≥1（保留）
```

---

## §8 验收标准映射

| # | 验收项 | 代码位置 | 验证方式 |
|:-:|:-------|:---------|:---------|
| 1 | `##step##complete##R131` 回复完成 | `handle_step` → `_cmd_step_complete` | 功能测试 |
| 2 | `##step##reject##R131##原因` 回复打回 | `handle_step` → `_cmd_step_reject` | 功能测试 |
| 3 | `##step##force##R132` 回复强制推进 | `handle_step` → `_cmd_step_force` | 功能测试 |
| 4 | `##step##unknown##R132` 回未知 action | `handle_step` else 分支 | 功能测试 |
| 5 | L1 用户 `##step##complete##R131` 拒绝 | `if level < min_level` | 权限测试 |
| 6 | `!step_complete R131` 旧命令仍工作 | `commands/` 不变 | 兼容测试 |
| 7 | `##query##whoami` 仍工作（rule 25 优先） | rule 25 < 28 | 回归测试 |
| 8 | `##start##R132` 仍走 rule 30（不匹配 rule 28） | `startswith("##step")` 不匹配 | 回归测试 |

---

> **审核记录：**
> - v1.0 提交审核
