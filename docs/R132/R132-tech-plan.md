# R132 技术方案 — ##step 规则迁移（! 命令统一化收官）

| 字段 | 内容 |
|:-----|:------|
| **版本** | v1.0 |
| **作者** | Hermes Agent |
| **轮次** | R132 |
| **状态** | 已审签 |

---

## 1. 问题与目标

### 1.1 现状

当前管线步骤操作（complete / reject / restart / force / pause / resume）走旧 `!` 命令体系，由 `commands/` 目录处理。`##` 命令体系（`scenario_matcher.py`）仅支持管线生命周期命令（start / status / stop / advance / archive）。两套命令体系并存，维护成本高。

R131 规划了 ##query 查询规则（whoami / status / agents / audit 等），但仅完成到技术方案（commit `870f4ae`），未编码。R132 聚焦 `##step` 一个规则组，不做 ##query。

### 1.2 本轮目标

在 `scenario_matcher` 规则表中新增 `##step` 规则组（优先级 32），实现 6 个步骤操作的 ## 化。旧 `!step_*` 命令保持兼容，不删除。

### 1.3 变更范围

| 文件 | 操作 | 说明 |
|:-----|:----:|:------|
| `server/ws_server/scenario_matcher.py` | ✅ 修改 | 新增 `match_step()` + `handle_step()` + 权限检查 |
| `server/ws_server/main.py` | ✅ 修改 | 注册 `##step` 规则（HandlerRule, priority=32） |
| `server/commands/` | ❌ 不变 | 旧 `!step_*` 兼容，本轮不动 |

---

## 2. 代码审计 — 实际行号

### 2.1 `scenario_matcher.py`（260 行）

#### 2.1.1 规则注册模式

当前使用 `HandlerRule` dataclass（L27-41），`register_rule()`（L47-50）按优先级升序排序。

#### 2.1.2 匹配函数一览

| # | 函数 | 行 | 优先级 | 规则名 |
|:-:|:-----|:--:|:------:|:-------|
| 1 | `match_loopback` | L96-100 | 10 | 回路测试 |
| 2 | `match_to_agent` | L102-116 | 20 | to_agent 派活 |
| 3 | **`match_hash_cmd`** | **L118-122** | **30** | **##命令路由** |
| 4 | `match_pm_guard` | L124-129 | 35 | PM 安全守卫 |
| 5 | `match_ack` | L131-135 | 40 | ACK 转发 |
| 6 | `match_complete` | L137-141 | 50 | 完成确认 |
| 7 | `match_reject` | L143-147 | 60 | 退回回退 |
| 8 | `match_fail` | L149-153 | 70 | 失败告警 |
| 9 | `match_exclamation` | L155-159 | 80 | !命令透传 |
| 10 | `match_catchall` | L161-163 | 90 | 入库留痕 |

#### 2.1.3 关键行号

| 锚点 | 行号 | 说明 |
|:-----|:----:|:------|
| `match_hash_cmd` 函数体 | L118-122 | 需要添加 `and not startswith("##step")` 排除 |
| `match_exclamation` 结束 | L159 | **插入 `match_step`（L160）** |
| `match_catchall` | L161-163 | 之后 |
| `handle_hash_cmd` | L167-221 | **插入 `handle_step`（L165，在此函数之前）** |
| `_send_reply` 工具函数 | L247-260 | 可复用 |
| 空行 | L164-166 | 可用空间 |

### 2.2 `main.py`（4925 行）

#### 2.2.1 handle 包装函数

| 函数 | 行号 |
|:-----|:----:|
| `_sm_handle_hash` | L4709-4711 |
| `_sm_handle_pm_guard` | L4714-4721 |

#### 2.2.2 规则注册

| 注册块 | 行号 |
|:-------|:----:|
| `##命令路由` (priority 30) | L4869-4875 |
| `PM安全守卫` (priority 35) | L4876-4882 |

**→ `##step` 注册插入 L4875 与 L4876 之间。** `_sm_handle_step` 插入 L4711 之后（L4712-4713）。

---

## 3. 命令冲突分析

### 3.1 ##step 被 ## 规则拦截的问题

`##step##complete##R131` 的格式 `##step##` → `content.startswith("##")` 为 `True`。

**当前路径：** `match_hash_cmd` (priority 30) 拦截 → `handle_hash_cmd` 解析 `cmd="step"` → 走到 `elif cmd == "help":` 的 `else` 分支 → 回复 `❌ 未知 ## 命令: step`

**解决方案：** 在 `match_hash_cmd` 中排除 `##step` 前缀，使其 fall through 给 `match_step`（priority 32）。

```python
# L118-122 修改前
def match_hash_cmd(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 30: ## commands."""
    if content.startswith("##"):
        return content
    return False

# L118-122 修改后
def match_hash_cmd(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 30: ## commands (##step handled by rule 32)."""
    if content.startswith("##") and not content.startswith("##step"):
        return content
    return False
```

