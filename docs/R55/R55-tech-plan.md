# R55 技术方案 — 自动驾驶管线技术实现

> **版本：** v1.0
> **状态：** 📋 草稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-29
> **基于：** R55 产品需求 v0.2
> **改动范围：** 仅第①类（服务器代码 `server/handler.py`）+ `server/config.py`

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                         R55 六方向全景                            │
│                                                                  │
│   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐        │
│   │  A 放开  │   │ B 退回  │   │ C git   │   │ D 状态  │        │
│   │ 角色校验 │   │ 命令    │   │ 验证    │   │可视化  │        │
│   └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘        │
│        │              │              │              │              │
│        └──────────────┴──────────────┴──────────────┘              │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │  E 模式开关  │◄── `mode` 字段控制 A/B/C      │
│                    │  auto/manual │    是否生效                    │
│                    └──────┬──────┘                                │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │  F 减少回声  │── 定向发送取代全广播          │
│                    └──────┬──────┘                                │
│                           │                                       │
│              ┌────────────▼────────────┐                          │
│              │  _PIPELINE_STATE 扩展    │                          │
│              │  + rejected_steps       │                          │
│              │  + mode                 │                          │
│              │  + _step_advance_buffer │                          │
│              └─────────────────────────┘                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 关键决策

| # | 决策项 | 方案 | 理由 |
|:-:|:-------|:-----|:------|
| D1 | `_channel_ack_state` 是否复用？ | **不复用。** 退回状态直接存入 `_PIPELINE_STATE[round_name]["rejected_steps"][step_name]` | `_channel_ack_state` 是 ACK 协议结构（online/acked/timer/callback），与退回序列化的数据形态不同。退回记录是持久化状态，需要和管线 state 一起存在，不是临时 ACK 跟踪。 |
| D2 | 退回后 task 处理？ | **原 task 标 `INPUT_REQUIRED` + 创建新 task。** 保留审计线索（旧 task 不可修改），新 task 从 SUBMITTED 开始 | 复用现有 `INPUT_REQUIRED` 状态 + `reject_count` 机制。不破坏审计链，不新增 TaskState 枚举值。 |
| D3 | Git 验证方式？ | **`urllib.request` → `git ls-remote` HTTP 协议。** 仓库 URL 从 `config.py` 的新建 `GIT_REMOTE_URL` 配置读取 | 无需 API key，无需安装第三方库，纯 Python stdlib。超时 10s，失败降级为警告。 |
| D4 | 序列化策略？ | **2s 内存缓冲：** `_step_advance_buffer: dict[str, float]` — key 为 `round:step`，value 为时间戳 | 零 DB 开销，零锁复杂度。2s 内重复推进同一 step 被拒绝。多管线并发安全（key 含 round）。 |

---

## Part A — 方案设计

### 涉及文件

| 文件 | 改动类型 | 预估行数 |
|:-----|:---------|:--------|
| `server/handler.py` | 修改 + 新增函数 | ~110 行 |
| `server/config.py` | 新增配置项 | ~5 行 |

### 新增全局变量

```python
# R55: Step 推进 2s 序列化缓冲 — {round_name:step_name → timestamp}
_step_advance_buffer: dict[str, float] = {}
```

### 新增配置项（`config.py`）

```python
# R55: Step 推进参数
GIT_REMOTE_URL: str = "https://github.com/datahome73/ws-bridge.git"
```

### 方向 A：放开 `!step_complete` 角色校验（~10 行）

**目标：** 工作区内任意成员可推进 pending step。

**实现方式：** 修改 `_check_command_permission` 对 `step_complete` 命令的处理。

**详细逻辑：**

```
_check_command_permission() — 在 L374 的权限校验中增加特殊分支：

    if cmd_name == "step_complete" and min_role <= 1:
        # R55 Direction A: 自动驾驶模式 → 放开角色校验
        # 工作区成员即可推进 pending step
        # 具体 step 是否可推进由 _cmd_step_complete 内部校验
        return True, ""
```

**约束实现：** `_cmd_step_complete` 内部（~L1330）在放开后额外校验：

