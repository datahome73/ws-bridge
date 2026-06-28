# R50 技术方案 — 管线激活 + Step 交接过渡命令

- **轮次：** R50
- **类型：** 功能增强 — 管线激活命令 + Step 交接显式过渡 + 自动频道切换
- **日期：** 2026-06-28
- **文档作者：** 架构师（arch）
- **改动范围：** 仅 `server/handler.py`

---

## 1. 概述

### 1.1 当前问题

| 问题 | 描述 |
|:-----|:------|
| 管线启动即激活 | `_cmd_pipeline_start` 在创建工作室后立即设置 `active=True`，无独立激活步骤。工作室准备阶段（成员迁入、角色确认）与管线执行阶段混在一起 |
| Step 完成即自动交接 | `_cmd_step_complete` 在标记 Task 完成后立即点名下一角色并创建 Task，执行者无法确认上一环节产出是否达标再交接 |
| 频道切换靠手动 | Step 交接后下一负责人需手动切到工作室频道才能看到任务上下文，无自动 `MSG_SET_ACTIVE_CHANNEL` 推送 |
| 交接通知缺主动动作 | 交接完成缺少显式「确认接收」的信号，新 Step 负责人可能未感知自己被点名 |

### 1.2 设计目标

1. **管线启动与激活分离** — 新增 `!pipeline_activate` 命令，在管线启动后由 PM/Admin 显式激活
2. **Step 交接显式化** — 新增 `!step_handoff` 命令，替代 `step_complete` 中隐式交接逻辑，支持产出确认后再交接
3. **自动 MSG_SET_ACTIVE_CHANNEL** — Step 交接时自动向工作室所有成员推送频道切换信号
4. **向后兼容** — `!pipeline_start` + `!step_complete` 原流程保持不变，新增命令作为增强选项
5. **仅有 handler.py 修改** — 不改 persistence、protocol、config、ws_mod 等模块

---

## 2. 方向 B：过渡命令（优先实施）

### 2.1 `!pipeline_activate` 命令

#### 2.1.1 接口定义

```
!pipeline_activate <R{N}> [--ws <workspace_id>]
```

| 参数 | 必填 | 说明 |
|:-----|:----:|:-----|
| `R{N}` | ✅ | 轮次名称，如 `R50` |
| `--ws` | ❌ | 工作室 ID，默认使用该轮次 `_PIPELINE_STATE` 中记录的 `ws_id` |

#### 2.1.2 处理逻辑

```python
async def _cmd_pipeline_activate(sender_id: str, params: dict) -> str:
    round_name = positional[0].upper()
    ws_id = params.get("ws", "") or _PIPELINE_STATE.get(round_name, {}).get("ws_id", "")
    
    # 1. 校验管线已启动但未激活
    if not pipeline_exists(round_name):
        return f"❌ {round_name} 管线不存在，请先执行 !pipeline_start {round_name}"
    if pipeline_is_active(round_name):
        return f"❌ {round_name} 管线已激活，无需重复激活"
    
    # 2. 校验工作室存在
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return f"❌ 工作室 {ws_id} 不存在"
    
    # 3. 向全体成员推送 MSG_SET_ACTIVE_CHANNEL
    switch_count = await _broadcast_active_channel(ws_id)
    
    # 4. 设置管线为活跃
    _set_pipeline_state(round_name, {
        "active": True,
        "current_step": "step1",
        "ws_id": ws_id,
        "activated_at": time.time(),
    })
    
    return (
        f"🚀 **{round_name} 管线已激活**\n"
        f"  工作室: {ws_id}\n"
        f"  MSG_SET_ACTIVE_CHANNEL 已发送至 {switch_count} 个在线成员\n"
        f"  请各成员确认频道已切换到工作室"
    )
```

#### 2.1.3 状态分离

引入新的管线状态区分：

| 状态 | 常量 | 说明 |
|:-----|:-----|:------|
| 不存在 | — | 管线未创建 |
| 已创建 | `active=False` | `!pipeline_start` 已执行，工作室已创建，但未激活 |
| 已激活 | `active=True` | `!pipeline_activate` 已执行，管线正式运行 |
| 已完成 | 已移除 | 所有 Step 完成，管线关闭 |

#### 2.1.4 命令注册

```python
"pipeline_activate": {
    "handler": _cmd_pipeline_activate, "min_role": 3, "workspace_scope": False,
    "usage": "!pipeline_activate <R{N}> [--ws <workspace_id>]",
},
```

### 2.2 `!step_handoff` 命令

#### 2.2.1 接口定义

```
!step_handoff <step_name> --output <commit/file> [--next <next_step>]
```