单行改动，零副作用。**所有 `##step**` 前缀的消息都会 fall through 到 priority 32。**

### 3.2 边缘输入分析

| 输入 | `match_hash_cmd` 判断 | `match_step` 判断 | 最终 |
|:-----|:---------------------|:------------------|:-----|
| `##step##complete##R131` | `##`✅ 但 `##step`✅ → `False` | `##step`✅ → `content` | ✅ `handle_step` |
| `##stepwise##xxx` | `##`✅ 但 `##step`✅ → `False` | `##step`✅ → `content` | ✅→未知 action 拒绝 |
| `##start##R132` | `##`✅, `##step`❌ → `content` | 不匹配 | ✅ `handle_hash_cmd` |
| `##steps` | `##`✅, `##step`❌ → `content` | 不匹配 (`startswith` not `steps`) | ✅ `handle_hash_cmd`→未知命令 |

结论：`startswith("##step")` 前缀匹配安全。边缘输入（如 `##stepwise`）被 `handle_step` 的未知操作分支拒绝，不会影响现有功能。

---

## 4. 详细设计

### 4.1 新增 `match_step`（scenario_matcher.py，插入 L160）

```python
def match_step(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 32: ##step commands."""
    if content.startswith("##step"):
        return content
    return False
```

### 4.2 新增 `handle_step`（scenario_matcher.py，插入 L165，在 `handle_hash_cmd` 之前）

```python
_STEP_ACTIONS = {"complete", "reject", "restart", "force", "pause", "resume"}

async def handle_step(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Rule 32: Handle ##step##<action>##<args> commands.
    
    Routes to pipeline engine for step state manipulation.
    All actions require L4 permission.
    
    Args:
        ws: WebSocket connection
        agent_id: authenticated agent ID
        msg: original message dict
        matched: content string (from match_step)
    
    Returns:
        True — handled, reply sent to agent's inbox
    """
    content = matched
    parts = content.split("##")
    
    # parts: ["", "step", "action", "args..."]
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "❌ 格式: `##step##<action>##<id>##<原因>`\n"
            "可用操作: complete / reject / restart / force / pause / resume"
        )
        return True
    
    action = parts[2].lower()
    args = parts[3].strip() if len(parts) > 3 else ""
    reason = parts[4].strip() if len(parts) > 4 else ""
    
    # ── Unknown action ──
    if action not in _STEP_ACTIONS:
        await _send_reply(ws, agent_id,
            f"❌ 未知步骤操作: {action}，可用: complete / reject / restart / force / pause / resume"
        )
        return True
    
    # ── Permission check: L4 required for all step operations ──
    from server.common import auth
    level = auth.get_level(agent_id)
    if level < 4:
        await _send_reply(ws, agent_id,
            f"❌ 权限不足：当前等级 L{level}，需要 L4 级别才能操作步骤"
        )
        return True
    
    # ── Parse round_name from args ──
    # args can be "R131", "R132", etc.
    round_name = args.upper()
    if not round_name.startswith("R"):
        await _send_reply(ws, agent_id,
            f"❌ 无效参数: `{args}`，应为 R{N}（如 `##step##complete##R131`）"
        )
        return True
    
    # ── Route to pipeline engine ──
    from . import main as _main
    engine = _main._ensure_engine()
    ctx = engine._ctx_mgr.get(round_name)
    
    if not ctx:
        await _send_reply(ws, agent_id,
            f"❌ 未找到管线 `{round_name}`"
        )
        return True
    
    # Find the current or last active step
    # Try to find step by step_key matching round_name in step name
    step_idx = ctx.current_step - 1
    if step_idx < 0 or step_idx >= len(ctx.steps):
        step_idx = 0
    
    step_key = f"step{step_idx + 1}"
    step_info = ctx.steps[step_idx] if step_idx < len(ctx.steps) else {}
    
    # ── Action dispatch ──
    if action == "complete":
        if step_info:
            step_info["status"] = "done"
        ctx.current_step = min(ctx.current_step + 1, ctx.total_steps)
        try:
            engine._ctx_mgr.save()
        except Exception:
            pass
        await _send_reply(ws, agent_id, f"步骤 #{args} 已完成 ✅")
    
    elif action == "reject":
        if step_info:
            step_info["status"] = "rejected"
        if ctx.current_step > 1:
            ctx.current_step -= 1
        try:
            engine._ctx_mgr.save()
        except Exception:
            pass
        reply = f"步骤 #{args} 已打回"
        if reason:
            reply += f"：{reason}"
        await _send_reply(ws, agent_id, reply + " 🔄")
    
    elif action == "restart":
        if step_info:
            step_info["status"] = "in_progress"
        try:
            engine._ctx_mgr.save()
        except Exception:
            pass
        await _send_reply(ws, agent_id, f"步骤 #{args} 已重启 ▶️")
    
    elif action == "force":
        # Mark current step done and advance
        if step_info:
            step_info["status"] = "done"
        ctx.current_step = min(ctx.current_step + 1, ctx.total_steps)
        try:
            engine._ctx_mgr.save()
        except Exception:
            pass
        await _send_reply(ws, agent_id, f"步骤 #{args} 已强制推进 ⏩")
    
    elif action == "pause":
        if step_info:
            step_info["status"] = "paused"
        try:
            engine._ctx_mgr.save()
        except Exception:
            pass
        await _send_reply(ws, agent_id, f"步骤 #{args} 已暂停 ⏸️")
    
    elif action == "resume":
        if step_info:
            step_info["status"] = "in_progress"
        try:
            engine._ctx_mgr.save()
        except Exception:
            pass
        await _send_reply(ws, agent_id, f"步骤 #{args} 已恢复 ▶️")
    
    logger.info("[R132] ##step: %s → %s (round=%s) by %s",
                action, args, round_name, agent_id[:12])
    return True
