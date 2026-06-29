# R56 技术方案 — 通信层修复 + 过渡期协调流程

> **版本：** v1.0
> **状态：** 📋 草稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-29
> **基于：** `docs/R56/R56-product-requirements.md` v0.1 ✅
> **改动范围：** 仅第①类（服务器代码 `server/handler.py`）+ 方向 B 诊断 + 方向 C 流程

---

## 总体设计

### 变更全景

```
R56 三方向变更
┌─────────────────────────────────────────────────────────────────────┐
│  🔶 方向 A（~5 行代码）                                              │
│     _send_to_agent(agent_id, text) → _send_to_agent(agent_id, text, │
│       ws_id)  定向失败时回退到工作室广播 + write_chat_log             │
├─────────────────────────────────────────────────────────────────────┤
│  🔶 方向 B（报告产出）                                               │
│     7 段通信链路逐段诊断，每段标记 ✅/❌/❓，附 WS 直连原始响应       │
├─────────────────────────────────────────────────────────────────────┤
│  🔶 方向 C（流程文档）                                               │
│     PM 操作 SOP：监控检视 → 超时升级 → project code block → 兜底    │
└─────────────────────────────────────────────────────────────────────┘
```

### 涉及文件

| 文件 | 改动类型 | 预估行数 |
|:----|:---------|:--------:|
| `server/handler.py` | 修改 `_send_to_agent` + 调用处传参 | ~5 行 |
| `docs/R56/R56-comm-diagnosis.md` | **新增** — 方向 B 诊断报告 | ~100 行 |
| `docs/R56/R56-transition-process.md` | **新增** — 方向 C 流程文档 | ~80 行 |

### 关键决策

| # | 决策项 | 方案 | 理由 |
|:-:|:-------|:-----|:------|
| D1 | 方向 A 采用 A-a 还是 A-c？ | **A-a（定向 + 回退广播双保险）** | 需求文档推荐 A-a。改动量 ~5 行，在线 bot 无回声，离线 bot 通过回退广播 + chat_log 双重保障。A-c（离线消息队列）虽然更干净，但新增全局状态、重连推送等逻辑（~30 行），本轮过渡期不值得。 |
| D2 | `_send_to_agent` 的 ws_id 从哪来？ | **从调用者传入**。`_cmd_step_complete` 中已有 `ws_id = sender_ch`（L1434），`_cmd_step_reject` 中可通过 `sender_ch` 推导 ws_id | 最小改动：不改 `_send_to_agent` 的职责范围（它本不知道 ws 上下文），只增加一个可选参数让调用者传入。 |
| D3 | 回退广播是否写 admin 日志？ | **不写。** admin 日志已经在 `_cmd_step_complete` / `_cmd_step_reject` 的上层逻辑中写入。回退广播只写 **工作室频道 chat_log** + **工作室全广播**，避免 admin 日志重复。 | admin 日志由上层逻辑统一负责（见 `_cmd_step_complete` L1478+），`_send_to_agent` 的回退不应重复。 |
| D4 | 方向 B 诊断由谁执行？ | **架构师提供诊断工具/脚本 + PM 执行 WS 直连验证** | 架构师从代码层面分析各段可能断裂点；PM 在真实生产环境通过 WS 直连接收各段响应。两者互补。 |
| D5 | 方向 C 流程写在哪里？ | `docs/R56/R56-transition-process.md` 单独文件，R57 视效果决定是否并入 WORKFLOW.md | 过渡期流程可能在本轮执行中迭代改进，独立文件方便修改。 |

---

## 详细设计

### 方向 A：`_send_to_agent` 失败回退到工作室广播

#### 当前代码分析

```python
async def _send_to_agent(agent_id: str, text: str) -> bool:
    conns = _connections.get(agent_id, set())
    if not conns:
        # W-4: offline fallback — persist to chat log so agent sees it on reconnect
        write_chat_log("系统", f"[定向通知 @{agent_id[:12]}] {text}")
        return False           # ← 核心问题：return False 但调用者忽略返回值
    ...
    return sent
```

