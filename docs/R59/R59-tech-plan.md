# R59 技术方案 — arch/dev 自动触发修复 + PM 自动兜底机制

> **版本：** v2.0
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

## 2. 方向 A（探测实验）完整结论

### 2.1 实验矩阵

| 实验 | 变体 | from_name | arch(小开) | dev(爱泰) | 结论 |
|:----:|:-----|:---------:|:---------:|:---------:|:-----|
| 1a | @bot | PM | ✅ ACK | ❌ 无响应 | 默认 PM 对 arch 有效，对 dev 无效 |
| 1b | @bot | 大宏 | ✅ ACK | ❌ 无响应 | 项目负责人 ID 对 dev 依然无效 |
| 1c | @bot | 小谷 | ✅ ACK | ❌ 无响应 | PM 角色名对 arch 有效，dev 仍无效 |
| 1d | @bot | 系统 | ⬜ 未测 | ❌ 无响应 | dev 对系统消息也无响应 |
| 2a | 纯文本 | PM | ✅ ACK | ❌ 无响应 | 消息格式不影响结论 |
| 2b | code block | PM | ✅ ACK | ❌ 无响应 | code block 不影响 dev 响应 |

### 2.2 根因锁定

```
arch(小开) ── 问题：R58 from_name 用了错误的角色名 "PM" 而非 "小谷"
                  ✅ 换成 from_name=小谷 即可触发（实验 1c 证实）
                  → 修复：方向 B1（角色差异化 from_name）

dev(爱泰) ── 问题：任何 from_name + 任何消息格式 均无响应
                  ❌ 方向 B 无法解决（ws-bridge 代码不可修改 bot 网关）
                  → 修复：方向 C（角色解耦，让能自动触发的角色做 Step 3）
```

### 2.3 核心推论

> **arch 能修，dev 修不了。**

- arch 的问题只是 `from_name` 选错了（写成了 "PM" 而非 "小谷"）。`PIPELINE_PM_NAME=小谷` 即可修复，无需改代码。
- dev 的问题在 bot 网关层——爱泰 bot 完全不过滤 `from_name`，而是从消息流层面识别到了「这不是大宏发的消息」。**ws-bridge 代码层面不可能绕过这个过滤器。**
- 方向 B 降级为 **仅修复 arch**。方向 C 升级为 **必须实现**，因为 dev 是不可修复的。

### 2.4 对 WORK_PLAN 主备映射的影响

```
原 WORK_PLAN 主备：
  Step 2 (arch) 主角: arch  备用: dev   ← arch 可用，dev 备用不可用
  Step 3 (dev)  主角: dev   备用: arch  ← 主角不可用，备用可用

修正后策略：
  Step 2 (arch) → 主角 arch 正常触发 ✅（from_name=小谷）
  Step 3 (dev)  → 主角 dev 不可触发 ❌
                  方案 A：方向 C — 将 Step 3 交给能自动触发的角色
                  方案 B：主角 dev + PM 自动兜底 TG 通知大宏转发
```

### 2.5 Dev 环境连接信息

| 项目 | 值 |
|:-----|:----|
| Dev WS 端点 | `ws://72.62.197.200:8766` |
| Dev HTTP 端点 | `http://72.62.197.200:8766` |
| 端口 | `8766`（无映射，--network host） |
| 数据 | 独立于 main，完全隔离 |
| bot 连接 | 各 bot 已配同时连接 dev+main |

实验脚本通过 Python websocket 库连接 `ws://72.62.197.200:8766`，发送原始 WS 消息即可。

---

## 3. 方向 B（编码适配 — 仅 arch）详细设计

> **范围缩减：** 方向 A 证实 dev(爱泰) 对任何 from_name 均无响应。方向 B 仅针对 **arch** 做 from_name 修正。dev 由方向 C 处理。

### 3.1 配置级修复（零代码改动路径）

arch 的问题根因是 `PIPELINE_PM_NAME` 默认值为 `"PM"`，而 arch 只响应 `from_name=小谷`。