```

### 4.3 修改 `match_hash_cmd` 排除 `##step`

scenario_matcher.py L118-122，追加 `and not content.startswith("##step")`：

```python
def match_hash_cmd(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 30: ## commands (##step handled by rule 32)."""
    if content.startswith("##") and not content.startswith("##step"):
        return content
    return False
```

### 4.4 注册规则（main.py）

**在 L4711 后插入 handle 包装函数：**

```python
async def _sm_handle_step(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 32: ##step commands → scenario_matcher.handle_step."""
    return await _sm.handle_step(ws, agent_id, msg, matched)
```

**在 L4875 与 L4876 之间插入规则注册：**

```python
# R132 — ##step 步骤操作（优先级 32）
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_step,
    handle=_sm_handle_step,
    priority=32,
    name="##step步骤操作",
    protocol_ref="§R132",
))
```

---

## 5. 数据流图

```
Bot → _inbox:server
  → __main__.py dispatch(ws, agent_id, data)
    → scenario_matcher.dispatch()
      → rule priority order traversal

      [priority 10] match_loopback     → test ✅ → false
      [priority 20] match_to_agent     → no to_agent → false
      [priority 30] match_hash_cmd     → ##step##complete##R131
                                          startswith("##")?   ✅
                                          startswith("##step")? ✅
                                          → False (excluded)
      [priority 32] match_step  ← NEW  → ##step##complete##R131
                                          startswith("##step")? ✅
                                          → handle_step(ws, agent_id, msg, content)
                                            ├─ get_level(agent_id) → < 4?
                                            │   → ✅ L4 → continue
                                            │   → ❌ 回复"权限不足"
                                            ├─ action="complete", args="R131"
                                            ├─ engine._ctx_mgr.get("R131")
                                            │   → ctx found? → ✅
                                            │   → ❌ 回复"未找到管线"
                                            ├─ step_info["status"]="done"
                                            ├─ engine._ctx_mgr.save()
                                            └→ 回复"步骤 #R131 已完成 ✅"

      [priority 35] match_pm_guard     → skipped (rule 32 handled)
      [priority 80] match_exclamation  → "!step_complete R131" untouched
```

---

## 6. 侧效应分析

### 6.1 命令路由影响表

| 输入 | 修改前 | 修改后 | 影响 |
|:-----|:-------|:-------|:----:|
| `##step##complete##R131` | ❌ `handle_hash_cmd` 报"未知 ## 命令: step" | ✅ `handle_step` 正确处理 | ✅ 修复 |
| `##step##reject##R131##原因` | ❌ 同上 | ✅ `handle_step` 处理打回 | ✅ 修复 |
| `##step##unknown##R132` | ❌ 同上 | ✅ `handle_step` 报"未知步骤操作" | ✅ 明确 |
| `##start##R132##k=v` | ✅ `handle_hash_cmd` | ✅ 不变（不含 `##step` 前缀） | ✅ 无影响 |
| `##status##R132` | ✅ `handle_hash_cmd` | ✅ 不变 | ✅ 无影响 |
| `##help` | ✅ `handle_hash_cmd` | ✅ 不变 | ✅ 无影响 |
| `!step_complete R131` | ✅ `match_exclamation` → 透传 | ✅ 不变 | ✅ 无影响 |
| `!whoami` | ✅ `match_exclamation` → 透传 | ✅ 不变 | ✅ 无影响 |
| `!set_card xxx` | ✅ `match_exclamation` → 透传 | ✅ 不变 | ✅ 无影响 |

### 6.2 兼容性保证