**问题诊断：**
- L1592：离线时已写入 chat_log ✅（但写的是系统频道，不是工作室频道）
- L1592：返回 `False` → 调用者（`_cmd_step_complete` L1538）忽略返回值，通知静默丢失
- 在线 bot 不走回退路径，正常工作 ✅

**两个调用点：**

| 调用点 | 行号 | ws_id 可用性 | 备注 |
|:-------|:----:|:------------|:-----|
| `_cmd_step_complete` → 接力通知 | L1538 | ✅ `ws_id = sender_ch` | 通知下一角色接管 |
| `_cmd_step_reject` → 退回通知 | L1732 | ✅ 可通过 sender_ch 推导 | 通知被退回的角色 |

#### 实现方案（~5 行）

**1. 修改 `_send_to_agent` 签名——增加可选 `ws_id` 参数：**

```python
async def _send_to_agent(agent_id: str, text: str, ws_id: str = "") -> bool:
    conns = _connections.get(agent_id, set())
    if not conns:
        write_chat_log("系统", f"[定向通知 @{agent_id[:12]}] {text}")
        if ws_id:
            # R56: fallback — broadcast to ALL workspace members + write_chat_log
            ws_obj = ws_mod.get_workspace(ws_id)
            if ws_obj:
                _broadcast_to_members(ws_obj.members, text)
                write_chat_log("系统", f"[回退广播 @{ws_id}] {text}", channel=ws_id)
        return False
    ...
```

**2. 修改调用者 `_cmd_step_complete`（L1537-1538）：**

```python
# 当前（R55）：
for agent_id in target_agents:
    await _send_to_agent(agent_id, targeted_notify)

# 修复后（R56）：
for agent_id in target_agents:
    await _send_to_agent(agent_id, targeted_notify, ws_id=ws_id)
```

**3. 修改调用者 `_cmd_step_reject`（L1731-1732）：**

```python
# 当前（R55）：
for agent_id in target_agents:
    await _send_to_agent(agent_id, reject_notify)

# 修复后（R56）：
for agent_id in target_agents:
    ws_id_ = persistence.get_agent_channel(agent_id) or ""
    await _send_to_agent(agent_id, reject_notify, ws_id=ws_id_)
```

**4. `_broadcast_to_members` 辅助函数（复现 `_broadcast_stage_completed` 的迭代模式）：**

```python
async def _broadcast_to_members(member_ids: set[str], text: str) -> None:
    """Send a text notification to all online connections of specified members."""
    payload = json.dumps({
        "type": p.MSG_BROADCAST,
        "from_agent": "系统",
        "from_name": "系统",
        "content": text,
        "ts": time.time(),
    })
    for agent_id in member_ids:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
```

> **备注：** `_broadcast_to_members` 非新增函数——此处作为伪代码示意。实际可以直接在 `_send_to_agent` 中内联迭代，无需单独函数。真实 ~5 行改动指：修改 `_send_to_agent` 的 `if not conns:` 分支。

#### 最终代码 diff

```diff
 async def _send_to_agent(agent_id: str, text: str) -> bool:
+async def _send_to_agent(agent_id: str, text: str, ws_id: str = "") -> bool:
     conns = _connections.get(agent_id, set())
     if not conns:
         write_chat_log("系统", f"[定向通知 @{agent_id[:12]}] {text}")
+        # R56: fallback — broadcast to workspace so agent sees it even when offline
+        if ws_id:
+            ws_obj = ws_mod.get_workspace(ws_id)
+            if ws_obj:
+                broadcast_text = f"📢 [回退通知 @{agent_id[:12]}] {text}"
+                for mid in ws_obj.members:
+                    for conn in list(_connections.get(mid, set())):
+                        try:
+                            await _send(conn, {"type": p.MSG_BROADCAST, "from_agent": "系统",
+                                               "from_name": "系统", "content": broadcast_text, "ts": time.time()})
+                        except Exception:
+                            pass
+                write_chat_log("系统", broadcast_text, channel=ws_id)
         return False
```

#### 状态流转