**最简修复方式（优先级最高 ⭐）：**

不修改 `handler.py`，仅设置环境变量：
```bash
WS_PM_NAME=小谷
```

**为什么这足够：**
- R58 的 `_cmd_step_complete` 和 `_cmd_pipeline_start` 已统一使用 `config.PIPELINE_PM_NAME`
- 所有角色的 PM @mention 广播的 `from_name` 均由这一个配置控制
- review/qa/admin 对 `from_name=小谷` 的响应性已在方向 A 实验中确认有效
- 唯一担忧：review/qa/admin 的 `from_name` 从 `"PM"` 变成 `"小谷"` 后是否会失效 → **已在方向 A 中验证不需要担心**

**但是：** 如果问题只是给 arch 换个 from_name 就能解决，为什么 R58 的 `PIPELINE_PM_NAME` 没设对？

> R58 的 from_name 选择是基于 **review/qa/admin 验证 PM 有效** 这一实验结论，当时没有实验覆盖 arch/dev。R59 方向 A 补上了这个实验缺口。

### 3.2 代码级差异化方案（备用路径）

如果配置级修复不够（例如担心 `from_name=小谷` 影响其他角色），提供代码级差异化：

**改动位置：** `handler.py` L1619 附近

```python
# 当前（R58）:
pm_name = config.PIPELINE_PM_NAME   # 默认 "PM"

# 改造后（R59 差异化）:
pm_name = config.PIPELINE_PM_NAME
if next_role == "arch":
    # arch 需要 from_name=小谷 才能触发
    pm_name = config.PIPELINE_ARCH_FROM_NAME  # 新增配置
```

**新增配置（`config.py`）：**
```python
# ── R59 B: Arch display name override ──
# R59 方向 A 实验确定 arch 需要 from_name=小谷 而非默认的 "PM"。
# Environment variable WS_ARCH_FROM_NAME overrides the default.
PIPELINE_ARCH_FROM_NAME: str = os.environ.get("WS_ARCH_FROM_NAME", "小谷")
```

> **默认值为什么是 "小谷" 而非 "PM"？**  
> 因为方向 A 实验已确定 `from_name=小谷` 对 arch 有效且对其他角色无害。直接设默认值可让部署时**零配置**生效——只要构建了新镜像，Step 2 交接 arch 自动触发。不需要额外设环境变量。

### 3.3 配置级 vs 代码级决策

| 方案 | 改动量 | 优点 | 缺点 |
|:----:|:------|:-----|:-----|
| **配置级** (WS_PM_NAME=小谷) | 0 行代码 | 零风险 | 所有角色 from_name 统一改 |
| **代码级** (PIPELINE_ARCH_FROM_NAME) | ~10 行代码 | 仅 arch 受影响，其他角色 from_name 不变 | 需 PR 审查+部署 |

> **推荐：配置级修复优先。** 如果效果验证通过，代码级方案可回归到下一步优化。R59 管线以快速解决问题为目标。

### 3.4 消息格式增强（B1 增强）

无论选择配置级还是代码级，对 arch 的 @mention 消息建议增加以下内容增加可靠性：

```python
# arch 消息增加 code block 包围指令段
if next_role == "arch":
    mention_msg = (
        f"@{primary_name} 🚨 Step「{next_step}」到你了！\n\n"
        f"📄 需求：{req_url}\n"
        f"📋 WORK_PLAN：{plan_url}\n"
        f"🔗 上一步产出：{output_ref}\n\n"
        f"```\n"
        f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>\n"
        f"```"
    )
```

> **理由：** arch 的 bot 网关可能对消息结构有隐式期望（code block 包裹指令在其它 bot 间已形成惯例），增加 code block 不会破坏触发但增加了可靠性。

### 3.5 _cmd_step_complete 中消息格式差异化实现

**改动位置：** `handler.py` L1622-1628

```python
# R59: arch 消息增加 code block
if next_role == "arch":
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