1. **仅推进 pending step：** 检查 `current_step` 指针是否在目标 step 之前或等于目标 step（不可跳过当前活跃 step）
2. **已完成的 step 不可重复推进：** 检查 `current_step` 是否已超过目标 step
3. **E 模式隔离：** 如果 mode 为 `manual`，恢复旧的角色校验（仅 step 负责人可推进）

**代码定位：**
- `_check_command_permission()` — handler.py:374
- `_cmd_step_complete()` — handler.py:1330

### 方向 B：新增 `!step_reject` 退回命令（~40 行）

**命令注册：**

```python
"step_reject": {
    "handler": _cmd_step_reject,
    "min_role": 1,           # 同 step_complete，工作区成员可用
    "workspace_scope": True,
    "usage": "!step_reject stepN --reason <原因>",
}
```

**新建函数：**

```python
async def _cmd_step_reject(sender_id: str, params: dict) -> str:
    """退回 Step N 到 pending 状态，附退回理由。"""
    # 1. 参数解析
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_reject stepN --reason <原因>"
    step_name = positional[0].lower().strip()
    reason = params.get("reason", "")
    if not reason:
        return "❌ 退回必须附理由：!step_reject stepN --reason <原因>"

    # 2. 解析管线上下文
    sender_ch = persistence.get_agent_channel(sender_id)
    ws_obj = workspace_mod.get_workspace_by_channel(...)
    round_name = _find_round_by_ws(...)

    # 3. 前置校验
    #    a) step 必须存在于 PIPELINE_STEP_MAP 中
    #    b) step 必须在当前活跃管线中
    #    c) 退回次数 ≤ TASK_REJECT_CEILING (2)

    # 4. 处理原 task: 标记 INPUT_REQUIRED + 写入 reject_count
    ts.update_state(task_id, p.TaskState.INPUT_REQUIRED.value, ...)
    ts.increment_reject_count(task_id, ...)
    reject_count = task["reject_count"] + 1

    # 5. 检查退回次数上限
    if reject_count >= p.TASK_REJECT_CEILING:
        # 第 3 次退回 → 升级给 PM
        _notify_admin(...)
        return f"🚨 {step_name} 已被退回 {reject_count} 次，自动升级给 PM 协调"

    # 6. 回退 pipeline step 指针
    #    找到 step 在 step_keys 中的索引 idx
    #    当前 current_step 已是该 step → 不动指针（退回当前 step，指针不前移）
    #    如果 current_step > step_idx → 指针回退到 step_idx
    _update_pipeline_step(round_name, step_name)

    # 7. 写入退回记录到 _PIPELINE_STATE
    #    _PIPELINE_STATE[round_name]["rejected_steps"][step_name] = {
    #        "reject_count": reject_count,
    #        "last_reason": reason,
    #        "rejected_by": sender_id,
    #        "rejected_at": time.time(),
    #    }

    # 8. 创建新 task（重新从 SUBMITTED 开始）
    #    调用 _cmd_task_create() 为同一 step 创建新任务

    # 9. 通知（方向 F 优化）：
    #    - 工作室内定向通知被退回的角色（非全广播）
    #    - _admin 频道记录退回日志

    return f"🔄 {step_name} 已退回（第 {reject_count} 轮）：{reason}"
```

**退回后状态流转示例：**

```
!step_reject step3 --reason "变量名阴影 shadow 了内置函数 len"

before:  [step1✅] [step2✅] [step3▶] [step4⏳] [step5⏳] [step6⏳]
                              ↑current
after:   [step1✅] [step2✅] [step3▶] [step4⏳] [step5⏳] [step6⏳]
                              ↑current (指针不变)
         但 step3 的 task: COMPLETED → INPUT_REQUIRED + 新 task SUBMITTED
         并在 pipeline_status 显示: 🔄 step3 — 退回(第1轮): 变量名阴影

退回后重推:
!step_complete step3 --output <sha>
         新 task: SUBMITTED → WORKING → COMPLETED
         pipeline 推进到 step4
```

### 方向 C：git 自动验证（~20 行）

**新增辅助函数：**

