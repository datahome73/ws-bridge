# R89 技术方案 — AutoRouter 增强 🔧

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于需求文档：** `docs/R89/R89-product-requirements.md` v1.0
> **基于工作计划：** `docs/R89/WORK_PLAN.md` v1.0
> **改动文件：** `server/auto_router.py`（仅 1 文件，零 handler.py 侵入 ✅）

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ `_send_inbox()` payload 补全](#2-️-send_inbox-payload-补全)
3. [🅱️ Step 超时检测](#3-️-step-超时检测)
4. [改动对照表](#4-改动对照表)
5. [兼容性分析](#5-兼容性分析)
6. [风险与缓解](#6-风险与缓解)
7. [验收清单](#7-验收清单)

---

## 1. 改动总览

### 1.1 两处改动

| # | 改动 | 文件 | 净增行 | 影响函数数 |
|:-:|:-----|:-----|:------:|:----------:|
| 🅰️ | `_send_inbox()` payload 补全 — 新增 `from_name`/`agent_id`/`id`/`ts` | `auto_router.py` | ~5 | 1 |
| 🅱️ | Step 超时检测 — 后台定时检查 + PM 告警 | `auto_router.py` | ~55 | 6（含 2 新增） |
| **合计** | | | **~+60 行** | **7 个函数** |

### 1.2 仅改一个文件

```
server/auto_router.py
├── 🅰️ _send_inbox()           (payload 字段补齐)
├── 🅱️ _dispatch_step()         (末尾记录 dispatch_time)
├── 🅱️ _on_step_complete()      (完成时清理计时器)
├── 🅱️ _notify_all_done()       (全部完成时清理计时器)
├── 🅱️ _connect_and_listen()    (启动后台超时 task)
├── 🅱️ _timeout_check_loop()    (🆕 新增 — 周期性检查)
└── 🅱️ _check_step_timeouts()   (🆕 新增 — 超时判定 + 通知 PM)
```

✅ 零修改：`handler.py` · `config.py` · `__main__.py` · `agent_card.py` · `tests/`

### 1.3 改动位置全景图

```
  ┌─────────────────────────────────────────────────────────┐
  │  auto_router.py  (~250 行, R88 增量)                    │
  │                                                         │
  │  PipelineAutoRouter ───────────────────────────────────┐│
  │  │                                                     ││
  │  │  import time                   ← 🅱️ 新增 import    ││
  │  │                                                     ││
  │  │  class PipelineAutoRouter:                          ││
  │  │    _TIMEOUT_CHECK_INTERVAL = 300  ← 🅱️ 新增常量    ││
  │  │    _STEP_DEFAULT_TIMEOUT = 7200    ← 🅱️ 新增常量   ││
  │  │                                                     ││
  │  │    def __init__(...):                               ││
  │  │      self._step_dispatch_times = {}   ← 🅱️ 新增    ││
  │  │      self._step_timeout_notified = {} ← 🅱️ 新增    ││
  │  │                                                     ││
  │  │    async def _connect_and_listen(self):             ││
  │  │      ...                                            ││
  │  │      timeout_task = asyncio.create_task(  ← 🅱️     ││
  │  │          self._timeout_check_loop())                ││
  │  │      async for raw in ws:                           ││
  │  │        ...                                          ││
  │  │      finally:                                       ││
  │  │        timeout_task.cancel()                        ││
  │  │                                                     ││
  │  │    async def _send_inbox(...):                      ││
  │  │      🅰️ payload += from_name/agent_id/id/ts        ││
  │  │                                                     ││
  │  │    async def _dispatch_step(...):                   ││
  │  │      ...                                            ││
  │  │      self._record_dispatch(round, step)  ← 🅱️      ││
  │  │                                                     ││
  │  │    async def _on_step_complete(...):                 ││
  │  │      ...                                            ││
  │  │      self._cleanup_dispatch(round, step)  ← 🅱️     ││
  │  │                                                     ││
  │  │    async def _notify_all_done(...):                  ││
  │  │      ...                                            ││
  │  │      self._cleanup_all_dispatch(round)  ← 🅱️       ││
  │  │                                                     ││
  │  │    🆕 async def _timeout_check_loop(self):          ││
  │  │    🆕 async def _check_step_timeouts(self):          ││
  │  └─────────────────────────────────────────────────────┘│
  └─────────────────────────────────────────────────────────┘
```

---

## 2. 🅰️ `_send_inbox()` payload 补全

### 2.1 改动前 → 改动后

#### 🟡 当前（R88 伪代码，预计 L180-190）

```python
async def _send_inbox(self, target_id: str, content: str) -> None:
    """发送 inbox 消息到目标 bot。"""
    if not self.ws:
        raise RuntimeError("WebSocket 未连接")
    payload = {
        "type": "message",
        "channel": f"_inbox:{target_id}",
        "content": content,
    }
    await self.ws.send(json.dumps(payload))
```

#### ✅ 改动后（同文件，3 字段 → 7 字段）

```python
async def _send_inbox(self, target_id: str, content: str) -> None:
    """发送 inbox 消息到目标 bot。

    R89 🅰️: payload 补全 — 增加 from_name/agent_id/id/ts 四个字段。
    """
    if not self.ws:
        raise RuntimeError("WebSocket 未连接")
    payload = {
        "type": "message",
        "channel": f"_inbox:{target_id}",
        "content": content,
        "from_name": "系统(管线)",
        "agent_id": self.my_agent_id,
        "id": f"auto-{int(time.time() * 1000)}",
        "ts": time.time(),
    }
    await self.ws.send(json.dumps(payload))
```

### 2.2 新增字段说明

| 字段 | 值 | 作用 | 类型 |
|:-----|:----|:-----|:-----|
| `from_name` | `"系统(管线)"` | Bot 收到消息后识别来源显示名 | `str` |
| `agent_id` | `self.my_agent_id` | AutoRouter 自身 agent_id，Bot 可据此回复 | `str` |
| `id` | `f"auto-{int(t*1000)}"` | 消息唯一 ID（毫秒时间戳前缀），服务端去重用 | `str` |
| `ts` | `time.time()` | 消息发送时间戳，排序和超时判定用 | `float` |

### 2.3 依赖变化

**文件顶部 import 区：** 需要新增 `import time`

```python
import asyncio
import json
import logging
import os
import random
import re
import time      # ← 🅰️ 新增: payload ts/id 字段
from pathlib import Path
```

---

## 3. 🅱️ Step 超时检测

### 3.1 设计概览

```
_dispatch_step(round, step, agent)  ────→  _step_dispatch_times[round][step_key] = {dispatch_time, role}
                                                    │
                                                    ▼
                     _timeout_check_loop() — 每 5 分钟异步循环
                                                    │
                                                    ▼
                     _check_step_timeouts()
                       │                     elapsed > _STEP_DEFAULT_TIMEOUT(7200s)?
                       │                     └─ Yes → _step_timeout_notified[round] 检查是否已通知
                       │                                └─ 未通知 → _send_to_pm("⏰ 超时告警")
                       │                                └─ 已通知 → 跳过（防重复）
                       │
_on_step_complete() ──→ _cleanup_dispatch(round, step_key)  ← 移除计时器
_notify_all_done()  ──→ _cleanup_all_dispatch(round)       ← 清空该轮所有计时器
```

### 3.2 新增常量

```python
# ── R89 🅱️: Step 超时检测 ────────────────────────────────
_TIMEOUT_CHECK_INTERVAL = 300   # 5 分钟检查一次
_STEP_DEFAULT_TIMEOUT = 7200    # 2 小时默认超时
```

### 3.3 新增实例变量（`__init__`）

```python
# ── R89 🅱️: Step 超时检测 ──
# round_name → {step_key: {"dispatch_time": float, "role": str}}
self._step_dispatch_times: dict[str, dict[str, dict]] = {}
# round_name → set[step_key]  已通知超时的 step（防重复）
self._step_timeout_notified: dict[str, set[str]] = {}
```

### 3.4 新增函数 `_timeout_check_loop()`

```python
async def _timeout_check_loop(self) -> None:
    """R89 🅱️: Step 超时检测后台循环。

    随 `_connect_and_listen()` 启动，周期检查所有活跃 Step 是否超时。
    """
    while self._running:
        try:
            await self._check_step_timeouts()
        except Exception as e:
            logger.error("[AR] ⏰ 超时检查异常: %s", e)
        await asyncio.sleep(_TIMEOUT_CHECK_INTERVAL)
```

### 3.5 新增函数 `_check_step_timeouts()`

```python
async def _check_step_timeouts(self) -> None:
    """R89 🅱️: 检查所有活跃 Step 是否超时。

    遍历 `_step_dispatch_times`，超时 ≥ `_STEP_DEFAULT_TIMEOUT` 则通知 PM。
    同一 Step 仅首次通知（`_step_timeout_notified` 防重复）。
    """
    now = time.time()
    overdue_count = 0

    for round_name, steps in list(self._step_dispatch_times.items()):
        for step_key, info in list(steps.items()):
            elapsed = now - info["dispatch_time"]
            if elapsed > _STEP_DEFAULT_TIMEOUT:
                overdue_count += 1
                notified = self._step_timeout_notified.setdefault(round_name, set())
                if step_key not in notified:
                    notified.add(step_key)
                    await self._send_to_pm(
                        f"⏰ AutoRouter 超时告警: {round_name} {step_key} "
                        f"({info['role']}) 已超过 {_STEP_DEFAULT_TIMEOUT // 3600} 小时 "
                        f"未完成，请检查 Bot 状态"
                    )
                    logger.warning(
                        "[AR] ⏰ [%s] %s(%s) 超时: %.0fs",
                        round_name, step_key, info["role"], elapsed,
                    )

    logger.debug("[AR] ⏰ 超时检查: %d/%d 活跃 Step 超时",
                 overdue_count, sum(len(v) for v in self._step_dispatch_times.values()))
```

### 3.6 `_connect_and_listen()` 改动

```python
async def _connect_and_listen(self) -> None:
    """建立 WS 连接并进入主监听循环。"""
    self._running = True
    timeout_task: asyncio.Task | None = None  # ← 🅱️

    try:
        async with websockets.connect(...) as ws:
            self.ws = ws
            # ... 认证逻辑 ...

            # ── 🅱️ 启动超时检测后台 task ──
            timeout_task = asyncio.create_task(self._timeout_check_loop())
            logger.info("[AR] ⏰ 超时检测已启动 (interval=%ds, timeout=%ds)",
                        _TIMEOUT_CHECK_INTERVAL, _STEP_DEFAULT_TIMEOUT)

            # ── 主监听循环 ──
            async for raw in ws:
                # ... 消息处理 ...
                pass
    finally:
        # ── 🅱️ 取消超时 task ──
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()
            try:
                await timeout_task
            except asyncio.CancelledError:
                pass
```

### 3.7 `_dispatch_step()` 改动（末尾记录 dispatch_time）

```python
async def _dispatch_step(
    self,
    round_name: str,
    step_config: dict,
    prev_role: str,
    prev_sha: str,
    chain: list,
) -> None:
    """发送派活消息到目标 bot 的 inbox。"""
    role = step_config.get("role", "")
    step_key = step_config.get("step", "")

    # ... (现有逻辑: 找 target_id、构建 task_content、发送) ...

    await self._send_inbox(target_id, task_content)

    # ── 🅱️ 记录派活时间 ──
    self._step_dispatch_times.setdefault(round_name, {})[step_key] = {
        "dispatch_time": time.time(),
        "role": role,
    }
    logger.info("[AR] ⏰ [%s] %s(%s) 已记录派活时间",
                round_name, step_key, role)
```

### 3.8 `_on_step_complete()` 改动（完成时清理计时器）

```python
async def _on_step_complete(self, content: str) -> None:
    """Step 完成 → 自动派活下一棒。"""
    role = self._extract_role(content)
    sha = self._extract_sha(content)
    round_name = self._extract_round(content)
    # ... (现有逻辑: 进度更新、找下一步) ...

    # ── 🅱️ 清理该 Step 的计时器 ──
    self._cleanup_dispatch(round_name, step_key)
```

新增帮助方法（可选内联）：

```python
def _cleanup_dispatch(self, round_name: str, step_key: str) -> None:
    """R89 🅱️: 移除指定 Step 的超时计时器。"""
    steps = self._step_dispatch_times.get(round_name)
    if steps and step_key in steps:
        del steps[step_key]
        logger.debug("[AR] ⏰ [%s] %s 计时器已清理", round_name, step_key)
    # 也清理已通知标记（Step 完成了就不用再告警了）
    notified = self._step_timeout_notified.get(round_name)
    if notified and step_key in notified:
        notified.discard(step_key)
```

### 3.9 `_notify_all_done()` 改动（全部完成时清空该轮计时器）

```python
async def _notify_all_done(self, round_name: str) -> None:
    """通知 PM 全链闭环。"""
    # ... (现有逻辑: 通知 PM) ...

    # ── 🅱️ 清空该轮所有计时器 ──
    self._cleanup_all_dispatch(round_name)
```

新增帮助方法：

```python
def _cleanup_all_dispatch(self, round_name: str) -> None:
    """R89 🅱️: 清空指定轮次的所有超时计时器。"""
    self._step_dispatch_times.pop(round_name, None)
    self._step_timeout_notified.pop(round_name, None)
    logger.debug("[AR] ⏰ [%s] 全部计时器已清空", round_name)
```

### 3.10 `__init__` 新增 import (已包含)

```python
import time  # ← 🅰️ 也在用, 🅱️ 也依赖, 一个 import 满足两处
```

---

## 4. 改动对照表

### 4.1 精确函数级变化

| # | 函数 | 位置（auto_router.py） | 改动内容 | 行数变化 |
|:-:|:-----|:---------------------|:---------|:--------:|
| 1 | `import` 区 | 文件顶 ~L10 | 新增 `import time` | +1 |
| 2 | 模块级常量 | 类定义上方 ~L20 | 新增 `_TIMEOUT_CHECK_INTERVAL` + `_STEP_DEFAULT_TIMEOUT` | +2 |
| 3 | `__init__` | 类构造函数中 | 新增 `_step_dispatch_times` + `_step_timeout_notified` | +2 |
| 4 | `_send_inbox()` | ~L180-190 | payload 从 3 字段扩为 7 字段 | ~+4 |
| 5 | `_connect_and_listen()` | ~L70-90 | `create_task(_timeout_check_loop)` + finally cancel | ~+8 |
| 6 | `_dispatch_step()` | ~L328-371 | 末尾新增 `_step_dispatch_times` 记录 | ~+5 |
| 7 | `_on_step_complete()` | ~L278-317 | 完成时调用 `_cleanup_dispatch()` | ~+3 |
| 8 | `_notify_all_done()` | ~L480 附近 | 完成时调用 `_cleanup_all_dispatch()` | ~+2 |
| 9 | **🆕 `_timeout_check_loop()`** | 类中新增 | 新增函数 | ~+12 |
| 10 | **🆕 `_check_step_timeouts()`** | 类中新增 | 新增函数 | ~+25 |
| 11 | **🆕 `_cleanup_dispatch()`** | 类中新增（或内联） | 帮助方法 | ~+7 |
| 12 | **🆕 `_cleanup_all_dispatch()`** | 类中新增（或内联） | 帮助方法 | ~+5 |
| | **总计** | | | **~+60 行净增** |

### 4.2 行号参考说明

> **⚠️ 注意：** R88 的 `server/auto_router.py` 尚未编码实现（R88 Step 3 为编码阶段），上述行号基于 R88 技术方案的伪代码位置预估。实际行号以 Step 3（R89 Developer）编码时的源文件为准。**R89 改动点已明确标记 `# — 🅱️ R89` 和 `# — 🅰️ R89` 注释**，Developer 搜索这 2 个标记即可定位所有改动点。

---

## 5. 兼容性分析

### 5.1 向后兼容矩阵

| 场景 | 旧行为 | R89 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| Bot 接收入站消息 | 收到 3 字段 payload | 收到 7 字段 payload（4 新增字段不冲突） | ✅ 加字段不破坏 |
| Bot 根据 `agent_id` 回复 | 无此字段 | 有 `agent_id` 可回复 AutoRouter | ✅ 新能力 |
| 服务端消息去重 | 部分消息缺 `id` | 带 `auto-{ts}` 前缀的唯一 ID | ✅ 提升去重质量 |
| AutoRouter 未部署 | 无超时检测 | 无超时检测 | ✅ 零影响 |
| STEP_TIMEOUT=0（禁用） | N/A | `_timeout_check_loop` 不启动 | ✅ 由代码检查 |
| 旧版 AutoRouter 升级 | 无超时字段 | 升级后 `_step_dispatch_times` 为空 | ✅ 首次派活后正常记录 |
| 旧版 `handler.py` | 不处理超时 | 不做任何改变 | ✅ 零修改 |

### 5.2 多活跃管线兼容

| 场景 | 预期 |
|:-----|:------|
| R88 + R89 管线同时运行 | `_step_dispatch_times["R88"]` 和 `["R89"]` 独立 key，互不影响 |
| R88 Step 2 超时 + R89 Step 3 正常 | 各自检测，各自通知，互不干扰 |
| R88 全部完成 → 清空 R88 计时器 | `_cleanup_all_dispatch("R88")` 不影响 R89 |

### 5.3 scope 边界

| 不改 | 原因 |
|:-----|:------|
| `handler.py`（~6200 行） | 协议层无变动，`_send_inbox` 是 AutoRouter 自有方法 |
| `config.py` | 超时时间直接用类常量，不需要全局配置 |
| `agent_card.py` | 角色映射无变动 |
| `tests/` | 纯新增功能，回归测试由 R88 已有用例覆盖 |
| Web 端 / 客户端库 | 不相关模块 |

---

## 6. 风险与缓解

### 6.1 风险评估

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| R1 | 超时检测 task 与主循环争 async 资源 | 🟢 低 | 纯 `asyncio.sleep` + 单次 O(n) 遍历，无 CPU 密集操作 |
| R2 | `_step_dispatch_times` 在 AutoRouter 重连后丢失 | 🟡 中 | **v1 已知限制**：重连后 `_restore_pipeline_state()` 不恢复计时器。PM 收到「已恢复」通知后自行确认进度 |
| R3 | 超时通知刷屏 | 🟢 低 | `_step_timeout_notified` set 严格防重复：同一 Step 最多 1 条告警 |
| R4 | 派活成功但 WS send 失败 → 未记录 dispatch_time → 无超时检测 | 🟡 中 | 应在 WS send 成功之后再记录 dispatch_time（先 await send，后记录） |
| R5 | `time.time()` 线程安全 | 🟢 低 | 单线程 async 模型，无需锁 |
| R6 | `_TIMEUT_CHECK_INTERVAL` 与 `_STEP_DEFAULT_TIMEOUT` 不匹配 | 🟢 低 | 默认 5min 间隔 vs 2h 超时，第一个超时通知在派活后 2h5min 发出，延迟 <5min，可接受 |

### 6.2 回退方案

| 级别 | 操作 | 复杂度 |
|:----:|:-----|:------:|
| 🟢 浅回退 | 注释 `create_task(self._timeout_check_loop)` 一行 → 禁用超时 | 1 行 |
| 🟡 中回退 | 注释 `_send_inbox()` 中 4 个新字段 → payload 恢复旧版 3 字段 | 4 行 |
| 🔴 全回退 | `git revert <commit-sha>` | 1 命令 |

### 6.3 重连后超时检测状态迁移

| 状态 | 重连前 | 重连后（v1） |
|:-----|:-------|:-----------|
| `_step_dispatch_times` | 有 Step2 正在等待 | ❌ 丢失（`__init__` 重新初始化为 {}） |
| `_step_timeout_notified` | 已通知 PM Step2 超时 | ❌ 丢失 |
| 影响 | — | 重连后不会对之前超时的 Step 重新告警 |

---

## 7. 验收清单

### 🅰️ Payload 补全（4 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅰️-1 | payload 含 `from_name` | WS 抓包 / 日志检查 | `"from_name": "系统(管线)"` |
| 🅰️-2 | payload 含 `agent_id` | WS 抓包 / 日志检查 | `"agent_id": self.my_agent_id` |
| 🅰️-3 | payload 含 `id` | WS 抓包 / 日志检查 | 格式 `"auto-{毫秒时间戳}"` |
| 🅰️-4 | payload 含 `ts` | WS 抓包 / 日志检查 | `"ts": 1700000000.123` (float) |

### 🅱️ 超时检测（7 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🆁-1 | 超时检测 task 随主循环启动 | 查看 `_connect_and_listen()` 源码 | 有 `create_task(self._timeout_check_loop())` |
| 🆁-2 | 周期性运行（默认 5min） | 日志检查 | 每 ~5min 出现 `[AR] ⏰ 超时检查: N 个活跃 Step` |
| 🆁-3 | 超时达 2h 时通知 PM | 模拟超时（短时间隔+短超时）验证 | PM 收件箱收到 `⏰ AutoRouter 超时告警` |
| 🆁-4 | 仅首次通知，不重复 | 连续等待 2 个检查周期 | 同一 Step 仅 1 条告警 |
| 🆁-5 | Step 完成后清理计时器 | 完成 Step → 检查 `_step_dispatch_times` | 对应 step_key 已删除 |
| 🆁-6 | 全部完成时清理计时器 | 最后 Step 完成 → 检查 | 该 round 的所有计时器已清空 |
| 🆁-7 | 超时检测不影响正常派活 | 同时运行超时 + 正常接力 | 正常 Step 流程不受超时检查干扰 |

---

*本文档由 🏗️ 架构师编写，待 Step 3 👨‍💻 编码实现。*
