# R59 技术方案 — arch/dev 自动触发修复 + PM 自动兜底机制

> **版本：** v1.0
> **架构师：** 🏗️ 小开
> **日期：** 2026-06-30
> **基线需求：** `docs/R59/R59-product-requirements.md` v0.1
> **基线 WORK_PLAN：** `docs/R59/WORK_PLAN.md` v1.0

---

## 0. 执行摘要

R59 解决管线最后两个自动触发断点：**Step 2（arch）** 和 **Step 3（dev）** 在 `from_name=PM` 的工作室广播 @mention 后不响应，需要项目负责人 TG 私聊转发。

采用**方向 A（探测实验）→ 方向 B（编码适配）→ 方向 C（角色弹性兜底）** 三步策略。

---

## 1. 代码基线分析

### 1.1 当前通知路径（R58）

```
_cmd_step_complete (L1435)
  └─ 主角在线分支 (L1618-1643, R58 A2)
       ├─ L1619:  pm_name = config.PIPELINE_PM_NAME  (默认 "PM")
       ├─ L1622-1628: 构建 @primary_name 消息
       ├─ L1629:  持久化广播 _persist_broadcast(sender_ch, pm_name, mention_msg)
       ├─ L1630-1643: 广播到全体工作室成员
       │     from_name = pm_name  (="PM")
       │     type = "broadcast"
       └─ L1645-1652: 系统广播点名 + 30s ACK 等待
             from_name = "系统"
```

### 1.2 关键函数签名

| 函数 | 行号 | 作用 |
|:-----|:----:|:-----|
| `_cmd_step_complete` | 1435 | Step 交接核心，含 PM @mention 广播 |
| `_cmd_pipeline_start` | 1215 | 管线启动，含 kickoff PM @mention 广播 |
| `_send_to_agent` | 1730 | 定向通知（from_name 写死 `"系统"`） |
| `_r57_switch_to_backup` | 1782 | 备用接管（走 `_send_to_agent`） |

### 1.3 关键配置点

| 配置 | 位置 | 默认值 | 覆盖方式 |
|:-----|:-----|:-------|:---------|
| `PIPELINE_PM_NAME` | `config.py:69` | `"PM"` | `WS_PM_NAME` 环境变量 |
| `PIPELINE_STEP_MAP` | `config.py:73-86` | 硬编码六步五角色 | `PIPELINE_STEP_MAP_OVERRIDE` JSON 环境变量 |

### 1.4 代码定位小结

**方向 B 所有改动集中在：**
- `handler.py` L1618-1643（`_cmd_step_complete` 中的 PM @mention 广播段）
- `handler.py` L1318-1345（`_cmd_pipeline_start` 中的 kickoff 广播段）
- 新增：5 分钟超时后台监控任务（在 `_cmd_step_complete` 尾部）

---

## 2. 方向 A（探测实验）分析

### 2.1 实验状态

方向 A 已由 PM 在此工作室并行执行，记录实验数据。

### 2.2 实时实验数据（截至技术方案定稿）

| 实验编号 | 变体 | from_name | 小开(arch) 响应 | 结论 |
|:--------:|:-----|:---------:|:---------------:|:-----|
| 1a | @小开 | PM | ✅ ACK | arch 响应 PM from_name |
| 1b | @小开 | 大宏 | ✅ ACK | arch 响应大宏 from_name |

> **初步结论：** 小开（本实例 arch）对 `from_name=PM` 和 `from_name=大宏` 均正常响应。这提示「arch 不响应 from_name=PM」**可能与具体 bot 的网关配置有关**，并非所有 arch bot 都有此问题。

### 2.3 对方向 B 的影响

- 如果完整实验确认 arch 和 dev（现网生产实例）确实不响应 `from_name=PM`，方向 B 需要引入角色差异化 `from_name`
- 如果完整实验发现 arch/dev **实际可以响应**（当前卡住另有原因），方向 B 可降级为仅做消息格式增强 + PM 兜底
- **建议方向 B 写入条件分支逻辑**：当 `next_role` 为 arch/dev 时使用可配置的 `from_name` 值，其他角色保持 PM 不变