```python
async def _verify_git_commit(commit_sha: str) -> tuple[bool, str]:
    """检查远程 git dev 分支是否存在指定 commit。
    
    返回: (exists, message)
    - 存在: (True, "")
    - 不存在: (False, "❌ Commit xxx 不存在于远程 dev 分支")
    - 超时/失败时降级: (True, "⚠️ git 验证超时，已跳过验证")  # 返回 True 保持推进
    """
    repo_url = _r42cfg.GIT_REMOTE_URL
    try:
        # 用 asyncio 包装 urllib 请求，超时 10s
        # 请求: git ls-remote 远程仓库
        # 在返回中 grep 指定 commit_sha
        # ... 
    except (TimeoutError, Exception) as e:
        return True, f"⚠️ git 验证不可达（{str(e)[:30]}），已跳过验证，继续推进"
```

**在 `_cmd_step_complete` 中的调用（~L1338-1340 修改）：**

```python
# 原: 强制 --output，为空则报错
# 改为: --output 可选
output_ref = params.get("output", "")
if output_ref:
    # R55 Direction C: git 自动验证
    git_ok, git_msg = await _verify_git_commit(output_ref)
    if not git_ok:
        return git_msg       # ❌ 阻止推进
    # 如果 git_msg 是"⚠️ 警告"级别，继续推进
```

**配置项（`config.py` 新增）：**

```python
GIT_REMOTE_URL: str = "https://github.com/datahome73/ws-bridge.git"
# 可通过环境变量 WS_BRIDGE_GIT_REMOTE 覆盖
```

### 方向 D：`!pipeline_status` 显示退回记录 + 状态标记（~15 行）

**修改 `_cmd_pipeline_status`（~L1635）：**

在已有状态循环中增加：

```python
# ... 原状态逻辑 ...
# 读取退回记录
rejected = pstate.get("rejected_steps", {})
step_reject_info = rejected.get(step_key)
reject_suffix = ""
if step_reject_info:
    reject_suffix = (
        f" 🔄 退回(第{step_reject_info['reject_count']}轮): "
        f"{step_reject_info['last_reason']}"
    )

# 状态 emoji 覆盖：
# - 如有退回记录 → 🔄 (覆盖原状态)
# - task_state == COMPLETED → ✅
# - current_step 且 task_state == WORKING → ▶
# - 其他 pending → ⏳

# 增加 mode 标记
mode = pstate.get("mode", "auto")
```

**输出格式变化：**

```
before:
  📊 R55 管线状态
    ⏳ step1 — admin
    ✅ step2 — arch ◀ 当前
    ⏳ step3 — dev

after (退回后):
  📊 R55 管线状态（🚀 auto）
    ✅ step1 — admin
    ✅ step2 — arch
    🔄 step3 — dev ◀ 当前 退回(第1轮): 变量名阴影
    ⏳ step4 — review
    ⏳ step5 — qa
    ⏳ step6 — admin

after (退回 + 修正后):
  📊 R55 管线状态（🚀 auto）
    ✅ step1 — admin
    ✅ step2 — arch
    ✅ step3 — dev
    ▶ step4 — review ◀ 当前
    ⏳ step5 — qa
    ⏳ step6 — admin
```

### 方向 E：`--mode auto/manual` 模式开关 + `!pipeline_mode`（~10 行）

**修改 `_cmd_pipeline_start`（~L1150）：**

```python
# 新增 mode 参数解析
mode = params.get("mode", "auto").lower()
if mode not in ("auto", "manual"):
    return "❌ mode 参数仅支持 auto（自动驾驶）或 manual（手动模式）"

# 写入 _PIPELINE_STATE
_set_pipeline_state(round_name, {
    ...
    "mode": mode,       # ← 新增
    ...
})
```

**新增命令 `!pipeline_mode`：**

```python
"pipeline_mode": {
    "handler": _cmd_pipeline_mode,
    "min_role": 3,           # 管线状态修改，需 workspace admin
    "workspace_scope": True,
    "usage": "!pipeline_mode <auto|manual>",
}

async def _cmd_pipeline_mode(sender_id: str, params: dict) -> str:
    positional = params.get("_positional", [])
    if not positional or positional[0] not in ("auto", "manual"):
        return "❌ 用法：!pipeline_mode auto|manual"
    mode = positional[0]
    
    # 找到当前管线 state
    sender_ch = persistence.get_agent_channel(sender_id)
    round_name = _find_round_by_ws(...)
    
    # 更新 mode
    _PIPELINE_STATE[round_name]["mode"] = mode
    return f"✅ 管线 {round_name} 已切换为 {'🚀 自动驾驶' if mode == 'auto' else '📋 手动'} 模式"
```

