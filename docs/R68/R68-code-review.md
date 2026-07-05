# R68 代码审查报告 — Bot 私有收件箱通道 📥

> **审查人：** 🔍 小周
> **审查对象：** commit `6dc3400`（4 文件，+182/-58）
> **已知修复（未部署）：** `89ac235`（step_handoff 回退广播修复）
> **审查基线：** `origin/dev`（R67 最终合并 `ed23e90`）
> **需求文档：** `docs/R68/R68-product-requirements.md` v1.0 ✅
> **技术方案：** `docs/R68/R68-tech-plan.md` v1.0 ✅
> **WORK_PLAN：** `docs/R68/WORK_PLAN.md` v1.0 ✅
> **日期：** 2026-07-05

---

## 0. 审查结论

**🟢 通过 → 可进入 Step 5（测试）**

无 🔴 Critical 级别问题。发现 2 项 🟡 Warning（非阻塞，关联已知修复）和 1 项 💡 Suggestion。

---

## 1. 文件级语法验证

| 文件 | 状态 |
|:-----|:----:|
| `shared/protocol.py` | ✅ `compile() OK` |
| `server/persistence.py` | ✅ `compile() OK` |
| `server/handler.py` | ✅ `compile() OK` |
| `server/auth.py` | ✅ `compile() OK` |

---

## 2. 需求→方案→代码追溯矩阵

| 需求验收 | 技术方案项 | 实现位置（6dc3400） | 状态 |
|:---------|:-----------|:--------------------|:----:|
| ✅-1: INBOX_CHANNEL_PREFIX 常量 | A1-① `protocol.py` L165 后 | `shared/protocol.py:L167-168` | ✅ |
| ✅-2: agent 注册后自动收件箱 | A1-③ `auth.py` approve() | `server/auth.py:L47-48` | ✅ |
| ✅-3: 收件箱消息仅投递目标 agent | A2 inbox intercept | `server/handler.py:L4084-4132` 单播 `_connections.get(owner_id)` | ✅ |
| ✅-4: 权限 — 仅 admin 可写 | A2 `sender_role != "admin"` | `server/handler.py:L4092-4095` | ✅ |
| ✅-5: admin 可向任意收件箱发消息 | A2 权限 pass-through | admin 角色通过权限检查 → 正常投递 | ✅ |
| ✅-6: handle_broadcast 新增收件箱路由 | A2 插入 _admin 拦截后 | `server/handler.py:L4084` 紧接 R35 _admin return 后 | ✅ |
| ✅-7: 收件箱消息持久化到日志 | A2 `write_chat_log(channel=channel)` | `server/handler.py:L4097` | ✅ |
| ✅-8: 收件箱消息含时间戳 | A2 payload 含 `ts: time.time()` | `server/handler.py:L4100-4104` | ✅ |
| ✅-9: agent 不可向收件箱回复写 | A2 `sender_role != "admin"` 拒绝 | 任何非 admin 角色均被拦截（含 agent 本人） | ✅ |
| ✅-10: !step_complete 后任务消息发收件箱 | A3 `_send_inbox_task()` | `server/handler.py:L2574-2583` | ✅ |
| ✅-11: 工作室同时收到轻量通知 | A3 `_send_inbox_task()` workspace notify | `server/handler.py:L2319-2340` | ✅ |

**追溯率：** 11/11 项 ✅ 100%

---

## 3. 6 项审查重点逐项验证

### 3.1 ✅ `_inbox` 路由权限：仅 admin 可写，agent 不可写

**实现：** `handler.py:L4092-4095`

```python
if sender_role != "admin":
    await _send(ws, {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"})
    return
```

**验证矩阵：**

| 场景 | 期望 | 代码路径 | 状态 |
|:-----|:----:|:---------|:----:|
| admin → `_inbox:userA` | ✅ 投递 | 通过 `sender_role != "admin"` 检查 → 投递 | ✅ |
| member → `_inbox:userA` | ❌ 拒绝 | `sender_role="member"` → 拦截 return | ✅ |
| userA → `_inbox:userA`（本人） | ❌ 拒绝 | `sender_role="member"` → 拦截 return | ✅ |
| admin → `_inbox:`（空 owner） | ❌ 拒绝 | `resolve_inbox_owner` 返回 None → error return | ✅ |

### 3.2 ✅ 收件箱消息不广播到工作室