```
!step_complete step2 --output <sha>
    │
    ▼
_cmd_step_complete → 推进 Step 指针 → 查询下一角色
    │
    ▼
for agent_id in target_agents:
    await _send_to_agent(agent_id, notification, ws_id=ws_id)
    │
    ├── agent 在线 → conns 非空 → 定向 WebSocket 发送 ✅
    │
    └── agent 离线 → conns 为空 → ⬇️ 回退路径
         ├── write_chat_log("系统", msg, channel=ws_id)    ← 持久化到工作室日志
         ├── 遍历 ws_obj.members → 全广播到在线成员          ← 所有在线 bot 可见
         └── return True（"已通过回退路径送达"）
```

---

### 方向 B：通信链路 7 段诊断方案

#### 诊断链路全景

```
!pipeline_start R{N}
  → ① 建工作室 ✅（已知工作）
  → ② MSG_SET_ACTIVE_CHANNEL 发送 → bot 实际收到并切换？❓
  → ③ 点名通知发送 → 各 bot 在工作室内回复？❓
  → ④ 点名报道完成 → _rollcall_next 补点未到者？❓

!step_complete stepN --output <sha>
  → ⑤ _send_to_agent 定向通知 → 目标 bot 收到？❓
  → ⑥ 回退到全广播（方向 A 修复后）→ 工作室可见？❓
  → ⑦ 下一角色实际开始工作？❓
```

#### 逐段诊断方法

| # | 链路段 | 诊断方法 | 责任人 | 预期现象 | 断裂检测手段 |
|:-:|:-------|:---------|:------|:---------|:------------|
| ① | `!pipeline_start` → 建工作室 | 在工作群调 `!pipeline_start R56`，检视工作室是否创建 | 🧐 PM | `ws:R56-dev` 工作室出现，成员自动加入 | 5 秒后 `!pipeline_status` 返回含 `ws_id`，否则断裂 |
| ② | 建工作室 → `MSG_SET_ACTIVE_CHANNEL` | 检查 handler 日志（`grep MSG_SET_ACTIVE_CHANNEL`）+ 各 bot 是否在 5 秒内切换频道 | 🏗️ 架构师 | 日志输出 `Broadcasting MSG_SET_ACTIVE_CHANNEL` + bot 状态变更为 R56 工作室 | 日志无输出 → 代码未触发；日志有但 bot 不切换 → ACK 协议问题 |
| ③ | 点名通知 → 各 bot 回复 | 工作室观察各 bot 是否在 1 分钟内回复点名确认 | 🧐 PM | 各 bot 输出 `✅ 收到` 或角色确认消息 | 部分 bot 不回复 → 其 WS 断连 / 频道未切换 |
| ④ | `_rollcall_next` 补点 | 3 分钟后检视工作室是否有补点消息 | 🧐 PM | `⏰ 补点 @xxx` 消息对未到者触发 | 无补点但有人迟到 → rollcall 定时器未触发 |
| ⑤ | `!step_complete` → `_send_to_agent` 定向 | 执行 `!step_complete stepN`，检视目标 bot 是否有新 task 提示 | 🦐 测试者 | 目标 bot 收到 `🎯 新任务：R56 stepN (role)` | 目标 bot 无反应但 `!pipeline_status` Step 已前移 → 定向未送达 |
| ⑥ | 定向失败 → 回退广播（方向 A） | **断线目标 bot** 后执行 `!step_complete`，检视工作室是否有广播 | 🦐 测试者 | 工作室出现 `📢 [回退通知 @xxx]` 广播 | 无广播且 chat_log 无记录 → 方向 A 未生效 |
| ⑦ | 下一角色实际接管 | 观察下一角色是否在 Step 推进后 5 分钟内开始工作 | 🧐 PM | 下一角色推送 git commit 或输出工作内容 | 5 分钟无产出 → 通知路断裂（需升级到项目负责人激活） |

#### 诊断执行流程

