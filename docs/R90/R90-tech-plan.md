# R90 技术方案 — AutoRouter 坑位修补 🔧

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于需求文档：** `docs/R90/R90-product-requirements.md` v1.0
> **基于工作计划：** `docs/R90/WORK_PLAN.md` v1.0
> **改动文件：** `server/auto_router.py`（~+40 行） · `server/handler.py`（~+15 行）

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ AutoRouter 监听 _admin 频道](#2-️-autorouter-监听-_admin-频道)
3. [🅱️ handler.py 工作区创建失败通知 PM](#3-️-handlerpy-工作区创建失败通知-pm)
4. [🅲 AR_STEP_TIMEOUT 环境变量 + <=0 守卫](#4-️-ar_step_timeout-环境变量--0-守卫)
5. [改动对照表](#5-改动对照表)
6. [兼容性分析](#6-兼容性分析)
7. [风险与缓解](#7-风险与缓解)
8. [验收清单](#8-验收清单)

---

## 1. 改动总览

### 1.1 三处改动

| # | 改动 | 文件 | 净增行 | 修改函数数 |
|:-:|:-----|:-----|:------:|:----------:|
| 🅰️ | `_handle_message()` 增加 `_admin` 频道信号检测 | `auto_router.py` | ~+20 | 1 |
| 🅱️ | `_cmd_pipeline_start()` 末尾工作区创建失败 → PM 收件箱通知 | `handler.py` | ~+15 | 1 |
| 🅲 | `AR_STEP_TIMEOUT` 环境变量 + `<=0` 守卫 | `auto_router.py` | ~+20 | 3（含类常量） |
| **合计** | | **2 文件** | **~+55 行净增** | **5 函数** |

### 1.2 文件与函数全景

```
server/auto_router.py
│
├── 类常量区                        ← 🅲: _STEP_DEFAULT_TIMEOUT 改为 os.environ
│     _STEP_DEFAULT_TIMEOUT = int(os.environ.get("AR_STEP_TIMEOUT", "7200"))
│     _STEP_TIMEOUT_ENABLED: bool   = _STEP_DEFAULT_TIMEOUT > 0
│
├── _handle_message()               ← 🅰️: channel 过滤改为 is_pm_inbox OR is_admin
│     if not is_pm_inbox and not is_admin:
│         return
│
├── _timeout_check_loop()           ← 🅲: 增加 _STEP_TIMEOUT_ENABLED 守卫
│     if not self._STEP_TIMEOUT_ENABLED:
│         logger.info(...超时检测已禁用)
│         return
│
├── _check_step_timeouts()          ← 🅲: 增加 _STEP_TIMEOUT_ENABLED 守卫
│     if not self._STEP_TIMEOUT_ENABLED:
│         return
│
├── __init__()                      ← 🅲: 增加超时状态日志
│     logger.info("[AR] 超时=%ds (%s)", ...)
│
└── _connect_and_listen()           ← 🅲: create_task 也受 _STEP_TIMEOUT_ENABLED 控制

server/handler.py
│
├── _cmd_pipeline_start() L2820     ← 🅱️: return 前检测 create_result 含 ❌
│     if "❌" in create_result:
│         await _broadcast_to_channel(pm_inbox, ...)
│     return (...)
```

---

## 2. 🅰️ AutoRouter 监听 _admin 频道

### 2.1 问题

当前 `_handle_message()`（auto_router.py L158-185）只监听 PM 收件箱：

```python
# 当前: 仅监听 PM 收件箱
if self._pm_inbox_channel and channel != self._pm_inbox_channel:
    return
```

但 `!pipeline_start` 的服务端响应消息走 `_admin` 频道（handler.py 返回给命令发起频道），不经 R87 中继。结果：管线已启动，AutoRouter 却收不到信号。

### 2.2 设计方案

**方案：** 将 _admin 频道加入白名单，与 PM inbox 并列。

```python
async def _handle_message(self, msg: dict) -> None:
    """消息入口 — 监听 PM 收件箱 + _admin 频道。"""
    channel = msg.get("channel", "")
    content = (msg.get("content") or "").strip()
    msg_id = msg.get("id", "")

    # ── 去重 ──
    if self._mark_seen(msg_id):
        return

    # ── 🅰️ R90: 通道过滤改为白名单模式 ──
    is_pm_inbox = self._pm_inbox_channel and channel == self._pm_inbox_channel
    is_admin = channel == "_admin"

    if not is_pm_inbox and not is_admin:
        return  # 只处理 PM inbox 或 _admin 的消息

    # ═══ 信号 1: 管线就绪（PM inbox + _admin 均可） ═══
    if "管线已启动" in content or "工作区已就绪" in content:
        round_name = self._extract_round(content)
        if round_name:
            await self._on_pipeline_ready(round_name)
        return

    # ═══ PM inbox 专有: Step 完成信号 ═══
    if is_pm_inbox:
        if content.startswith("✅ ") and "任务完成" in content:
            await self._on_step_complete(content)
            return
        if content.startswith("✅ 完成") or "✅ 完成，已推" in content:
            await self._on_step_complete(content)
            return

    # _admin 专有: 其他消息忽略（不干扰 admin 频道正常通信）
    if is_admin:
        return  # 只响应管线启动信号，其他不处理
```

### 2.3 信号匹配精确度

| 通道 | 信号内容 | AutoRouter 响应 | 原因 |
|:-----|:---------|:---------------|:------|
| `_admin` | `🚀 **R90 管线已启动**` | ✅ `_on_pipeline_ready("R90")` | 管线启动信号 |
| `_admin` | `🚀 **R88 管线已启动**\n  ...` | ✅ 同上 | 多行也匹配 |
| `_admin` | 普通聊天消息 | ❌ 忽略 | 不干扰 admin 频道 |
| PM inbox | `✅ architect 任务完成: ✅ 完成，已推 dev: abc1234` | ✅ `_on_step_complete(content)` | Step 完成 |
| PM inbox | `ACK ✅ ...` | ❌ 忽略 | ACK 通知不处理 |

### 2.4 去重

`_mark_seen(msg_id)` 已覆盖所有频道，同一管线启动消息不会重复处理（PM inbox 和 _admin 各有一条时，第二条被去重）。

---

## 3. 🅱️ handler.py 工作区创建失败通知 PM

### 3.1 问题

`_cmd_pipeline_start()` 中 `create_result` 可能包含 `❌`（表示工作区创建失败），但该信息仅出现在返回文本中（发回 `_admin`）。PM 收件箱收不到通知，AutoRouter 不知晓管线存在。

### 3.2 改动位置

**文件：** `server/handler.py`
**函数：** `_cmd_pipeline_start()`（L2500）
**插入点：** 在 `return (...)` 语句之前（L2815-2828 之间），即 `# ── R81 B2: 成员不足检测 + inbox 邀请 ──` 代码块之后。

### 3.3 设计方案

```python
    # ── R90 🅱️: 工作区创建失败通知 PM 收件箱 ──
    pm_agent_id = getattr(config, "PIPELINE_PM_AGENT_ID", "")
    if pm_agent_id and "❌" in create_result:
        pm_inbox = f"_inbox:{pm_agent_id}"
        try:
            await _broadcast_to_channel(pm_inbox, {
                "type": "broadcast",
                "channel": pm_inbox,
                "from_name": "系统",
                "from_agent": SYSTEM_AGENT_ID,
                "content": (
                    f"⚠️ {round_name} 管线已启动但工作区创建失败。\n"
                    f"create_result: {create_result}\n"
                    f"AutoRouter 可能无法自动接力，请检查后手动启动。"
                ),
                "ts": time.time(),
            })
            logger.info(
                "R90 🅱️: 已通知 PM 工作区创建失败 (%s)", round_name
            )
        except Exception as e:
            logger.warning("R90 🅱️: PM 通知发送失败: %s", e)

    return (
        f"🚀 **{round_name} 管线已启动**\n"
        f"  Step: {start_step} → {target_role}\n"
        f"  工作室: {ws_id}\n"
        f"  {create_result}\n"
        f"  {rollcall_result}\n"
        f"  {task_result}"
    )
```

### 3.4 代码对比

```diff
+    # ── R90 🅱️: 工作区创建失败通知 PM 收件箱 ──
+    pm_agent_id = getattr(config, "PIPELINE_PM_AGENT_ID", "")
+    if pm_agent_id and "❌" in create_result:
+        pm_inbox = f"_inbox:{pm_agent_id}"
+        try:
+            await _broadcast_to_channel(pm_inbox, {
+                "type": "broadcast",
+                "channel": pm_inbox,
+                "from_name": "系统",
+                "from_agent": SYSTEM_AGENT_ID,
+                "content": (
+                    f"⚠️ {round_name} 管线已启动但工作区创建失败。\n"
+                    f"create_result: {create_result}\n"
+                    f"AutoRouter 可能无法自动接力，请检查后手动启动。"
+                ),
+                "ts": time.time(),
+            })
+        except Exception as e:
+            logger.warning("R90 🅱️: PM 通知发送失败: %s", e)
+
     return (
```

### 3.5 `create_result` 的取值场景

| 位置 | create_result 值 | 含 ❌? | 通知 PM? |
|:-----|:-----------------|:------:|:--------:|
| L2668 | `✅ 附着到已有工作室 {ws_id[:16]}…` | ❌ | ❌ |
| L2672 | `✅ 附着到已有工作室「...」({ws_id[:16]}…)` | ❌ | ❌ |
| L2674 | `⚠️ 指定工作室 {ws_id[:16]}… 不存在，仍以该 ID 启动管线` | ❌ | ❌ |
| L2688 | `✅ 复用现有工作室「...」({ws_id[:16]}…)` | ❌ | ❌ |
| L2699 | `❌ 创建失败：...`（来自 `_cmd_create_workspace`） | ✅ | ✅ 通知 PM |
| L693 | `❌ 创建失败：{ws_name} 可能已存在...` | ✅ | ✅ 通知 PM |

---

## 4. 🅲 AR_STEP_TIMEOUT 环境变量 + <=0 守卫

### 4.1 问题

当前 `_STEP_DEFAULT_TIMEOUT = 7200` 是硬编码类常量。需求要求：
1. 从环境变量 `AR_STEP_TIMEOUT` 读取
2. 设 `<=0` 时完全禁用超时检测（R89 审查 🟡 条件）

### 4.2 改动细节

#### 4.2.1 类常量区（auto_router.py L16-20）

```python
# ── R89 🅱️: Step 超时检测 ──
_TIMEOUT_CHECK_INTERVAL = 300   # 5 分钟检查一次
# R90 🅲: 从环境变量读取，支持 <=0 禁用
_STEP_DEFAULT_TIMEOUT = int(os.environ.get("AR_STEP_TIMEOUT", "7200"))
_STEP_TIMEOUT_ENABLED  = _STEP_DEFAULT_TIMEOUT > 0
```

#### 4.2.2 `__init__()` 增加日志（L65 附近，常量区后的构造函数内）

```python
# ── R90 🅲: 超时状态日志 ──
logger.info(
    "[AR] 超时=%ds (%s)",
    self._STEP_DEFAULT_TIMEOUT,
    "启用" if self._STEP_TIMEOUT_ENABLED else "禁用",
)
```

#### 4.2.3 `_timeout_check_loop()` 增加守卫（当前 L338）

```python
async def _timeout_check_loop(self) -> None:
    """R89 🅱️: Step 超时检测后台循环。"""
    # ── R90 🅲: <=0 禁用守卫 ──
    if not self._STEP_TIMEOUT_ENABLED:
        logger.info("[AR] ⏰ 超时检测已禁用 (AR_STEP_TIMEOUT=%d)",
                     self._STEP_DEFAULT_TIMEOUT)
        return  # 不启动定时器
    while self._running:
        try:
            await self._check_step_timeouts()
        except Exception as e:
            logger.error("[AR] ⏰ 超时检查异常: %s", e)
        await asyncio.sleep(self._TIMEOUT_CHECK_INTERVAL)
```

#### 4.2.4 `_check_step_timeouts()` 增加守卫（当前 L356）

```python
async def _check_step_timeouts(self) -> None:
    """R89 🅱️: 检查所有活跃 Step 是否超时。"""
    # ── R90 🅲: <=0 禁用守卫 ──
    if not self._STEP_TIMEOUT_ENABLED:
        return
    # ... 原有逻辑不变 ...
```

#### 4.2.5 `_connect_and_listen()` 中 `create_task` 调用（当前 L109-111）

当前代码已无条件创建 `timeout_task`。R90 🅲 改为条件创建：

```python
# ── 🅱️ 启动超时检测后台 task ──
if self._STEP_TIMEOUT_ENABLED:
    timeout_task = asyncio.create_task(self._timeout_check_loop())
    logger.info("[AR] ⏰ 超时检测已启动 (interval=%ds, timeout=%ds)",
                self._TIMEOUT_CHECK_INTERVAL, self._STEP_DEFAULT_TIMEOUT)
```

这样 `_timeout_check_loop()` 内部的守卫是双重保障（`_connect_and_listen` 不创建 + 函数自身守卫）。

### 4.3 代码对比

```diff
# R89: 硬编码类常量
- _STEP_DEFAULT_TIMEOUT = 7200   # 2 小时默认超时
+ # R90 🅲: 从环境变量读取，支持 <=0 禁用
+ _STEP_DEFAULT_TIMEOUT = int(os.environ.get("AR_STEP_TIMEOUT", "7200"))
+ _STEP_TIMEOUT_ENABLED  = _STEP_DEFAULT_TIMEOUT > 0
```

```diff
# R89: 无条件创建超时 task
- timeout_task = asyncio.create_task(self._timeout_check_loop())
- logger.info("[AR] ⏰ 超时检测已启动 ...")
+ # R90 🅲: 条件创建
+ if self._STEP_TIMEOUT_ENABLED:
+     timeout_task = asyncio.create_task(self._timeout_check_loop())
+     logger.info("[AR] ⏰ 超时检测已启动 (interval=%ds, timeout=%ds)",
+                 self._TIMEOUT_CHECK_INTERVAL, self._STEP_DEFAULT_TIMEOUT)
```

### 4.4 环境变量行为矩阵

| `AR_STEP_TIMEOUT` | `_STEP_DEFAULT_TIMEOUT` | `_STEP_TIMEOUT_ENABLED` | 行为 |
|:-----------------:|:-----------------------:|:-----------------------:|:-----|
| 不设 | 7200 | `True` | 默认 2h 超时 |
| `3600` | 3600 | `True` | 1h 超时 |
| `0` | 0 | `False` | 完全禁用 |
| `-1` | -1 | `False` | 完全禁用 |
| `abc` | 抛 ValueError | N/A | ⚠️ 启动崩溃（期望行为：环境变量错误应立即暴露，不退化为 7200 静默） |

---

## 5. 改动对照表

### 5.1 auto_router.py 改动

| # | 位置 | 行号（当前） | 操作 | 说明 |
|:-:|:-----|:-----------|:----|:------|
| 1 | 类常量区 | L17-19 | ✏️ 修改 | `_STEP_DEFAULT_TIMEOUT` 改为 `os.environ.get("AR_STEP_TIMEOUT", "7200")` |
| 2 | 类常量区 | L19 (新增) | ➕ 新增 | `_STEP_TIMEOUT_ENABLED = _STEP_DEFAULT_TIMEOUT > 0` |
| 3 | `__init__()` | L65 附近 | ➕ 新增 2 行 | `logger.info("[AR] 超时=%ds (%s)", ...)` |
| 4 | `_handle_message()` | L163-167 | ✏️ 修改 | channel 过滤改为白名单模式：`is_pm_inbox OR is_admin` |
| 5 | `_handle_message()` | L175-185 | ✏️ 修改 | 信号检测前移，is_pm_inbox 包裹 Step 完成信号 |
| 6 | `_connect_and_listen()` | L109 | ✏️ 修改 | `create_task` 条件化：`if self._STEP_TIMEOUT_ENABLED` |
| 7 | `_timeout_check_loop()` | 函数入口 | ➕ 新增 4 行 | 增加 `if not self._STEP_TIMEOUT_ENABLED: return` |
| 8 | `_check_step_timeouts()` | 函数入口 | ➕ 新增 4 行 | 增加 `if not self._STEP_TIMEOUT_ENABLED: return` |
| **合计** | | | **~+40 行净增** | |

### 5.2 handler.py 改动

| # | 位置 | 行号（当前） | 操作 | 说明 |
|:-:|:-----|:-----------|:----|:------|
| 1 | `_cmd_pipeline_start()` | L2815 前 | ➕ 新增 ~12 行 | `pm_agent_id` + `❌` 检测 → `_broadcast_to_channel(pm_inbox, ...)` |
| **合计** | | | **~+15 行净增** | |

---

## 6. 兼容性分析

### 6.1 向后兼容矩阵

| 场景 | 旧行为 | R90 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| AutoRouter 只监听 PM inbox | ✅ 正常 | ✅ 额外监听 _admin | ✅ 增加不破坏 |
| _admin 频道其他消息 | N/A | ❌ 忽略（不含 `管线已启动`） | ✅ 零干扰 |
| 不设 AR_STEP_TIMEOUT | 默认 7200 | 默认 7200 | ✅ 完全一致 |
| AR_STEP_TIMEOUT=7200 | 硬编码 7200 | 环境变量读取后 = 7200 | ✅ 值相同 |
| 工作区创建成功 | 返回文本含 ✅ | 同上，不通知 PM | ✅ 零侵入 |
| 工作区创建失败（已有） | 返回文本含 ❌ | 返回文本 + PM 通知 | ✅ 仅增加通知 |
| handler.py 无 `PIPELINE_PM_AGENT_ID` | 无 PM 通知 | `getattr(config, ..., "")` → 空 → 跳过 | ✅ 优雅降级 |

### 6.2 重连后行为

| # | 场景 | 影响 |
|:-:|:-----|:------|
| B5 | AutoRouter 重连后，_admin 频道已有管线启动消息 | `_mark_seen(msg_id)` 判断为新消息？→ 取决于服务端是否重发历史消息。v1 依赖 `_restore_pipeline_state()` 恢复 |
| B6 | 重连后环境变量改变（AR_STEP_TIMEOUT 不同） | `os.environ` 在进程生命周期内不变，重连不影响 |

### 6.3 scope 边界

| 不改 | 原因 |
|:-----|:------|
| `config.py` | 环境变量直接在 `auto_router.py` 读取，不需要全局配置 |
| `__main__.py` | 服务入口零修改 |
| `agent_card.py` | 角色映射无变动 |
| `_cmd_create_workspace()` | 仅检测 `create_result` 字符串，不修改工作区创建逻辑 |

---

## 7. 风险与缓解

### 7.1 风险评估

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| R1 | `_admin` 频道收到大量无关消息 → AutoRouter 反复调用 `_handle_message` | 🟢 低 | `_mark_seen()` 去重 + 精确信号匹配。`_admin` 管线启动消息仅 1 条/周期 |
| R2 | `_admin` 频道泄露给 AutoRouter 不相关的系统消息 | 🟢 低 | AutoRouter 只订阅 `_admin` 的 `broadcast` 消息。所有非 `管线已启动` 的内容立即 return |
| R3 | `AR_STEP_TIMEOUT=abc` 非法值 → `int()` 抛 ValueError | 🟡 中 | **预期行为**：环境变量错误应使进程崩溃重启，不退化为静默默认值。Ops 配置时自动暴露 |
| R4 | `_broadcast_to_channel` 发送失败（PM 不在线） | 🟢 低 | try/except 包裹，日志 warning 即可。PM 收件箱消息有离线持久化 |
| R5 | `_cmd_pipeline_start` 末尾新增 ~15 行 → 回归风险 | 🟡 中 | 仅新增代码，不修改任何现有逻辑路径。集成测试验证 `❌` 检测 |
| R6 | `_STEP_TIMEOUT_ENABLED` 是实例属性而非类常量，运行时不可变 | 🟢 低 | 环境变量只在进程启动时读取，运行时不变。需改 → 重启进程 |

### 7.2 回退方案

| 级别 | 操作 | 复杂度 |
|:----:|:-----|:------:|
| 🟢 浅回退 🅰️ | 注释 `_admin` 频道白名单 → 恢复仅 PM inbox 监听 | 1 行 |
| 🟢 浅回退 🅱️ | 注释 `_cmd_pipeline_start` 末尾的 if 块 → 恢复无 PM 通知 | ~12 行 |
| 🟡 中回退 🅲 | `_STEP_DEFAULT_TIMEOUT` 改回硬编码 7200 | 2 行 |
| 🔴 全回退 | `git revert <commit-sha>` | 1 命令 |

---

## 8. 验收清单

### 🅰️ Admin 频道监听（3 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅰️-1 | `_handle_message()` 处理 `_admin` 频道的 `管线已启动` | 构造 admin 消息 → 检查 `_on_pipeline_ready` 被调用 | 收到信号 |
| 🅰️-2 | `_handle_message()` 不处理 `_admin` 频道的无关消息 | 发送普通文本 → 无 `_on_pipeline_ready` 调用 | 不响应 |
| 🅰️-3 | PM inbox 通道行为不变 | 回归：R87 中继转发 → 正常处理 Step 完成 | 不变 |

### 🅱️ 工作区创建失败通知（3 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅱️-1 | `create_result` 含 `❌` 时通知 PM | 模拟 workspace 创建失败 | PM 收件箱收到 ⚠️ |
| 🅱️-2 | `create_result` 不含 `❌` 时不通知 | 正常 `!pipeline_start` | 无 PM 通知 |
| 🅱️-3 | `pm_agent_id` 为空时跳过 | 设 `PIPELINE_PM_AGENT_ID=""` | try/except 不抛异常 |

### 🅲 环境变量 + 守卫（6 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅲-1 | 不设 `AR_STEP_TIMEOUT` → 默认 7200 | 无 env 启动 | `_STEP_DEFAULT_TIMEOUT == 7200` |
| 🅲-2 | `AR_STEP_TIMEOUT=3600` → 1h 超时 | 设 env 启动 | `_STEP_DEFAULT_TIMEOUT == 3600` |
| 🅲-3 | `AR_STEP_TIMEOUT=0` → 禁用超时 | 设 env=0 启动 | `_STEP_TIMEOUT_ENABLED == False` |
| 🅲-4 | 禁用时 `_timeout_check_loop()` 立即返回 | 日志检查 | `[AR] ⏰ 超时检测已禁用` |
| 🅲-5 | 禁用时 `_check_step_timeouts()` 立即返回 | 守卫行存在 | 函数入口有 `if not ...: return` |
| 🅲-6 | 禁用时 `create_task` 不创建 | 代码检查 | `_connect_and_listen` 条件化 |


---

### 流程图：AutoRouter 消息处理

```
_handle_message(msg)
    │
    ├─ _mark_seen(msg_id)? → Yes → return（去重）
    │
    ├─ channel 检查 ──────────────────────────────────────────────┐
    │   ┌────────────────────────────┬────────────────────────────┐ │
    │   │  is_pm_inbox               │  is_admin                  │ │
    │   │  (= channel == _pm_inbox)  │  (= channel == "_admin")   │ │
    │   └────────────────────────────┴────────────────────────────┘ │
    │   │                            │                              │
    │   │                            │                              │
    │   ▼                            ▼                              │
    │  "管线已启动" in content? ── Yes ──→ _on_pipeline_ready()    │
    │   │                            │                              │
    │   │  (PM inbox only)           │  (admin only)                │
    │   │  "✅ ... 任务完成"? ── Yes ──┤  其他 → return              │
    │   │  "✅ 完成，已推"? ── Yes ──┘                              │
    │   │                                                            │
    │   └─ 其他 → return                                            │
    └──────────────────────────────────────────────────────────────┘
```

---

*本文档由 🏗️ 架构师编写，待 Step 3 👨‍💻 编码实现。*