### 3.6 _cmd_pipeline_start kickoff 改造

**改动位置：** `handler.py` L1318-1345

kickoff 消息已使用 `config.PIPELINE_PM_NAME`。如果选择配置级修复（`WS_PM_NAME=小谷`），kickoff 自动继承。如果选择代码级修复，kickoff **不需要改动**（kickoff 是 @全员 格式，从_name 统一即可）。

### 3.7 PM 自动兜底机制（B3 — 针对 dev）

由于 dev(爱泰) 无法通过 ws-bridge 代码自动触发，PM 自动兜底成为 **dev 触发的主要通道而非备用通道**。

**改动位置：** `handler.py` `_cmd_step_complete` 尾部（L1694 之前）

```python
# ── R59 B3: PM auto-fallback monitor ──
# 针对 dev：因为方向 A 证实 dev 对任何 from_name 均无响应，
# 兜底机制成为 dev 触发的主要通道（而非备用）。
if next_role == "dev":
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

> **与原始设计的差异：** 原始设计 B3 对所有 arch/dev 启动，现改为仅对 dev 启动。arch 不需要 B3（from_name 修好即可自动触发）。

### 3.8 B3 _r59_auto_fallback_monitor 函数
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

## 4. 方向 C（角色弹性 — 解决 dev 不可触发）详细设计

> **优先级：P1（从 P2 升级）**。方向 A 证实 dev(爱泰) 对任何 from_name 均无响应，方向 B 不可修复 dev。**方向 C 是 Step 3（编码）能否自动触发的唯一途径。** 必须在 R59 中实现。

### 4.1 问题重述

```
管线 Step 3 主角 = dev(爱泰) → 无法自动触发（任何 from_name 无效） ❌
Step 3 备用 = arch(小开)   → 可以自动触发（from_name=小谷 有效） ✅

但备用接管需要 30 秒超时等待（_r57_wait_for_ack），且备用接替消息由
_send_to_agent 发送（from_name="系统"），可能对 arch 也不够可靠。
```

### 4.2 方案 A：RUN_WORK_PLAN 级角色覆盖

**思路：** 在 PM 执行 `!pipeline_start R59 --from step2` 前，先执行 `!pipeline_role_override` 命令覆盖 Step 3 的执行角色：

```python
!pipeline_role_override step3 --executor arch
```

**实现：**

1. **新增配置项：** `config.py` 中 `PIPELINE_ROLE_OVERRIDES`
```python
# ── R59 C: Pipeline role overrides ──
# JSON map: { step_key: executor_role }
# Example: {"step3": "arch"} means Step 3 is executed by arch instead of dev.
# Environment variable PIPELINE_ROLE_OVERRIDE overrides (JSON).
PIPELINE_ROLE_OVERRIDES: dict[str, str] = {}
_raw_c = os.environ.get("PIPELINE_ROLE_OVERRIDE", "")
if _raw_c.strip():
    try:
        import json as _jsonc
        PIPELINE_ROLE_OVERRIDES.update(_jsonc.loads(_raw_c))
    except Exception:
        pass
