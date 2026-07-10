# R89 产品需求 — AutoRouter 增强 🔧

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **前置条件：** R88 Pipeline AutoRouter 已部署 ✅（v2.54, main `1910a55`）
> **改动范围：** 仅 `server/auto_router.py`（零 handler.py 侵入）

---

## 1. 问题背景

### 1.1 现状

R88 AutoRouter 已实现 Pipeline 自动接力：
- PM = Step 1，`!pipeline_start` 即完成信号
- 5-Step 自动路由（Step 2→3→4→5→6）
- 72/72 测试通过，systemd 服务运行中

但仍有两个遗留问题：

| # | 问题 | 出处 | 影响 |
|:-:|:-----|:-----|:-----|
| 🅰️ | `_send_inbox()` payload 缺少 `from_name`/`agent_id`/`id`/`ts` 字段 | R88 Pitfall #78 | Bot 收到任务消息后无法识别发送者身份，消息元数据不完整 |
| 🅱️ | AutoRouter 无 Step 超时检测 | R88 Code Review E2/E7 | Bot 宕机/卡住时 AutoRouter 永久等待，PM 不知情 |

### 1.2 Bug 详情

**Bug 🅰️ — `_send_inbox()` payload 缺失字段**

当前 `auto_router.py` 的 `_send_inbox()`：

```python
payload = {
    "type": "message",
    "channel": f"_inbox:{target_id}",
    "content": content,
}
```

WS Bridge 消息协议要求的标准 payload 应包含：

| 字段 | 值 | 说明 |
|:-----|:----|:------|
| `type` | `"message"` | 消息类型 |
| `channel` | `"_inbox:{target_id}"` | 目标频道 |
| `content` | 任务消息 | 消息正文 |
| `from_name` | `"系统(管线)"` | 发送者显示名 |
| `agent_id` | `self.my_agent_id` | AutoRouter 的 agent ID |
| `id` | `f"auto-{int(time.time()*1000)}"` | 唯一消息 ID（去重用） |
| `ts` | `time.time()` | 时间戳 |

**缺失后果：** Bot 通过 `from_name` 识别消息来源为「系统(管线)」而非未知发送者，`agent_id` 用于去重和回复路由，`id` 和 `ts` 为服务端去重和排序提供必要信息。

**Bug 🅱️ — 无 Step 超时检测**

当前 AutoRouter 派活后永久等待 `✅ 完成` 信号：

```
PM ──→ AutoRouter 派活 ──→ Bot 干活...
                            （等待无限期）
```

如果 Bot 宕机、断连、卡住，AutoRouter 不会主动通知 PM。PM 只能自己发现管线停滞后再手动介入。

---

## 2. 方案设计

### 2.1 改动范围

| 文件 | 改动 | 估算 |
|:-----|:------|:----:|
| `server/auto_router.py` | ① `_send_inbox()` payload 补全 (~5行) | **+10 行** |
| | ② 新增 Step 超时检测机制 (~50行) | |
| **合计** | | **~+60 行净增** |

**零修改：** `handler.py` ✅ · `config.py` ✅ · `__main__.py` ✅ · `shared/` ✅ · `tests/` ✅

### 2.2 🅰️ `_send_inbox()` payload 补全

**入口：** `_send_inbox()` 方法（当前 L568-577）

**改动内容：**

```python
async def _send_inbox(self, target_id: str, content: str) -> None:
    """发送 inbox 消息到目标 bot。"""
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

> ⚠️ 需要在文件顶部新增 `import time`

### 2.3 🅱️ Step 超时检测

**原理：** 每次派活时记录 `dispatch_time`，后台定时器检查是否超时。

**新增配置常量：**

```python
_TIMEOUT_CHECK_INTERVAL = 300   # 5 分钟检查一次
_STEP_DEFAULT_TIMEOUT = 7200    # 2 小时默认超时
```

**新增数据结构：**

```python
# Key: round_name → {step_key: {"dispatch_time": float, "role": str}}
self._step_dispatch_times: dict[str, dict[str, dict]] = {}
self._step_timeout_notified: dict[str, set[str]] = {}  # round → set of step_keys notified
```

**改动点：**

| # | 位置 | 改动 |
|:-:|:-----|:------|
| 1 | `_dispatch_step()` 末尾 | 记录 `dispatch_time` 到 `_step_dispatch_times` |
| 2 | 新增 `_start_timeout_checker()` | 在 `_connect_and_listen()` 的主循环前启动 |
| 3 | 新增 `_timeout_check_loop()` | 周期性检查所有活跃 Step 是否超时 |
| 4 | 新增 `_check_step_timeouts()` | 遍历 `_step_dispatch_times`，超时则通知 PM |
| 5 | `_on_step_complete()` | Step 完成时清理对应的 `dispatch_time` 记录 |
| 6 | `_notify_all_done()` | 全部完成时清理该轮所有计时器 |

**超时检测逻辑：**

```python
async def _check_step_timeouts(self) -> None:
    """检查所有活跃 Step 是否超时。"""
    now = time.time()
    for round_name, steps in list(self._step_dispatch_times.items()):
        for step_key, info in list(steps.items()):
            elapsed = now - info["dispatch_time"]
            if elapsed > self._STEP_DEFAULT_TIMEOUT:
                # 检查是否已通知过
                notified = self._step_timeout_notified.setdefault(round_name, set())
                if step_key not in notified:
                    notified.add(step_key)
                    await self._send_to_pm(
                        f"⏰ AutoRouter 超时告警: {round_name} {step_key} "
                        f"({info['role']}) 已超过 {self._STEP_DEFAULT_TIMEOUT//3600}小时 "
                        f"未完成，请检查 Bot 状态"
                    )