### 2.4 Dev 环境连接信息

| 项目 | 值 |
|:-----|:----|
| Dev WS 端点 | `ws://72.62.197.200:8766` |
| Dev HTTP 端点 | `http://72.62.197.200:8766` |
| 端口 | `8766`（无映射，--network host） |
| 数据 | 独立于 main，完全隔离 |
| bot 连接 | 各 bot 已配同时连接 dev+main |

实验脚本通过 Python websocket 库连接 `ws://72.62.197.200:8766`，发送原始 WS 消息即可。

---

## 3. 方向 B（编码适配）详细设计

### 3.1 角色差异化 from_name（B1）

**改动位置：** `handler.py` L1618-1643（`_cmd_step_complete` 中的 PM @mention 段）

**当前代码：**
```python
pm_name = config.PIPELINE_PM_NAME   # 默认 "PM"
```

**改造后：**
```python
# 角色差异化 from_name
if next_role in ["arch", "dev"]:
    pm_name = config.PIPELINE_AGENT_FROM_NAME   # 新增配置，默认 "PM" 保持不变
else:
    pm_name = config.PIPELINE_PM_NAME            # 现有配置
```

**新增配置（`config.py`）：**
```python
# ── R59 A: Agent (arch/dev) notification display name ──
# Separate from PIPELINE_PM_NAME for roles that need custom from_name.
# Environment variable WS_AGENT_FROM_NAME overrides the default.
PIPELINE_AGENT_FROM_NAME: str = os.environ.get("WS_AGENT_FROM_NAME", "PM")
```

> **设计理由：** 避免硬编码。如果在实验中发现 arch/dev 需要 `from_name=大宏`（项目负责人 TG 用户 ID），只需设置 `WS_AGENT_FROM_NAME=大宏` 环境变量，无需改代码。`PIPELINE_PM_NAME` 保持对其他 4 个不变角色的保护。

### 3.2 角色差异化消息格式（B1 增强）

**改动位置：** `handler.py` L1622-1628

**当前格式（统一）：**
```python
mention_msg = f"@{primary_name} 🚨 Step「{next_step}」到你了！\n\n"
              f"📄 需求：{req_url}\n"
              f"📋 WORK_PLAN：{plan_url}\n"
              f"🔗 上一步产出：{output_ref}\n\n"
              f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>"
```

**改造后（按角色差异化）：**
```python
if next_role in ["arch", "dev"]:
    # arch/dev 需要更明确的触发消息（含 code block + 更直接的指令）
    mention_msg = (
        f"@{primary_name} 🚨 Step「{next_step}」到你了！\n\n"
        f"📄 需求：{req_url}\n"
        f"📋 WORK_PLAN：{plan_url}\n"
        f"🔗 上一步产出：{output_ref}\n\n"
        f"```\n"
        f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>\n"
        f"```"
    )
else:
    mention_msg = (
        f"@{primary_name} 🚨 Step「{next_step}」到你了！\n\n"
        f"📄 需求：{req_url}\n"
        f"📋 WORK_PLAN：{plan_url}\n"
        f"🔗 上一步产出：{output_ref}\n\n"
        f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>"
    )
```

### 3.3 角色差异化发送路径（B2）

**改动位置：** `handler.py` L1628-1643

**当前：** 所有角色走广播 + persist（统一路径）

**改造后：**
```python
if next_role in ["arch", "dev"]:
    # arch/dev: _send_to_agent 直连（from_name 使用差异化值）
    direct_payload = json.dumps({
        "type": "broadcast", "channel": sender_ch,
        "from_name": pm_name,     # 差异化 from_name（非 "PM" 的可能）
        "content": mention_msg, "ts": time.time(),
    })
    for conn in list(_connections.get(primary_agent, set())):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(direct_payload)
            elif hasattr(conn, "send"):
                await conn.send(direct_payload)
        except Exception:
            pass