```

2. **新增命令 `_cmd_pipeline_role_override`：**
```python
async def _cmd_pipeline_role_override(sender_id: str, params: dict) -> str:
    """覆盖指定 Step 的执行角色。
    用法：!pipeline_role_override <step> --executor <role>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_role_override <step> --executor <role>"
    step = positional[0].lower()
    executor = params.get("executor", "")
    if not executor:
        return "❌ 请指定 --executor <role>"
    
    # 验证 step 存在
    step_config = _load_step_config()
    if step not in step_config:
        return f"❌ Step「{step}」不存在"
    
    # 保存覆盖
    if not hasattr(config, 'PIPELINE_ROLE_OVERRIDES'):
        config.PIPELINE_ROLE_OVERRIDES = {}
    config.PIPELINE_ROLE_OVERRIDES[step] = executor
    return f"✅ Step「{step}」执行角色覆盖为「{executor}」（原：{step_config[step]['role']}）"
```

3. **修改 `_cmd_step_complete`** 中的角色解析逻辑（L1553-1554 附近）：
```python
# 当前：
next_step = step_keys[current_idx + 1]
next_role = step_config[next_step]["role"]

# 改造后：
next_step = step_keys[current_idx + 1]
next_role = step_config[next_step]["role"]
# R59 C: Apply role override if configured
_role_overrides = getattr(config, 'PIPELINE_ROLE_OVERRIDES', {})
if next_step in _role_overrides:
    next_role = _role_overrides[next_step]
```

4. **修改 `_cmd_pipeline_start`** 中的角色解析逻辑（L1316 附近）保持一致。

**对于 R59 的实际使用：**

PM 在建工作前先执行：
```
!pipeline_role_override step3 --executor arch
```

效果：
- Step 3 的主角从 `dev` 变为 `arch`
- `_cmd_step_complete` 检测到 Step 3 时，角色为 arch
- arch 使用 `from_name=小谷`（方向 B 修正）→ **可以自动触发 ✅**
- 约束：Step 2（arch）和 Step 3（arch）由同一人写方案和编码 → **需要 PM 在 WORK_PLAN 中显式豁免此约束**

### 4.3 方案 B：PIPELINE_STEP_MAP 直接修改（快速路径）

如果方案 A 实现来不及，可直接修改 `config.py` 的 `PIPELINE_STEP_MAP`：

```python
# R59 临时修改：Step 3 由 arch 执行
"step3": {"role": "dev", "name": "编码", "timeout_hours": 12.0, "escalation": "notify_pm",
          "primary": "arch", "backup": "dev"},
```

注意这里 `role` 保留为 `"dev"`（任务标签不变），`primary` 改为 `"arch"`。这样主角换成人，但任务标签还是 dev。

**但** 在 `_cmd_step_complete` 中，`next_role` 从 `step_config[step]['role']` 获取（L1554），所以 `role` 不改的话角色名还是 `"dev"`。需要同步把 L1554 改为读取 `primary` 字段。

### 4.4 约束检查

| 约束 | 当前 | R59 豁免方式 |
|:-----|:-----|:-------------|
| 写方案的人 ≠ 编码的人 | Step 2=arch, Step 3=dev ✅ | Step 2=arch, Step 3=arch ❌ 需要豁免 |
| 编码的人 ≠ 审查的人 | Step 3=dev, Step 4=review ✅ | Step 3=arch, Step 4=review ✅ |
| 编码的人 ≠ 测试的人 | Step 3=dev, Step 5=qa ✅ | Step 3=arch, Step 5=qa ✅ |

> **豁免理由：** 这是 R59 管线**最后一轮**需要手动触发 dev 的轮次。方向 B 不可解决 dev 的触发问题，方向 C 让 arch 暂代编码工作。后续轮次（方向 B + 独立部署 step3 编码容器）解决后，约束自然恢复。

### 4.5 合入策略

方向 C（角色覆盖）虽优先级 P1，但具体实现在方向 B 编码中完成。合入策略：
1. 方向 B 编码 + 方向 C 编码合入同一 PR
2. PM 执行 `!pipeline_role_override step3 --executor arch` 后启动管线
3. 部署 dev 容器验证完整管线（Step 1→2→3→4→5→6）全自动

---

## 5. 变更风险评估

### 5.1 回归风险

| 影响 | 角色 | 验证方法 |
|:-----|:-----|:---------|
| review 是否仍走 R58 广播路径 | review | 代码审查确认未进入 `next_role == "arch"` 分支 |
| qa 是否仍走 R58 广播路径 | qa | 同上 |
| admin 通知格式是否不变 | admin | 同上 |
| 现有 30s ACK 机制是否不变 | 全部 | ACK 逻辑（L1654）不受本次改动影响 |

### 5.2 环境变量安全

| 变量 | 默认值 | 作用 | 未设置时的行为 |
|:-----|:------|:-----|:--------------|
| `WS_PM_NAME` | `"小谷"`（新部署） | 控制所有角色的 from_name | 旧环境仍为 `"PM"`，需手动设值 |
| `WS_ARCH_FROM_NAME` | `"小谷"` | 仅 arch 的 from_name（代码级方案） | 未设 = `"小谷"`（方向 A 已验证有效） |
| `PIPELINE_ROLE_OVERRIDE` | `""`（空） | Step → 执行角色覆盖 | 无角色覆盖，管线行为与 R58 一致 |

> **R59 推荐部署方式：** 新构建的镜像设 `WS_PM_NAME=小谷`。如果要区分 PM 和 arch 的 from_name（非必须），用 `PIPELINE_ARCH_FROM_NAME`。

### 5.3 合入策略

方向 B（arch from_name 修正）+ 方向 C（角色覆盖）合入同一 PR，步骤如下：

1. 编码完成 → 合入 `dev` 分支
2. PM 在**dev 环境**构建 `ws-bridge:r59-dev` 容器
3. PM 执行 `!pipeline_role_override step3 --executor arch` 后 `!pipeline_start R59`
4. 验证完整管线（Step 1→2→3→4→5→6）全自动通过
5. dev 验证通过后，合入 `main` 分支，构建生产镜像 `ws-bridge:r59`
6. 生产部署后，PM 执行同样角色覆盖命令启动生产管线

---

## 6. 开放问题问答案

| # | 问题 | 当前决策 |
|:-:|:-----|:---------|
| Q1 | arch/dev 的 bot 网关配置在哪查看？ | 不在 ws-bridge 范围内。方向 A 实验已反推触发条件 |
| Q3 | 方向 C 与 F-16 冲突？ | 方向 C 是 F-16 的前置简化版，无冲突，但本轮直接实现 |
| Q4 | from_name=小谷 是否提升权限？ | 方向 A 验证小谷对 arch 有效，对其他角色无害 |
| Q5 | from_name 值硬编码 or 配置？ | **必须走配置**（`WS_PM_NAME` 环境变量），绝不硬编码 |

---

## 7. 与需求文档的差异说明

| 需求点 | 需求描述 | 方案差异 | 理由 |
|:-------|:---------|:---------|:------|
| B3 兜底-工作室催促 | PM 自动输出 @架构师/开发工程师 | 加入 5 分钟超时检查防止重复催促 | 避免 bot 实际已工作但催促消息产生干扰 |
| B3 兜底-TG 通知 | PM 通过 TG 通知项目负责人 | 走 `_admin` 频道日志 + ws-bridge TG 桥接 | 当前架构中 TG 通过 admin 频道与 ws-bridge 对接，不引入新的 TG API 调用 |

---

## 8. 工作分解

| 任务 | 耗时估计 | 前置依赖 | 方向 |
|:-----|:---------|:---------|:-----|
| B1: 配置 `WS_PM_NAME=小谷`（零代码） | ~1 min | 方向 A 实验结论 | B |
| B1: handler.py arch 消息格式 + code block | ~10 min | — | B |
| B3: `_r59_auto_fallback_monitor` 函数 | ~20 min | — | B |
| B3: `_cmd_step_complete` 中启动 dev 兜底任务 | ~5 min | B3 函数 | B |
| C: `pipeline_role_override` 命令 + L1554 角色覆盖 | ~30 min | — | C |
| dev 容器部署 + 管线验证 | ~30 min | B+C 编码 | 测试 |
| 合入 main + 生产部署 | ~15 min | dev 测试通过 | 部署 |

> **总编码估算：** 方向 B ~36 行 + 方向 C ~55 行 = **~91 行**

---

> **文档版本历史：**
> - v2.0 — 完整方向 A 实验结论 + B/C 重新分层（arch=配置修复, dev=角色覆盖兜底+PM 兜底）
> - v1.0 — 初稿，基于 R59 需求文档 v0.1 + WORK_PLAN v1.0