**E 模式行为隔离：**

| 方向 | auto 模式 | manual 模式 |
|:----:|:---------|:-----------|
| A 放开角色校验 | ✅ 任何工作区成员可推进 pending step | ❌ 仅 step 负责人可推进（恢复旧行为） |
| B 退回命令 | ✅ 可用 | ✅ 可用（退回是独立命令，不依赖模式） |
| C git 验证 | ✅ 检查远程 commit | ✅ 检查（纯辅助功能，不依赖模式） |
| D 状态可视化 | ✅ 显示退回记录 | ✅ 显示退回记录 |
| F 减少回声 | ✅ 定向发送 | ✅ 定向发送 |

### 方向 F：减少 Step 交接复读机回声（~15 行）

**核心思路：** Step 交接消息（`!step_complete` / `!step_reject` 的结果通知）不广播给全工作室，而是定向发送给目标角色（下一棒或被退回角色） + 记录到 `_admin` 频道供 PM 查阅。

**实现方式：**

**新建定向发送函数：**

```python
async def _send_to_agent(agent_id: str, payload: str) -> bool:
    """定向发送消息给指定 agent（非广播）。"""
    for conn in list(_connections.get(agent_id, set())):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(payload)
            elif hasattr(conn, "send"):
                await conn.send(payload)
            return True
        except Exception:
            pass
    return False
```

**在 `_cmd_step_complete` 中的改动（~L1443-1448 附近）：**

```python
# 原: _cmd_rollcall_next → _broadcast_active_channel (广播给所有人)
# 改为: 定向发送给下一 step 的角色
next_role_agents = _find_agents_by_role(next_role, round_name, ...)
for agent_id in next_role_agents:
    # 发送 MSG_SET_ACTIVE_CHANNEL(定向) + 附任务分配通知
    # 静默完成，不广播给其他角色
    ...
# _admin 频道写入进度日志（已有）
```

**关于 `MSG_BROADCAST_TASK`：** 需求文档中提及的概念，本方案不新建消息类型。改用**定向发送 `MSG_SET_ACTIVE_CHANNEL` + 定向文本通知**，复用 R53 的 ACK 协议但不广播全工作室。

**是否全替换为定向发送？** **否。** 只在以下场景使用定向发送：
- `!step_complete` 的「点名下一棒」通知 → 只发给目标角色
- `!step_reject` 的「退回通知」→ 只发给被退回的 step 负责人

以下场景保持广播：
- 工作室创建成功通知
- `!pipeline_start` 的激活通知
- 工作室内其他系统消息

---

## Part B — 向后兼容分析

| 已有功能/命令 | 影响 | 说明 |
|:-------------|:----|:------|
| `!step_complete stepN --output <sha>` | ✅ 向后兼容 | `--output` 改为可选（不传则跳过 git 验证）；放开角色校验仅 auto 模式生效；manual 模式下行为不变 |
| `!step_complete stepN`（无 output） | ✅ 兼容 | 新增支持：不传 `--output` 时跳过 git 验证，直接推进 |
| `!_admin` 频道进度通知 | ✅ 兼容 | 方向 F 不改变 _admin 频道日志（仅减少工作室全广播） |
| `!pipeline_status` | ✅ 兼容 | 输出格式增强，旧字段全部保留（只新增"退回记录"和"模式标记"列） |
| `!_rollcall_next` | ⚠️ 部分变更 | 方向 F 将 `!step_complete` 的 `_rollcall_next` 调用改为定向发送；但 `!rollcall_next` 命令本身不变（直接调用时仍全广播） |
| `!pipeline_start` | ✅ 兼容 | 新增 `--mode` 参数；不传时默认为 `auto`，不影响旧调用方式 |
| 旧协议 `MSG_TASK_ACK` | ✅ 兼容 | 未修改 ACK 协议逻辑 |
| 旧手动推进流程 | ✅ 兼容 | manual 模式下放开回退为旧行为 |