**验证：** `handler.py:L4084-4132` 是 `handle_broadcast()` 内的独立 `if` 分支，以 `return` 结尾。收件箱消息：
1. 通过 `write_chat_log(channel=channel)` 持久化到收件箱日志文件
2. 仅向 `_connections.get(owner_id, set())` 发送（单播）
3. `return` 阻止 fall-through 到 workspace resolution（L4135 `Channel resolution`）

✅ 现有 workspace broadcast 路径完全不受影响。

### 3.3 ✅ `handle_broadcast` 新增分支在 `_admin` 拦截后

**实际插入点验证：**

| 行号 | 内容 |
|:----:|:------|
| L4064-4082 | `# ── R35: _admin channel intercept ──` → 处理 _admin → `return` |
| L4084 | `# ── R68 A2: Inbox channel intercept ──` ← **此处插入** |
| L4132 | inbox 处理结束 → `return` |
| L4135 | `# ── Channel resolution (fall back to lobby...)` |

- ✅ 在 `_admin` 拦截之后
- ✅ 在 channel resolution 之前（避免 `_inbox:` 前缀被当作未知通道 fallback 到 lobby）
- ✅ 与 `__registration__` 跳过逻辑同模式

### 3.4 ✅ step_complete/handoff 改造不破坏管线

**`_cmd_step_complete()`（L2564-2590）：**

| 原逻辑（R58 A2） | 新逻辑（R68 A3） | 状态 |
|:-----------------|:-----------------|:----:|
| 构建 `mention_msg` | 删除 — 由 `_send_inbox_task` 接管 | ✅ |
| `_persist_broadcast` 全量广播 | 删除 — 改用收件箱单播 | ✅ |
| rollcall 点名 + 30s ACK timer | **保留** ✅ | ✅ |
| `_send_to_agent` 定向通知 | **保留** ✅ | ✅ |
| backup switch（primary_offline） | **保留** ✅ | ✅ |

**`_cmd_step_handoff()`（L3187-3205）：**

| 检查项 | 状态 |
|:-------|:----:|
| 保留原有 rollcall 广播（`_cmd_rollcall_next`） | ✅ |
| 新增 inbox delivery（非替代，平行添加） | ✅ |
| 不影响后续 `_cmd_task_create` | ✅ (L3220) |
| `step_config` 变量在作用域内（L3124 `_get_step_config(round_name)`） | ✅ |

### 3.5 ✅ Scope 合规

| 文件 | 本轮改动 | Scope 边界 |
|:-----|:---------|:-----------|
| `shared/protocol.py` | +`INBOX_CHANNEL_PREFIX` 常量 1 行 | ✅ 仅新增常量 |
| `server/persistence.py` | +3 个收件箱工具函数（末尾追加） | ✅ 纯工具函数 |
| `server/handler.py` | +inbox intercept + `_send_inbox_task` + step handoff 改造 | ✅ 路由/管线 |
| `server/auth.py` | +1 行收件箱注册调用 | ✅ 审批后钩子 |
| `server/web_viewer.py` | **不改** | ✅ |
| `server/templates.py` | **不改** | ✅ |
| `server/workspace.py` | **不改** | ✅ |

### 3.6 ✅ 脱敏检查

| 检查项 | 结果 |
|:-------|:----:|
| 硬编码内部 URL/端口 | ✅ 无（使用 `raw.githubusercontent.com`） |
| 内部角色名泄漏 | ✅ 无（使用 `"admin"`/`"system"`/`pm_name`） |
| 硬编码 agent ID | ✅ 无（使用 `target_agent_id` 参数） |
| 敏感信息（token/password/secret） | ✅ 零匹配 |
| TODO/FIXME/HACK/print 残留 | ✅ 零匹配 |
| 日志截断长 ID（`owner_id[:12]`） | ✅ 符合现有截断模式 |

---

## 4. ⚠️ 发现项

### 🟡 W-1: `_send_inbox_task()` 参数 `step_config: dict` 未使用

**位置：** `server/handler.py:L2244`

```python
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,   # ← 定义但未使用
    output_ref: str,
    workspace_id: str,
    pm_name: str,
) -> None:
```

函数体内部通过 `_PIPELINE_CONFIG.get(round_name, {})` 获取配置（`_pconfig`），`step_config` 参数从未被引用。

**影响：** 无功能影响。但属于死参数——两个调用者（`_cmd_step_complete` L2578、`_cmd_step_handoff` L3200）都传入 `step_config`，值被静默丢弃。