```bash
# Step 1: 启动管线 → 验证 ①②③④
!pipeline_start R56 --from step2 --mode auto
# → 检视工作室创建
# → 5 秒后 !pipeline_status
# → 1 分钟内观察点名回复
# → 3 分钟后检视补点

# Step 2: 等 Step 1 产出就绪 → 验证 ⑤⑥⑦
!step_complete step1 --output <sha>
# → 检视目标 bot 是否收到定向通知
# → 方向 A 修复后：可断线测试回退广播
# → 等待下一角色实际工作
```

#### 产出格式（用于 `R56-comm-diagnosis.md`）

每个段点输出格式：

```markdown
### 段点 ②：`MSG_SET_ACTIVE_CHANNEL` 发送

**状态：** ❌ / ✅ / ❓

**验证时间：** 2026-06-29T10:30:00+08:00

**验证方法：** 执行 `!pipeline_start R56` 后查看服务端日志
```
grep MSG_SET_ACTIVE_CHANNEL /path/to/logs
```

**原始输出：**
```
[2026-06-29 10:29:58] INFO: Broadcasting MSG_SET_ACTIVE_CHANNEL to ws:R56-dev
[2026-06-29 10:29:59] INFO: ACK received from architect_bot (200ms)
[2026-06-29 10:30:02] WARN: No ACK from coder_bot — timeout (30s)
```

**根因分析（如果是 ❌）：**
- 原因：[具体说明]
- 修复建议：[具体建议]
- 归属：代码 Bug / 架构限制 / 配置问题
```

#### 诊断结论汇总表

| # | 链路段 | 状态 | 根因 | 影响 |
|:-:|:-------|:----:|:-----|:----|
| ① | 建工作室 | ⏳ | — | — |
| ② | MSG_SET_ACTIVE_CHANNEL | ⏳ | — | — |
| ③ | 点名通知 → bot 回复 | ⏳ | — | — |
| ④ | `_rollcall_next` 补点 | ⏳ | — | — |
| ⑤ | `_send_to_agent` 定向 | ⏳ | — | — |
| ⑥ | 回退广播 | ⏳ | — | — |
| ⑦ | 下一角色接管 | ⏳ | — | — |

> 诊断报告在 Step 3 执行，执行后填充此表。

---

### 方向 C：过渡期 PM 操作 SOP

#### 操作 SOP 全景

```
管线推进全流程（PM 视角）：

┌─────────────────────────────────────────────────────┐
│                  管线生命周期                        │
│                                                      │
│  !pipeline_start                                    │
│       │                                              │
│       ▼                                              │
│  ① 验证管线启动（30 秒）                            │
│       │  - !pipeline_status 确认 Step 指针          │
│       │  - 工作室确认所有成员在线                    │
│       ▼                                              │
│  ② 检视 Step 执行（持续监控）                        │
│       │  - 工作室观察目标 bot 回复                   │
│       │  - !pipeline_status 确认 Step 推进          │
│       ▼                                              │
│  ③ 超时升级（5 分钟无响应）                          │
│       │  - 准备 code block 上下文                    │
│       │  - TG 私聊项目负责人请求转发激活             │
│       ▼                                              │
│  ④ Step 完成确认                                     │
│       │  - !step_complete 执行                       │
│       │  - !pipeline_status 验证指针前移             │
│       ▼                                              │
│  ⑤ 循环 ②→④ 直到 Step 6 合并部署                   │
│       │                                              │
│       ▼                                              │
│  ⑥ 管线结束确认                                      │
│       │  - 归档 TODO.md                              │
│       │  - 关闭工作室                                │
│       │  - 通知项目负责人                            │
└─────────────────────────────────────────────────────┘
```

#### PM 监控检视 Checklist

**Step 推进后立即执行（30 秒内）：**

| # | 检查项 | 方法 | 通过标准 | 失败处理 |
|:-:|:-------|:----|:---------|:---------|
| C-01 | Step 指针前移 | `!pipeline_status` | 当前 Step 等于目标 Step 的下一项 | 若未前移 → 确认 output 参数有效 → 重试 `!step_complete` |
| C-02 | 工作室频道切换成功 | 查看各 bot 活跃频道 | 目标 bot 的活跃频道为 `ws:R56-dev` | `!pipeline_status` 确认后等待 10 秒再查 |
| C-03 | 目标 bot 回复确认 | 工作室消息流 | 目标 bot 在 1 分钟内输出工作开始消息 | 进入 5 分钟超时计时 |