| 参数 | 必填 | 说明 |
|:-----|:----:|:-----|
| `step_name` | ✅ | 当前完成的 Step 名称，如 `step2` |
| `--output` | ✅ | 产出引用（commit SHA 或文件路径） |
| `--next` | ❌ | 指定下一步骤名称，默认按 step 排序自动推断 |

#### 2.2.2 处理逻辑

```python
async def _cmd_step_handoff(sender_id: str, params: dict) -> str:
    step_name = positional[0]
    output_ref = params.get("output", "")
    
    # 1. 验证当前工作区 + 管线活跃
    ws_obj, round_name = _resolve_workspace_and_pipeline(sender_ch)
    
    # 2. 标记当前 Task completed (同 step_complete 逻辑)
    task_result = await _cmd_task_update(sender_id, {...})
    
    # 3. 推断下一 Step
    next_step = ...  # 同 step_complete 推断逻辑
    
    # 4. 点名下一角色
    rollcall_result = await _cmd_rollcall_next(...)
    
    # 5. 创建下一 Step Task
    next_task_result = await _cmd_task_create(...)
    
    # 6. ★ 新增: 广播 MSG_SET_ACTIVE_CHANNEL 到全体成员
    switch_count = await _broadcast_active_channel(ws_id)
    
    # 7. 更新管线状态
    _update_pipeline_step(round_name, next_step)
    
    # 8. 通知 PM
    ...
    
    return (
        f"✅ **{step_name} 完成 → 交接给 {next_role} {next_step}**\n"
        f"  产出: {output_ref}\n"
        f"  MSG_SET_ACTIVE_CHANNEL 已发送至 {switch_count} 个在线成员\n"
        f"  📋 已点名 {next_role_display}，等待确认「到」\n"
        f"  {rollcall_result}\n"
        f"  {next_task_result}"
    )
```

#### 2.2.3 与 `!step_complete` 的关系

| 方面 | `!step_complete`（原有） | `!step_handoff`（新增） |
|:-----|:------------------------|:------------------------|
| 功能 | 标记完成 + 自动交接 + 点名 | 标记完成 + 自动交接 + 点名 + **MSG_SET_ACTIVE_CHANNEL** |
| 频道切换 | ❌ 无 | ✅ 自动广播 |
| 管线完整性 | ✅ 最后一步自动关闭管线 | ✅ 最后一步自动关闭管线 |
| 兼容性 | 保持原样 | 作为增强替代方案 |

> **注意：** `!step_handoff` 是 `!step_complete` 的超集——在 `!step_complete` 逻辑基础上增加了 MSG_SET_ACTIVE_CHANNEL 广播。用户可以按需选择使用哪一个。

#### 2.2.4 命令注册

```python
"step_handoff": {
    "handler": _cmd_step_handoff, "min_role": 3, "workspace_scope": True,
    "usage": "!step_handoff <step_name> --output <commit/file>",
},
```

---

## 3. 方向 A：自动 MSG_SET_ACTIVE_CHANNEL（方向 B 后实施）

### 3.1 核心函数 `_broadcast_active_channel`

从 R37 B-1 的 rollcall 上下文（L2036-2071）提取公共函数，供 `!pipeline_activate`、`!step_handoff`、以及最终自动钩子复用：

```python
async def _broadcast_active_channel(ws_id: str) -> int:
    """向工作室所有成员广播 MSG_SET_ACTIVE_CHANNEL。
    返回成功接收的在线成员数。
    """
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return 0
    
    switch_payload = json.dumps({
        "type": p.MSG_SET_ACTIVE_CHANNEL,
        p.FIELD_CHANNEL: ws_id,
        "from_name": "系统",
        "from": "系统",
        "content": f"请确认活跃频道已切换至 {ws_id}，回复「已切」确认。",
        "ts": time.time(),
    })
    
    online_count = 0
    for member_id in ws_obj.members:
        persistence.set_agent_channel(member_id, ws_id)
        for conn in list(_connections.get(member_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(switch_payload)
                elif hasattr(conn, "send"):
                    await conn.send(switch_payload)
                online_count += 1
            except Exception:
                pass
    
    persistence.save_agent_channels(config.DATA_DIR)
    logger.info(
        "MSG_SET_ACTIVE_CHANNEL '%s' sent to %d online members",
        ws_id, online_count,
    )
    return online_count
```

### 3.2 提取重构

| 改动点 | 当前代码 | 重构后 |
|:-------|:---------|:--------|
| R37 B-1 内联 MSG_SET_ACTIVE_CHANNEL | L2036-2071 内联逻辑 | 调用 `_broadcast_active_channel(ws_id)` |
| `!pipeline_activate` | — | 新增，调用 `_broadcast_active_channel` |
| `!step_handoff` | — | 新增，调用 `_broadcast_active_channel` |
| `_cmd_step_complete` (R50后) | 无频道切换 | 可选择性接入 `_broadcast_active_channel` |
| `_cmd_pipeline_start` (R50后) | 无频道切换 | 可选择性在工作区创建后调用 |