**建议：** 从函数签名中移除 `step_config` 参数，同时更新两处调用。或重构为函数体内实际使用它。

### 🟡 W-2: `_cmd_step_handoff` 中 `'ac_mod' in dir()` guard + 空 `_h_primary_agents` 无回退（已知 bug，已修复 89ac235）

**位置：** `server/handler.py:L3188-3204`（6dc3400）

```python
_h_cards = ac_mod.get_all_cards() if 'ac_mod' in dir() else {}
_h_primary_role = step_config.get(next_step, {}).get("primary")
_h_primary_agents = (
    _find_agents_by_role(_h_primary_role, _h_member_ids, _h_cards)
    if _h_cards and _h_primary_role else []
)
if _h_primary_agents:
    await _send_inbox_task(...)
# ← 无 else 分支！_h_primary_agents 为空时静默无操作
```

**问题：**
1. `'ac_mod' in dir()` guard 属于防御性编程，但 R67 已将 `ac_mod` 作为顶层 import（`from . import agent_card as ac_mod`），此 guard 不需要且可能掩盖 import 错误
2. `_h_primary_agents` 为空时（找不到对应角色的 agent card），**无 fallback 行为**——任务消息不发、工作室无通知、管线静默卡住

**修复状态：** `89ac235` 已推 `origin/dev`，修复方案：
- 移除 `'ac_mod' in dir()` guard（直接 `ac_mod.get_all_cards()`）
- 新增 `else` 分支：`_h_primary_agents` 为空时执行工作室全量广播回退（含 `@mention` + WORK_PLAN URL + 上一步产出）

**建议：** 两个 🟡 问题均在下一次 deploy 时通过 89ac235 一起修复。但 `_send_inbox_task` 的死参数（W-1）在 89ac235 中未涉及，建议后续修复。

---

## 5. 💡 建议（非阻塞）

### 💡 S-1: 收件箱 payload JSON 缺少 `agent_id` 字段

当前 `_send_inbox_task()` 的 `inbox_payload`（L2310-2314）缺少 `agent_id`：

```python
inbox_payload = json.dumps({
    "type": "broadcast", "channel": inbox_ch,
    "from_name": pm_name, "from": pm_name,
    "content": inbox_msg, "ts": time.time(),
})
```

而 `handle_broadcast()` 中的 inbox intercept（L4099-4104）payload 包含了 `agent_id` 和 `from_agent`：

```python
broadcast = json.dumps({
    "type": "broadcast", "channel": channel,
    "from_name": sender_name, "agent_id": sender_id,
    "from": sender_name, "from_agent": sender_id,
    "content": content, "ts": time.time(),
})
```

**影响：** bot 通过 `_send_inbox_task` 收到的消息缺少 `agent_id`/`from_agent` 字段。现有 bot 端可能不依赖此字段（仅读 `content`），但一致性上建议补上发件人信息。

---

## 6. 其他检查

| 检查项 | 状态 |
|:-------|:----:|
| 🔄 双入口同步（handler.py ↔ __main__.py） | ✅ inbox intercept 在 handler.py handle_broadcast() 中（独立于消息路由），__main__.py 的 ws_handler() 也在 handle_broadcast() 路径中，无需同步 |
| 📝 消息文案合规 | ✅ 收件箱/通知消息使用中性措辞，无预期外 emoji |
| 🔗 URL 引用使用公开地址 | ✅ `raw.githubusercontent.com` |
| 🏷️ R 标签准确性 | ✅ 所有新标签为 `R68` |
| 📤 `write_chat_log` + `save_message` 双写 | ✅ `_send_inbox_task` 中两者都调用 |
| 🗑️ 旧广播代码完全移除（无残留） | ✅ `_cmd_step_complete` 中 R58 A2 广播和点名广播被完整替换为 `_send_inbox_task` |

---

## 7. 总结

| 类别 | 结果 |
|:-----|:----:|
| 🔴 Critical | 0 项 |
| 🟡 Warning | 2 项（W-1 死参数, W-2 已知 bug 已修复） |
| 💡 Suggestion | 1 项（payload 字段补充） |
| ✅ Pass | 11/11 验收项全部通过 |

**结论：** 🟢 **审查通过** — 无阻塞性问题。W-1（死参数）和 W-2（step_handoff 回退）通过 89ac235 和后续清理解决。可进入 Step 5 测试。