---

## Part C — 验收标准映射

### 方向 A

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------|
| A-1 | member 在工作室内对 pending step 执行 `!step_complete step2 --output <sha>`，应成功推进 | 在实际管线中让 member 角色执行 | P0 |
| A-2 | 非工作区成员尝试推进，应被拒绝 | 用户权限校验（`workspace_scope=True` 保证） | P0 |
| A-3 | 对已完成的 step 执行 `!step_complete`，应报错「已完成的 step 不可重复推进」 | `_cmd_step_complete` 内部校验 current_step 位置 | P0 |
| A-4 | 同一 step 2 秒内被两人同时推进，第二次应被拒绝 | `_step_advance_buffer` 2s 检查 | P0 |

### 方向 B

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------|
| B-1 | `!step_reject step3 --reason "变量名阴影"`，step 指针回退到 step3 | `!pipeline_status` 显示 🔄 + 退回记录 | P0 |
| B-2 | 退回不带 `--reason`，应报错「退回必须附理由」 | 参数校验 | P0 |
| B-3 | 被退回 step 出现在 `!pipeline_status` 的退回记录中 | 退回记录写入 `_PIPELINE_STATE["rejected_steps"]` | P0 |
| B-4 | step 连续被退回 2 次后，第 3 次被拒绝并升级通知 | `reject_count >= TASK_REJECT_CEILING` | P0 |

### 方向 C

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------|
| C-1 | `!step_complete step2 --output 不存在的sha` → 报错「远程不存在此 commit」 | `_verify_git_commit` 返回 False | P1 |
| C-2 | `!step_complete step2 --output 存在的sha` → 正常推进 | 验证通过 | P1 |
| C-3 | `!step_complete step2`（不传 `--output`）→ 跳过 git 检查，正常推进 | `--output` 可选，params.get 默认空 | P1 |
| C-4 | `!step_complete step2 --output sha` 远程不可达 → 降级为警告，仍推进 | 超时/异常降级为 `(True, "⚠️")` | P1 |

### 方向 D

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------|
| D-1 | `!pipeline_status` 显示每个 step 的状态：✅ ▶ 🔄 ⏳ | 查看输出格式 | P1 |
| D-2 | 被退回 step 显示退回次数和最近一次理由 | `rejected_steps` 数据渲染 | P1 |
| D-3 | 管线在 auto/manual 模式下显示模式标记 | 输出头部含 `🚀 auto` 或 `📋 manual` | P1 |

### 方向 E

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------|
| E-1 | `!pipeline_start R55 --mode auto` → 管线自动模式运行 | 创建后 `!pipeline_status` 显示 🚀 auto | P2 |
| E-2 | `!pipeline_start R55`（不传 mode）→ 默认 auto 模式 | 默认值 `"auto"` | P2 |
| E-3 | `!pipeline_mode manual` → 切换为手动模式，方向 A 行为不可用 | member 角色在 manual 下 `!step_complete` 被拒绝 | P2 |

### 方向 F

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------|
| F-1 | `!step_complete` 广播的消息只有被 @mention 的角色回复 ACK，其他 bot 零输出 | 实测 Step 交接，观察工作室消息数 | P1 |
| F-2 | `!step_reject` 广播同样只触发被退回角色回复 | 实测退回场景 | P1 |
| F-3 | 系统 `📋` 进度消息不触发任何 bot 回复 | 观察 admin 频道通知输出 | P1 |
| F-4 | 被 @mention 的目标 bot 仍能正常回复 ACK 确认 | 确认接管流程不受影响 | P1 |

**检查：** PRD 验收标准共 22 项（A-1~A-4, B-1~B-4, C-1~C-4, D-1~D-3, E-1~E-3, F-1~F-4），本方案全部覆盖 ✅

---

## 附录

### 代码变更汇总表

