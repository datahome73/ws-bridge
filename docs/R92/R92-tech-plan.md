# R92 技术方案 — AutoRouter 最终修复 📡

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于需求文档：** `docs/R92/R92-product-requirements.md` v1.0
> **改动文件：** `server/handler.py`（~+14 行，仅 `_cmd_pipeline_start` 末尾）

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ `_cmd_pipeline_start` return 前增加 _admin 广播](#️-cmd_pipeline_start-return-前增加-_admin-广播)
3. [为什么 _send + _broadcast 都要保留](#3-为什么-_send--_broadcast-都要保留)
4. [改动对照表](#4-改动对照表)
5. [兼容性分析](#5-兼容性分析)
6. [风险与缓解](#6-风险与缓解)
7. [验收清单](#7-验收清单)

---

## 1. 改动总览

### 1.1 根因

AutoRouter 经过 R88→R91 五轮迭代，功能已完整，但 `!pipeline_start` 的响应只通过 `_send(ws, msg)` 回复发送者单条 WS 连接。AutoRouter 虽然订阅了 `_admin` 频道，但 **收不到 `_send` 回复的消息** — 需要 `_broadcast_to_channel` 推送才能收到。

```python
# handler.py _send_cmd_response() L531-543 — 只回复发送者
async def _send_cmd_response(ws, sender_id, from_name, content, channel):
    msg = {"type": "broadcast", "channel": channel, ...}
    await _send(ws, msg)        # ← 只发回 sender 的单条 WS
    ms.save_message(...)        # ← 仅持久化，不广播给其他订阅者
```

### 1.2 改动

| # | 改动 | 文件 | 净增行 | 函数 |
|:-:|:-----|:-----|:------:|:-----|
| 🅰️ | `_cmd_pipeline_start()` return 前增加 `_broadcast_to_channel(ADMIN_CHANNEL, ...)` | `handler.py` | ~+14 | `_cmd_pipeline_start()` |
| **合计** | | **1 文件** | **~+14 行** | **1 函数** |

---

## 2. 🅰️ `_cmd_pipeline_start` return 前增加 _admin 广播

### 2.1 改动位置

**文件：** `server/handler.py`
**函数：** `_cmd_pipeline_start()` — 末尾，return 语句之前
**精确行号：** L2858-2879（当前 dev 已实现）

### 2.2 代码

```python
    # ── R92: 广播管线启动通知到 _admin（让 AutoRouter 等监听者收到） ──
    try:
        await _broadcast_to_channel(p.ADMIN_CHANNEL, {
            "type": "broadcast",
            "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": (
                f"🚀 **{round_name} 管线已启动**\n"
                f"  Step: {start_step} → {target_role}\n"
                f"  工作室: {ws_id}\n"
                f"  {create_result}\n"
                f"  {rollcall_result}\n"
                f"  {task_result}"
            ),
            "ts": time.time(),
        })
        logger.info("R92: 已广播 %s 管线启动通知到 _admin", round_name)
    except Exception as e:
        logger.warning("R92: _admin 广播失败: %s", e)

    return (
        f"🚀 **{round_name} 管线已启动**\n"
        f"  Step: {start_step} → {target_role}\n"
        f"  工作室: {ws_id}\n"
        f"  {create_result}\n"
        f"  {rollcall_result}\n"
        f"  {task_result}"
    )
```

### 2.3 Payload 字段详解

| 字段 | 值 | 说明 |
|:-----|:----|:------|
| `type` | `"broadcast"` | 消息类型，与 _send_cmd_response 一致 |
| `channel` | `p.ADMIN_CHANNEL` | 目标频道 = `_admin` |
| `from_name` | `"系统"` | 发送者显示名 |
| `from_agent` | `SYSTEM_AGENT_ID` = `"_system"` | 发送者 ID |
| `content` | `🚀 **R92 管线已启动**\n  Step: step2 → architect\n  ...` | **AutoRouter 匹配的关键** — 需包含 `管线已启动` + `R{NN}` |
| `ts` | `time.time()` | 时间戳 |

### 2.4 AutoRouter 侧的信号匹配

AutoRouter 现有的 `_handle_message()`（R90 🅰️ 已实现）无需任何修改：

```python
# auto_router.py _handle_message()
is_admin = channel == "_admin"

# 只处理 PM inbox 或 _admin 的消息
if not is_pm_inbox and not is_admin:
    return

# ═══ 信号 1: 管线就绪 ═══
if "管线已启动" in content or "工作区已就绪" in content:
    round_name = self._extract_round(content)
    if round_name:
        await self._on_pipeline_ready(round_name)
    return
```

**匹配路径：** 广播 content 含 `🚀 **R92 管线已启动**` → `"管线已启动" in content` ✅ → `_extract_round` 用正则 `R\d{2,3}` 提取 `R92` ✅ → `_on_pipeline_ready("R92")` ✅

### 2.5 try/except 设计

| 异常场景 | 处理方式 | 对主流程影响 |
|:---------|:---------|:------------|
| `_broadcast_to_channel` 内部异常 | `logger.warning("R92: _admin 广播失败: %s", e)` | ❌ 不阻断，return 正常执行 |
| `p.ADMIN_CHANNEL` 不存在 | AttributeError → 被 except 捕获 | ❌ 不阻断 |
| broadcast 过程中 WS 连接断开 | 内部异常 → 被 except 捕获 | ❌ 不阻断 |

**原则：** broadcast 是辅助通知，不是主流程的必要步骤。失败不应阻止管线启动的返回。

---

## 3. 为什么 _send + _broadcast 都要保留

### 3.1 两者不可互相替代

| 对比维度 | `_send(ws, msg)`（原有） | `_broadcast_to_channel(ch, payload)`（R92 新增） |
|:---------|:------------------------|:-----------------------------------------------|
| 接收范围 | **仅发送者**的单条 WS 连接 | **所有订阅 _admin 频道的连接**（包括 AutoRouter） |
| 用途 | 命令发起者收到即时的、个人的回复 | 通知所有监听者管线已启动 |
| 是否持久化 | 否（`_send_cmd_response` 会 `ms.save_message`） | **是**（`_broadcast_to_channel` 内部调用 `ms.save_message`） |
| 是否写入 chat log | 是（`_send_cmd_response` 会写） | **是**（`_broadcast_to_channel` 内部调用 `write_chat_log`） |

### 3.2 为什么两个都要

```
原始流程（R91 及之前）:
  小谷发 !pipeline_start
    ↓
  _send_cmd_response(ws, ...) → _send(ws, msg)      ← 小谷收到
    ↓
  (无广播)                                            ← AutoRouter 收不到 ❌

R92 修复后:
  小谷发 !pipeline_start
    ↓
  _send_cmd_response(ws, ...) → _send(ws, msg)      ← 小谷收到 ✅
    ↓
  _broadcast_to_channel(ADMIN_CHANNEL, ...)          ← AutoRouter 收到 ✅
    ↓
  AutoRouter._handle_message() → _on_pipeline_ready()
```

- **保留 `_send`**：小谷（发送者）需要收到回复确认命令被执行，这是命令-响应模型的基石
- **新增 `_broadcast`**：AutoRouter 及其他 _admin 订阅者需要被动接收状态变更通知

### 3.3 重复消息风险

小谷作为发送者会收到两条消息：
1. `_send` 回复（原有，直接回复其 WS 连接）
2. `_broadcast` 推送（新增，通过 _admin 频道广播）

但这两条消息的 `id` 不同，`_mark_seen` 不会去重。不过：
- 对**发送者**：这是可接受的 — 两条都是同样的管线启动确认
- 对 **AutoRouter**：只收到 `_broadcast` 的那条（`_send` 不广播到它的连接）
- 对**原始发送者**：如果确实觉得冗余，可后续在 `_send_cmd_response` 层面去重（非本轮范围）

---

## 4. 改动对照表

### 4.1 handler.py 改动

| # | 位置 | 行号（当前 dev） | 操作 | 说明 |
|:-:|:-----|:--------------:|:----|:------|
| 1 | `_cmd_pipeline_start()` 末尾 | L2858-2879 | ➕ 新增 ~14 行 | try/except 包裹的 `_broadcast_to_channel(p.ADMIN_CHANNEL, {...})` |
| **合计** | | | **~+14 行净增** | |

### 4.2 状态

> ✅ **注意：** R92 broadcast 代码已在 dev 上实现（commit `b21103a` feat(R90) 中附带）。本文档为技术方案文档追写。

---

## 5. 兼容性分析

### 5.1 向后兼容矩阵

| 场景 | 旧行为 | R92 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| 不发 `!pipeline_start` | — | 新增代码不执行 | ✅ 零影响 |
| `!pipeline_start` 正常 | 小谷收到回复 | 小谷 + AutoRouter 都收到 | ✅ 增强 |
| broadcast 失败 | N/A | try/except 包裹，不阻断 return | ✅ 安全 |
| 旧 AutoRouter（无 _admin 监听） | 不处理 | 仍不处理，无影响 | ✅ 兼容 |
| 旧 handler.py（无 broadcast） | 无广播 | N/A | ✅ 升级到新版即可 |
| 手动 inbox 协调 | 正常工作 | 不受影响 | ✅ |

### 5.2 scope 边界

| 不改 | 原因 |
|:-----|:------|
| `auto_router.py` | `_handle_message` 已有 `_admin` 监听，payload 格式匹配 ✅ |
| `_send_cmd_response()` | 保持原有命令-响应机制不变 |
| 其他 `!` 命令 | broadcast 仅在 `_cmd_pipeline_start` 内新增，不影响其他命令 |

---

## 6. 风险与缓解

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| R1 | `_broadcast_to_channel` 抛异常阻断 return | 🟢 低 | try/except `Exception` 包裹，`logger.warning` 仅警告 |
| R2 | 发送者收到重复消息 | 🟢 低 | 两条消息 ID 不同，但内容一致。发送者可忽略重复。非用户可见 bug |
| R3 | `ADMIN_CHANNEL` 路由拥堵 | 🟢 低 | 管线启动是低频操作（每小时最多几次），`_broadcast` 一次仅 ~200 字节 |
| R4 | 这是「最后一次修复」吗？ | 🟡 中 | 全链路已无已知 gap。但如果 AutoRouter 在 `_fetch_topology` 或 `_dispatch_step` 仍有问题，需后续排查 |

---

## 7. 验收清单

### 🅰️ Broadcast 新增（6 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅰️-1 | `_cmd_pipeline_start` return 前有 `_broadcast_to_channel` | 代码审查 L2858-2879 | ✅ 存在 |
| 🅰️-2 | 广播 payload 的 `content` 含 `🚀 **{round_name} 管线已启动**` | 字符串格式检查 | 匹配 AutoRouter 信号 |
| 🅰️-3 | 广播目标频道是 `p.ADMIN_CHANNEL` | payload channel 字段 | `"_admin"` |
| 🅰️-4 | broadcast 失败不阻断 return | try/except 包裹 + 仅 warn | return 正常执行 |
| 🅰️-5 | 原有 `_send_cmd_response` 回复不变 | 检查 _send 调用 | 发送者仍收到完整回复 |
| 🅰️-6 | payload 完整包含 `from_name`/`from_agent`/`ts` | 代码审查 | 字段齐全 |

### 🅲 全自动管线验证（3 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅲-1 | `!pipeline_start` → AutoRouter 收到并派活 Step 2 | 小开 inbox 检查 | Step 2 任务送达 |
| 🅲-2 | Step 2→3 自动接力 | 小开发 ✅ 完成 → 爱泰收到 | 自动接力 |
| 🅲-3 | 全线闭环 | PM 收件箱收到 🏁 全部完成 | 6 Step 全自动 |

---

*本文档由 🏗️ 架构师编写。R92 broadcast 代码已于 dev 实现（`b21103a`），本文档为技术方案追写。*