else:
    # 其他角色：工作室广播（R58 路径，完整保留）
    _persist_broadcast(sender_ch, pm_name, mention_msg)
    mention_payload = json.dumps({
        "type": "broadcast", "channel": sender_ch,
        "from_name": pm_name, "from": pm_name,
        "content": mention_msg, "ts": time.time(),
    })
    for member_id in ws_obj.members:
        for conn in list(_connections.get(member_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(mention_payload)
                elif hasattr(conn, "send"):
                    await conn.send(mention_payload)
            except Exception:
                pass
```

> **设计理由：** 广播对所有成员推一次，`_send_to_agent` 只对特定 agent 推。如果实验发现 arch/dev 只响应定向消息（非广播），此分支可确保它们走定向路径。如果实验确认广播也有效（如本工作室中的实验 1a/b），则此分支可降级为纯格式差异化 + 广播路径不变。

### 3.4 _cmd_pipeline_start kickoff 同步改造（B1 同行）

**改动位置：** `handler.py` L1318-1345

思路同 `_cmd_step_complete`：如果 arch 是 Step 2 的 target_role，kickoff 广播的 from_name 也使用差异化值。**但 kickoff 消息是 `@全员` 格式不分角色，所以仅调整 from_name 到 `PIPELINE_PM_NAME`**（此处在 R58 已正确使用配置值，无需改动）。

### 3.5 PM 自动兜底机制（B3）

**新增位置：** `handler.py` `_cmd_step_complete` 尾部（L1694 之前插入）

```python
# ── R59 B3: PM auto-fallback monitor ──
if next_role in ["arch", "dev"]:
    asyncio.create_task(_r59_auto_fallback_monitor(
        round_name=round_name,
        next_step=next_step,
        next_role=next_role,
        primary_agent=primary_agent,
        primary_name=primary_name,
        sender_ch=sender_ch,
        ws_obj=ws_obj,
        timeout_minutes=5,
    ))
# ── R59 B3: End ──
```

**新增函数（`handler.py` 尾部）：**
```python
async def _r59_auto_fallback_monitor(
    round_name: str, next_step: str, next_role: str,
    primary_agent: str, primary_name: str,
    sender_ch: str, ws_obj,
    timeout_minutes: int = 5,
) -> None:
    """R59 B3: PM 自动兜底 — 检查 arch/dev 是否在超时内响应。
    
    如果超时后仍未检测到 bot 的 ACK 或任务推进信号：
    1. 在工作室内输出催促消息
    2. 通过 TG 通知项目负责人
    """
    await asyncio.sleep(timeout_minutes * 60)
    
    try:
        # 检查是否已经有活跃 Task（表示 bot 已响应并开始工作）
        tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
        has_active_task = any(
            t.get("name") == next_step and 
            t.get("state") != p.TaskState.COMPLETED.value and
            t.get("state") != p.TaskState.PENDING.value
            for t in tasks
        )
        
        # 检查 pipeline_state 中的 notification status
        pstate = _PIPELINE_STATE.get(round_name, {})
        step_notif = pstate.get("step_notifications", {}).get(next_step, {})
        ack_status = step_notif.get("ack_status", "")
        
        already_responded = has_active_task or ack_status in ("acknowledged", "completed")
        
        if not already_responded:
            # Bot 未响应 → 催一下
            reminder_msg = (
                f"@{primary_name} ⏰ Step「{next_step}」已通知 {timeout_minutes} 分钟，"
                f"请确认收到。若无法响应，请联系项目负责人处理。"
            )
            _persist_broadcast(sender_ch, config.PIPELINE_PM_NAME, reminder_msg)
            reminder_payload = json.dumps({
                "type": "broadcast", "channel": sender_ch,
                "from_name": config.PIPELINE_PM_NAME, "from": config.PIPELINE_PM_NAME,
                "content": reminder_msg, "ts": time.time(),
            })
            for member_id in ws_obj.members:
                for conn in list(_connections.get(member_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(reminder_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(reminder_payload)
                    except Exception:
                        pass
            
            # TG 通知项目负责人（通过 _admin 频道日志，供外部 TG 桥接读取）
            try:
                admin_channel = p.ADMIN_CHANNEL
                tg_alert = (
                    f"📋 [R59_FALLBACK] {round_name} | Step「{next_step}」({next_role}) "
                    f"已通知 {timeout_minutes} 分钟但 bot {primary_name} 未响应。\n"
                    f"工作室: {sender_ch}\n"
                    f"请检查是否需要 TG 转发触发。"
                )
                ms.save_message(
                    msg_id=str(uuid.uuid4()), msg_type="broadcast",
                    from_agent="系统", from_name="系统",
                    content=tg_alert, ts=time.time(),
                    data_dir=config.DATA_DIR, channel=admin_channel,
                )
                write_chat_log("系统", tg_alert, channel=admin_channel)
            except Exception:
                pass
    except Exception as e:
        write_chat_log("系统", f"[R59_FALLBACK 异常] {e}")
```

> **设计要点：**
> - 使用 `asyncio.create_task()` 将兜底作为后台任务运行，不阻塞 `_cmd_step_complete` 的返回
> - 超时后先检查 bot 是否已自行响应（通过 task 状态），避免重复催促
> - TG 通知走 `_admin` 频道日志，由 TG 桥接 bot 转发（当前架构中 TG 已连接 ws-bridge 的 admin 频道）

### 3.6 改动总结

| 文件 | 行号 | 改动 | 估算行数 |
|:-----|:----:|:-----|:--------:|
| `server/config.py` | 新增（~L70） | `PIPELINE_AGENT_FROM_NAME` 配置项 | ~6 行 |
| `server/handler.py` | L1618-1643 | 角色差异化 from_name + 消息格式 | ~20 行 |
| `server/handler.py` | L1628-1643 | 角色差异化发送路径（可选） | ~15 行 |
| `server/handler.py` | L1694 前 | 新增 B3 后台任务启动 | ~8 行 |
| `server/handler.py` | 文件尾部 | 新增 `_r59_auto_fallback_monitor` 函数 | ~55 行 |
| **合计** | | | **~104 行** |

---

## 4. 方向 C（角色弹性）设计概要

> 优先级：P2。在方向 B 实现后评估是否需要。方向 C 不纳入 R59 编码，仅记录设计思路供后续轮次参考。

### 4.1 PIPELINE_STEP_MAP 角色解耦思路

**当前耦合：**
```python
PIPELINE_STEP_MAP = {
    "step2": {"role": "arch", "primary": "arch", "backup": "dev", ...},
    "step3": {"role": "dev", "primary": "dev", "backup": "arch", ...},
}
```

**改造思路：**
- `role` 字段保留当前语义（职责标签）
- 新增 `executor_role` 字段，指定谁来执行（不强制 = role 相同）
- 允许 PM 在 `RUN_WORK_PLAN` 配置中覆盖 `executor_role`

```python
PIPELINE_STEP_MAP = {
    "step2": {"role": "arch", "executor_role": "review", ...},
    # 此时 Step 2 的角色标签是 arch，但由 review 执行
}
```

### 4.2 约束检查

| 约束 | 检查逻辑 |
|:-----|:---------|
| 不能自审自测 | step3 的 `executor_role` ≠ step4 的 `executor_role` |
| 写方案 ≠ 编码 | step2 的 `executor_role` ≠ step3 的 `executor_role` |

### 4.3 与 F-16 的关系

方向 C 是 F-16（Agent Card 角色映射持久化重构）的**简化先导版本**，在代码层实现角色解耦，后续 F-16 再迁移到持久化数据层。

> **评估结论：** 如果方向 B 能成功解决 arch/dev 触发问题，方向 C 可推迟到 F-16 统一实现。如果方向 B 完全无效（arch/dev 无论如何都无法自动触发），方向 C 作为最后兜底再由 PM 决策是否提前执行。

---

## 5. 变更风险评估

### 5.1 回归风险

| 影响 | 角色 | 验证方法 |
|:-----|:-----|:---------|
| review 是否仍走 R58 广播路径 | review | 代码审查确认未进入 `next_role in ["arch","dev"]` 分支 |
| qa 是否仍走 R58 广播路径 | qa | 同上 |
| admin 通知格式是否不变 | admin | 同上 |
| 现有 30s ACK 机制是否不变 | 全部 | ACK 逻辑（L1654）在差异化分支之外，不受影响 |

### 5.2 环境变量安全

- `WS_AGENT_FROM_NAME` 默认值 = `"PM"`，未设置时行为与 R58 完全一致（零影响）
- `PIPELINE_PM_NAME` 不受本次改动影响

### 5.3 合入策略

1. 方向 B 编码完成后，先部署到 **dev 环境**（dev 容器）：构建 `ws-bridge:r59-dev` 镜像
2. PM 在 dev 环境中执行完整管线测试（Step 1→2→3）
3. 确认 arch/dev 自动触发正常后，合入 main 构建生产镜像
4. 如果 dev 测试发现 arch/dev 仍不响应，调整 `WS_AGENT_FROM_NAME` 实验值再次测试

---

## 6. 开放问题问答案

| # | 问题 | 当前决策 |
|:-:|:-----|:---------|
| Q1 | arch/dev 的 bot 网关配置在哪查看？ | 不在 ws-bridge 范围内。通过方向 A 实验反推触发条件 |
| Q3 | 方向 C 与 F-16 冲突？ | 方向 C 是 F-16 的前置简化版，无冲突 |
| Q4 | from_name=项目负责人ID 是否提升权限？ | 需要项目负责人明确授权（大宏已在通讯中确认） |
| Q5 | from_name 值硬编码 or 配置？ | **必须走配置**（`WS_AGENT_FROM_NAME` 环境变量），绝不硬编码 |

---

## 7. 与需求文档的差异说明

| 需求点 | 需求描述 | 方案差异 | 理由 |
|:-------|:---------|:---------|:------|
| B3 兜底-工作室催促 | PM 自动输出 @架构师/开发工程师 | 加入 5 分钟超时检查防止重复催促 | 避免 bot 实际已工作但催促消息产生干扰 |
| B3 兜底-TG 通知 | PM 通过 TG 通知项目负责人 | 走 `_admin` 频道日志 + ws-bridge TG 桥接 | 当前架构中 TG 通过 admin 频道与 ws-bridge 对接，不引入新的 TG API 调用 |

---

## 8. 工作分解

| 任务 | 耗时估计 | 前置依赖 |
|:-----|:---------|:---------|
| B1: config.py 新增 AGENT_FROM_NAME | ~5 min | 方向 A 实验数据（角色差异化值） |
| B1: handler.py 角色差异化 from_name+格式 | ~10 min | B1 config |
| B2: handler.py 角色差异化发送路径 | ~10 min | 方向 A 实验数据（是否需直连） |
| B3: _r59_auto_fallback_monitor 函数 | ~20 min | B1/B2 完成 |
| B3: _cmd_step_complete 中启动后台任务 | ~5 min | B3 函数完成 |
| dev 部署测试 + 实验验证 | ~30 min | 编码完成 |
| 合入 main + 生产部署 | ~10 min | dev 测试通过 |

---

> **文档版本历史：**
> - v1.0 — 初稿，基于 R59 需求文档 v0.1 + WORK_PLAN v1.0