| 方向 | 文件 | 操作 | 函数/位置 | 预估行数 |
|:----:|:----|:----|:----------|:--------|
| A | `handler.py` | 修改 | `_check_command_permission()` 增加 `step_complete` 特殊分支 | +5 |
| A | `handler.py` | 修改 | `_cmd_step_complete()` 增加内部 step 状态校验 + _step_advance_buffer 检查 | +10 |
| B | `handler.py` | 新增 | `_cmd_step_reject()` 函数 | +40 |
| B | `handler.py` | 注册 | `_ADMIN_COMMANDS["step_reject"]` | +5 |
| C | `handler.py` | 新增 | `_verify_git_commit()` 辅助函数 | +20 |
| C | `handler.py` | 修改 | `_cmd_step_complete()` — output 改为可选 + 验证调用 | +3 |
| C | `config.py` | 新增 | `GIT_REMOTE_URL` 配置项 | +3 |
| D | `handler.py` | 修改 | `_cmd_pipeline_status()` — 退回记录 + mode 标记 | +15 |
| E | `handler.py` | 修改 | `_cmd_pipeline_start()` — 新增 mode 参数 | +3 |
| E | `handler.py` | 新增 | `_cmd_pipeline_mode()` 函数 | +10 |
| E | `handler.py` | 注册 | `_ADMIN_COMMANDS["pipeline_mode"]` | +5 |
| F | `handler.py` | 新增 | `_send_to_agent()` 定向发送函数 | +8 |
| F | `handler.py` | 修改 | `_cmd_step_complete()` + `_cmd_step_reject()` — 定向发送 | +10 |
| | | | **合计** | **~137 行** |

### 双入口同步检查表

| 改动位置 | handler.py | `__main__.py` | 说明 |
|:---------|:----------|:-------------|:------|
| `_check_command_permission()` | ✅ L374 | N/A | 仅 handler.py 有该函数 |
| `_cmd_step_complete()` | ✅ L1330 | N/A | `_ADMIN_COMMANDS` 唯一路由 |
| `_cmd_step_reject()` | ✅ 新增 | N/A | `_ADMIN_COMMANDS` 唯一路由 |
| `_cmd_pipeline_mode()` | ✅ 新增 | N/A | `_ADMIN_COMMANDS` 唯一路由 |
| `_verify_git_commit()` | ✅ 新增 | N/A | 仅被 `_cmd_step_complete` 调用 |
| `_send_to_agent()` | ✅ 新增 | N/A | 仅被 handler 内函数调用 |
| `_cmd_pipeline_status()` | ✅ L1635 | N/A | `_ADMIN_COMMANDS` 唯一路由 |
| `_PIPELINE_STATE` 读写 | ✅ 同步 | N/A | 同一进程空间，不存在双入口同步问题 |

**结论：** 所有改动均在 `_ADMIN_COMMANDS` 体系下，无需 `__main__.py` 同步。✅

### 状态字段参考

**`_PIPELINE_STATE[round_name]` 完整字段（R55 扩展后）：**

```python
_PIPELINE_STATE[round_name] = {
    "active": True,                    # R42 已有
    "current_step": "step2",           # R42 已有
    "ws_id": "ws:abc123-R55-dev",      # R42 已有
    "started_at": 1234567890.0,        # R42 已有
    "work_plan_url": "https://...",    # R48 已有
    "triggerer_id": "admin-bot",       # R44 已有
    "mode": "auto",                    # ← R55 方向 E 新增
    "rejected_steps": {                # ← R55 方向 B 新增
        "step3": {
            "reject_count": 1,
            "last_reason": "变量名阴影 shadow 了内置函数 len",
            "rejected_by": "review-bot",
            "rejected_at": 1234567891.0,
        }
    },
}
```

### 序列化缓冲参考

```python
# R55 方向 A: 2s 序列化缓冲
_step_advance_buffer: dict[str, float] = {}

# 在 _cmd_step_complete 中推进前检查:
buffer_key = f"{round_name}:{step_name}"
last_ts = _step_advance_buffer.get(buffer_key, 0.0)
if time.time() - last_ts < 2.0:
    return f"❌ {step_name} 正在被推进中（2 秒序列化缓冲），请稍后重试"
_step_advance_buffer[buffer_key] = time.time()

# 清理：buffer 自动过期，不做主动清理（dict 大小有限，最多 active_pipelines × 6 steps）
```