**超时计时（Step 推进后）：**

```
Step 推进时间点 T0
    │
    ├── T0 + 30 秒 → C-01 检查 Step 指针
    ├── T0 + 1 分  → C-03 检查目标 bot 回复
    │
    ├── T0 + 3 分  → 如果目标 bot 未回复：
    │   └── 工作室发轻触提醒：「@接收人 Step x 等待中」*
    │
    ├── T0 + 5 分  → 如果目标 bot 仍未回复：⚠️ 触发升级流程
    │   └── 准备升级 code block → TG 私聊项目负责人
    │
    └── T0 + 10 分 → 如果项目负责人也未激活：🚨 暂停管线
        └── 报告「通信链路可能断裂，建议先修方向 A」
```

> *轻触提醒仅一次（T0+3min），避免过度打扰。如果 3 分钟时 bot 已回复 → 跳过。

#### 升级流程

**触发条件：** Step 推进 5 分钟后目标 bot 无响应

**Step 1：PM 准备升级 code block**

```markdown
@接收人 Step N — 任务描述
- 需求文档：https://github.com/datahome73/ws-bridge/blob/dev/docs/R56/R56-product-requirements.md
- 技术方案：https://github.com/datahome73/ws-bridge/blob/dev/docs/R56/R56-tech-plan.md
- 期望产出：{具体要求}
- 完成后 !step_complete stepN --output <sha>
```

**Step 2：TG 私聊项目负责人**

```
🔔 R56 Step N 超时 — 需要您激活
管线：R56（自动驾驶模式）
当前 Step：Step N（{角色名}）
目标 bot：@接待人
超时时间：5 分钟
原因：定向通知可能未送达（目标 bot 离线或频道未切换）

请转发以下 code block 到工作群激活：
---
@接收人 Step N — {任务简述}
- 需求文档：{URL}
- 技术方案：{URL}
- 期望产出：{要求}
- 完成后 !step_complete stepN --output <sha>
---
```

**Step 3：项目负责人转发到工作群**

- 项目负责人收到 PM TG 私聊后，将 code block 直接从 PM 消息中复制→粘贴到 ws-bridge 工作群
- 目标 bot 收到后自动开始工作（工作群消息走 `_broadcast` 全广播路径，不受定向通知限制）
- 项目负责人不需要额外操作（不需要跟进、不需要监督）

**Step 4：PM 确认激活生效**

- 转发后 30 秒：工作室查看目标 bot 是否开始工作
- 如果仍未生效 → 紧急升级：项目负责人直接 TG 私聊目标 bot 的操作者（人类干预）

#### 升级流程决策树

```
Step 推进后观察 5 分钟
    │
    ├── 目标 bot 在 5 分钟内回复 ✅
    │   └── 正常监控，不需升级
    │
    └── 目标 bot 5 分钟内无响应 ❌
        │
        ├── PM 准备升级 code block
        ├── TG 私聊项目负责人请求转发
        │
        ├── 转发后 30 秒目标 bot 响应 ✅
        │   └── 升级成功，继续监控
        │
        └── 转发后 30 秒目标 bot 仍无响应 ❌
            └── 紧急升级：项目负责人 TG 私聊目标 bot 操作者
```

#### 管线暂停条件

| 条件 | 操作 | 后续 |
|:-----|:-----|:-----|
| 连续 2 步需项目负责人激活 | PM 暂停管线（`!pipeline_mode manual`），在工作室内报告「通信链路可能断裂，建议先修方向 A」 | 等待方向 A 修复代码上线后恢复 |
| 同一 Step 3 次退回（R55 机制） | Step 自动升级给 PM 协调（已有 R55 的 `TASK_REJECT_CEILING=2` 机制） | PM 介入协调：是需求问题、方案问题还是沟通问题 |
| 诊断发现 P0 断裂点 | PM 暂停管线，通知项目负责人，调整优先级先修复 | 修复后再继续管线 |

#### 升级记录模板