### 3.3 自动触发时机（终极形态）

方向 A 完成后，以下时机自动触发 MSG_SET_ACTIVE_CHANNEL：

1. **管线激活** — `!pipeline_activate` → 全工作室广播
2. **Step 交接** — `!step_handoff` → 全工作室广播
3. **`!step_complete` 增强**（可选）— 根据配置决定是否自动广播
4. **`!pipeline_start` 增强**（可选）— 根据配置决定是否自动广播

---

## 4. 文件变更

| 文件 | 操作 | 说明 |
|:-----|:-----|:-----|
| `server/handler.py` | 🟡 修改 | 新增 `_cmd_pipeline_activate`、`_cmd_step_handoff` 命令处理函数；提取 `_broadcast_active_channel` 公共函数；重构 R37 B-1 内联逻辑调用公共函数；注册新命令到 `_ADMIN_COMMANDS` |

**本次改动仅限 `server/handler.py`，其它模块不变。**

---

## 5. 实施计划

### Phase 1：提取公共函数（30min）

1. 从 L2036-2071（R37 B-1 rollcall 上下文）提取 `_broadcast_active_channel(ws_id) -> int`
2. 将原内联逻辑改为调用 `_broadcast_active_channel`
3. 验证提取后 rollcall 功能不变

### Phase 2：`!pipeline_activate`（30min）

4. 新增 `_cmd_pipeline_activate` 处理函数
5. 新增管线状态检查辅助函数 `pipeline_exists(round_name)`
6. 注册到 `_ADMIN_COMMANDS`
7. 验证：`!pipeline_start R50` → 管线未激活 → `!pipeline_activate R50` → 激活成功

### Phase 3：`!step_handoff`（30min）

8. 复制 `_cmd_step_complete` 逻辑作为基础骨架
9. 在交接逻辑中插入 `_broadcast_active_channel` 调用
10. 注册到 `_ADMIN_COMMANDS`
11. 验证：最后一步 → 自动关闭管线 + 恢复大厅 + PM 通知

### Phase 4：方向 A 自动 MSG_SET_ACTIVE_CHANNEL（方向 B 验证后）

12. 在 `_cmd_step_handoff` 中确认 MSG_SET_ACTIVE_CHANNEL 自动推送正确
13. 在 `_cmd_pipeline_activate` 中确认激活即推送
14. 端到端验证全流程

---

## 6. 安全与边界

| 关注点 | 处理 |
|:-------|:-----|
| 重复激活 | `pipeline_is_active` 检查，已激活则拒绝 |
| 无管线时激活 | `pipeline_exists` 检查，不存在则报错 |
| 无工作室时激活 | `ws_mod.get_workspace` 检查，不存在则报错 |
| `!step_handoff` 权限 | `min_role=3`（工作室管理员），与 `!step_complete` 一致 |
| `!pipeline_activate` 权限 | `min_role=3`（管理员），与 `!pipeline_start` 一致 |
| 离线成员 | `MSG_SET_ACTIVE_CHANNEL` 仅推送给在线连接，离线成员上线后自动获得 persistence 中设置的频道 |
| 方向 A/B 互斥 | 方向 B 的 `!step_handoff` 包含 MSG_SET_ACTIVE_CHANNEL 功能；方向 A 是将其扩展到其他触发点。不冲突 |

---

## 7. 测试策略

| 测试类型 | 覆盖场景 |
|:---------|:---------|
| 集成测试 | `!pipeline_start R50` → 管线状态 `active=False` |
| 集成测试 | `!pipeline_activate R50` → 状态变 `active=True`，MSG_SET_ACTIVE_CHANNEL 发送 |
| 集成测试 | 重复 `!pipeline_activate` → 被拒绝 |
| 集成测试 | `!pipeline_activate` 时工作室不存在 → 报错 |
| 集成测试 | `!step_handoff step2 --output abc123` → Task 标记完成 + 下一人点名 + MSG_SET_ACTIVE_CHANNEL |
| 集成测试 | `!step_handoff` 最后一步 → 管线自动关闭 + 大厅恢复 |
| 回归测试 | `!step_complete` 原逻辑不变 |
| 回归测试 | 原有 rollcall MSG_SET_ACTIVE_CHANNEL 功能不变 |
| 回归测试 | 无 `!pipeline_activate` 场景下原 `!pipeline_start` 流程不变 |

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v0.1 | 2026-06-28 | 初版 — 方向 B（`!pipeline_activate` + `!step_handoff`）优先，方向 A（自动 MSG_SET_ACTIVE_CHANNEL）延后 |