```

**超时定时器启动位置：** 在 `_connect_and_listen()` 的 `async for raw in ws:` 主循环前启动，作为独立 `asyncio.create_task` 运行：

```python
async def _connect_and_listen(self) -> None:
    ...
    async with websockets.connect(...) as ws:
        ...
        # 启动超时检测后台任务
        timeout_task = asyncio.create_task(self._timeout_check_loop())
        
        async for raw in ws:
            ...
        finally:
            timeout_task.cancel()
```

### 2.4 改动一览

| 函数 | 当前 | 改动后 |
|:-----|:-----|:-------|
| `_send_inbox()` | 3 字段 payload | 7 字段 payload（+from_name/agent_id/id/ts） |
| `_dispatch_step()` | 发完即止 | 末尾记录 dispatch_time |
| `_on_step_complete()` | 清理 progress | 额外清理 dispatch_times |
| `_notify_all_done()` | 通知 PM | 额外清理计时器 |
| `_connect_and_listen()` | 纯监听循环 | 启动后台超时检测 task |
| (新增) `_timeout_check_loop()` | — | 周期性调用 `_check_step_timeouts()` |
| (新增) `_check_step_timeouts()` | — | 检测超时并通知 PM |

### 2.5 向后兼容

| 场景 | 影响 | 说明 |
|:-----|:-----|:------|
| AutoRouter 未启动 | ❌ 无 | 手动模式零影响 |
| AutoRouter 旧版 | ✅ 无 | 新版替换旧版，在线升级 |
| Bot 端 | ✅ 无 | payload 补全是增加字段，不减少已有字段 |
| STEP_TIMEOUT=0 | ✅ 无 | 设为 0 或负数 = 禁用超时检测 |
| 多活跃管线 | ✅ 无 | `_step_dispatch_times` 以 round_name 为 key |

---

## 3. 边界情况

| # | 场景 | 预期行为 |
|:-:|:-----|:---------|
| B1 | Bot 长时间正常工作中未超时 | 不触发超时通知（`elapsed < timeout`） |
| B2 | Bot 宕机/断连 | 超时后 PM 收到 ⏰ 告警 |
| B3 | 超时后 Bot 仍回复完成 | 正常处理完成，不再重复通知 |
| B4 | 同一 Step 多次超时检查 | 仅首次通知（`_step_timeout_notified` 防重复） |
| B5 | 超时检测时 AutoRouter 断线重连 | 重连后 `_step_dispatch_times` 清空（v1 限制，同 R88） |
| B6 | STEP_TIMEOUT=0 禁用超时 | 不创建超时检测 task |
| B7 | 超时后 PM 手动覆盖派活 | 手动消息和 AutoRouter 正常共存，互不干扰 |

---

## 4. 验收清单

| # | 内容 | 验证方法 |
|:-:|:-----|:---------|
| 🅰️-1 | `_send_inbox()` payload 含 from_name | 抓包检查 payload JSON |
| 🅰️-2 | `_send_inbox()` payload 含 agent_id | 抓包检查 payload JSON |
| 🅰️-3 | `_send_inbox()` payload 含 id | 抓包检查 payload JSON，id 格式为 `auto-{ts}` |
| 🅰️-4 | `_send_inbox()` payload 含 ts | 抓包检查 payload JSON |
| 🆁-1 | 超时检测后台 task 随主循环启动 | `_connect_and_listen()` 中有 `create_task` |
| 🆁-2 | 超时检测周期性运行（默认 5min） | 日志 `[AR] ⏰ 超时检查: N 个活跃 Step` |
| 🆁-3 | 超时达 2h 时通知 PM | PM 收件箱收到 ⏰ 告警 |
| 🆁-4 | 超时通知仅首次触发，不重复 | 同一 Step 不重复通知 |
| 🆁-5 | Step 完成后清理计时器 | `_on_step_complete()` 清理对应记录 |
| 🆁-6 | 超时检测不影响正常派活 | 正常 Step 流程不受超时检查干扰 |
| 🆁-7 | APP_TIMEOUT=0 禁用超时 | 不创建检测 task |

---

## 5. 风险与缓解

| 风险 | 等级 | 缓解 |
|:-----|:----:|:------|
| 超时检测 task 与主循环争 async 资源 | 🟢 | 纯 async sleep + 单次 O(n) 检查，无阻塞 |
| dispatch_time 在重连后丢失 | 🟡 | v1 限制，同 R88。重连后 PM 可手动确认进度 |
| 超时通知刷屏 | 🟢 | 仅首次通知，已启用 |
| `time.time()` 并发安全 | 🟢 | 单线程 async 模型，无需锁 |