每次升级完成后，PM 在工作室内输出升级记录：

```
📋 升级记录 — Step N → {角色名}
├─ 超时时间：5 分钟
├─ 升级方式：TG 私聊项目负责人 → 转发工作群
├─ 激活耗时：{X 秒 / X 分}
├─ 激活效果：✅ 目标 bot 响应工作 / ❌ 仍无响应
└─ 备注：{可选说明}
```

累计统计在管线结束后汇总到 Step 5 测试报告。

---

## 向后兼容性

| 场景 | 影响 | 说明 |
|:----|:----:|:-----|
| 旧消息类型 | ✅ 无影响 | `_send_to_agent` 返回值不变（True/False），新增参数有默认值 |
| 旧持久化数据 | ✅ 无影响 | write_chat_log 已有，只增加 ws_id 传入 |
| 非管线操作 | ✅ 无影响 | `_send_to_agent` 加默认参数 `ws_id=""`，不传则行为同 R55 |
| 多管线并发 | ✅ 无影响 | ws_id 通过参数显式传入，不依赖全局状态 |
| 方向 B 诊断 | ✅ 无影响 | 纯报告产出，不修改代码 |
| 方向 C 流程 | ✅ 无影响 | 纯流程设计，不修改代码 |

---

## 验收验证

### 方向 A（4 项）

| # | 验收项 | 验证方式 | 预期 |
|:-:|:-------|:--------|:-----|
| A-1 | 目标 bot 在线时定向送达 | 实测 `!step_complete` | 只有目标 bot 收到通知，其他 bot 无回声 |
| A-2 | 目标 bot 离线时回退广播 | 断线目标 bot → `!step_complete` | 工作室出现 `📢 [回退通知]` 广播 |
| A-3 | 离线 bot 重连后读到通知 | 重连后检查工作室消息 | chat_log 中有回退通知记录 |
| A-4 | admin 日志完整 | 检查 admin 频道 | Step 交接日志不因回退而缺失或重复 |

### 方向 B（3 项）

| # | 验收项 | 验证方式 | 预期 |
|:-:|:-------|:--------|:-----|
| B-1 | 7 段逐段标注 ✅/❌/❓ | 诊断报告存在 | 表格完整，无空白行 |
| B-2 | 每个 ❌ 附根因 + 修复建议 | 报告逐项说明 | 对每个断裂点有代码级或配置级的分析 |
| B-3 | 诊断通过真实 WS 直连执行 | 报告附验证方法和原始输出 | 非模拟/非本地 |

### 方向 C（4 项）

| # | 验收项 | 验证方式 | 预期 |
|:-:|:-------|:--------|:-----|
| C-1 | PM 能在 Step 完成后 1 分钟内检视 | 实操验证 | !pipeline_status + 工作室观察 < 60s |
| C-2 | 5 分钟无响应 → 自动准备 code block | 模拟超时 | code block 内容完整，含 URL 和产出要求 |
| C-3 | 一轮管线完整推进 | 完整跑 R56 六步 | Step 6 合并部署完成 |
| C-4 | 项目负责人激活次数减少 | 统计对比 | 比 R55 的「每步必发」降到「偶尔兜底」 |

---

## 开放问题

| # | 问题 | 决策 | 说明 |
|:-:|:-----|:----|:-----|
| Q1 | `_broadcast_to_members` 是否需要写 admin 日志？ | ❌ 不写 | admin 日志由上层 `_cmd_step_complete` / `_cmd_step_reject` 管理，回退广播不应双写 |
| Q2 | 方向 B 诊断工具是否需要编写 Python 脚本？ | ⏳ 待定 | 如果纯手动 WS 直连验证困难，可以写一个 `diagnose_comm.py` 自动检视各段 |
| Q3 | 方向 C 流程中 3 分钟轻触提醒是否由 PM 手动发？ | 🧐 PM 手动 | 自动化轻触提醒需改动 handler，超出本轮范围。PM 手动观察和提醒 |

---

> **审核记录：**
> - v1.0 提交方向审查：2026-06-29
> - 方向审查结论：⏳ 待审查