- 旧 `!step_*` 命令走 `match_exclamation` → 透传 → `commands/`，不受影响
- `to_agent` 消息路由不受影响
- 数据库 schema 不变
- Web UI 不变

---

## 7. 修改位置汇总

### 7.1 `scenario_matcher.py`

| # | 位置(L) | 操作 | 内容 |
|:-:|:--------|:----:|:------|
| 1 | L118-122 | 🔧 修改 | `match_hash_cmd` 追加 `and not startswith("##step")` |
| 2 | L160 | ✅ 新增 | `match_step()` 函数（11 行） |
| 3 | L165 | ✅ 新增 | `handle_step()` 函数（~90 行）+ `_STEP_ACTIONS` 集合 |
| 4 | 模块级 imports | ✅ 验证 | `time`, `re` 已导入（L13-14），无需额外 import |

### 7.2 `main.py`

| # | 位置(L) | 操作 | 内容 |
|:-:|:--------|:----:|:------|
| 1 | L4712-4713 | ✅ 新增 | `_sm_handle_step()` 包装函数（3 行） |
| 2 | L4875-4876 | ✅ 新增 | `##step` 规则注册（7 行） |

### 7.3 净变更统计

| 文件 | 新增 | 修改 | 删除 | 净增 |
|:-----|:----:|:----:|:----:|:----:|
| scenario_matcher.py | ~101 行 | 1 行 | 0 | +101 |
| main.py | ~10 行 | 0 | 0 | +10 |
| **合计** | **111 行** | **1 行** | **0** | **+111** |

---

## 8. 验证验收标准

### 8.1 功能验收（通过客户端发消息验证）

| # | 发送 | 期望回复 |
|:-:|:-----|:---------|
| 1 | `##step##complete##R131` | 步骤 #R131 已完成 ✅ |
| 2 | `##step##reject##R131##测试未通过` | 步骤 #R131 已打回：测试未通过 🔄 |
| 3 | `##step##restart##R131` | 步骤 #R131 已重启 ▶️ |
| 4 | `##step##force##R132` | 步骤 #R132 已强制推进 ⏩ |
| 5 | `##step##pause##R132` | 步骤 #R132 已暂停 ⏸️ |
| 6 | `##step##resume##R132` | 步骤 #R132 已恢复 ▶️ |
| 7 | `##step`（无参数） | ❌ 格式错误帮助文本 |
| 8 | `##step##unknown##R132` | ❌ 未知步骤操作: unknown |
| 9 | `##step##complete##xxx` | ❌ 未找到管线 XXX |

### 8.2 权限验收

| # | 用户级别 | 命令 | 期望 |
|:-:|:--------:|:-----|:-----|
| 10 | L1 | `##step##complete##R131` | ❌ 权限不足：需要 L4 |
| 11 | L3 | `##step##pause##R132` | ❌ 权限不足：需要 L4 |
| 12 | L4 | `##step##force##R132` | ✅ 正常执行 |

### 8.3 回归验收

| # | 检查项 | 方法 |
|:-:|:-------|:-----|
| 13 | `##start##R132##k=v` 正常 | 发 `##start` → 检查创建 |
| 14 | `##status##R132` 正常 | 发 `##status##R132` → 查状态 |
| 15 | `!step_complete R131` 旧命令 | 发 `!` → 走 commands/ |
| 16 | `!whoami` 旧命令 | 发 `!whoami` → 正常 |
| 17 | `to_agent` 路由 | 发带 to_agent 消息 → 目标收到 |

---

## 9. 不做事项

| 事项 | 说明 |
|:-----|:------|
| `##query` 规则实现 | R131 规划但未编码，不纳入 R132 scope |
| `_QUERY_LEVEL_MAP` 结构 | R131 设计概念，R132 使用 `auth.get_level()` 替代 |
| 旧 `!` 命令删除 | 保持兼容，R132 不涉及 |
| 数据库 schema 变更 | 不新增表/字段 |
| Web UI 变更 | 纯后端改动 |
| pipeline_engine 核心变更 | 仅通过 `_ctx_mgr` 访问 ctx，直接操作 step 状态 |
| `command_utils.py` 修改 | 旧 `!` 命令体系不动 |

---

## 10. 实现顺序

1. `scenario_matcher.py` — 修改 `match_hash_cmd`（L118，排除 `##step`）
2. `scenario_matcher.py` — 新增 `match_step()`（L160）
3. `scenario_matcher.py` — 新增 `handle_step()` + `_STEP_ACTIONS`（L165）
4. `main.py` — 新增 `_sm_handle_step()`（L4712）
5. `main.py` — 注册 `##step` 规则（L4875-4876）
6. 验证 `python3 -c "from server.ws_server import scenario_matcher"` 无 ImportError
7. 启动服务端，逐一验证 12 条功能/权限用例 + 5 条回归用例

---

*技术方案结束*
