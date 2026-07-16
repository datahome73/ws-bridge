# R122 技术方案

> **作者：** 🏗️ 小开（Arch）
> **版本：** v1.0
> **依据：** `docs/R122/R122-product-requirements.md` v1.0 ✅

---

## 1. 总体设计

### 1.1 架构变更

仅新增需求 A — 管线超时告警，不涉及需求 B/C（已明确搁置）。

**核心改动：** 在 `_auto_dispatch()` 派活成功处记录 `dispatched_at` 时间戳，新增轻量后台扫描协程，每 N 秒检查所有 `RUNNING` 管线中 `in_progress` 的 step 是否超过阈值，超时则向 PM 发送单次告警（`timeout_alerted` 防重复）。

```
_auto_dispatch() 成功派活
    │
    ├─ next_step_info["dispatched_at"] = time.time()
    ├─ next_step_info["timeout_alerted"] = False
    └─ mgr.save()
    
后台扫描协程（每 PIPELINE_TIMEOUT_SCAN_INTERVAL 秒）
    │
    └─ _pipeline_timeout_scan()
         ├─ 遍历所有 RUNNING 管线
         ├─ 遍历 steps 找 status=in_progress 且 dispatched_at 存在
         ├─ elapsed >= PIPELINE_TIMEOUT_ALERT_MINUTES * 60
         │   且 timeout_alerted == False
         │   └─ → 发送告警给 PM → timeout_alerted=True → mgr.save()
         └─ elapsed < 阈值 或 timeout_alerted=True → 跳过
```

**与现有 `_try_advance_pipeline` 的关系：** step 正常完成（收到 `已完成 ✅`）时，`_try_advance_pipeline` 将 step 标记为 `done`，扫描协程会自然跳过 `done` 状态的 step，不会误告警。超时告警和正常推进两条路径互不干扰。

### 1.2 涉及文件

| 文件 | 改动类型 | 预估行数 |
|:----|:--------|:--------:|
| `server/common/config.py` | 修改 | +6 行 |
| `server/ws_server/main.py` | 修改 | +60 行 |

仅涉及上述两个文件，均为服务端代码。服务端无需新增文件。

---

## 2. 详细设计

### 2.1 需求 A — 管线超时告警

#### 配置层（`server/common/config.py`）

新增两个配置项：

```python
# ── R122: 管线超时告警 ─────────────────────────────────
PIPELINE_TIMEOUT_ALERT_MINUTES: int = int(
    os.environ.get("R122_TIMEOUT_ALERT_MINUTES", "30")
)
PIPELINE_TIMEOUT_SCAN_INTERVAL: int = int(
    os.environ.get("R122_TIMEOUT_SCAN_INTERVAL", "300")
)
```

- `PIPELINE_TIMEOUT_ALERT_MINUTES`: 超时阈值（分钟），默认 **30 分钟**。设为 0 时禁用超时扫描。
- `PIPELINE_TIMEOUT_SCAN_INTERVAL`: 扫描间隔（秒），默认 **300 秒（5 分钟）**。仅当 `PIPELINE_TIMEOUT_ALERT_MINUTES > 0` 时有效。

#### 时间戳记录（`server/ws_server/main.py`，`_auto_dispatch` 函数）

**位置：** `_auto_dispatch` 函数中，派活成功（`sent > 0`）后，`next_step_info["status"] = "in_progress"` 设置处。

**当前代码（lines 2768-2776）：**
```python
    # R118: 派活成功后通知 PM
    if sent > 0:
        # 标记 step 为进行中，防止重复派活
        next_step_info["status"] = "in_progress"
        try:
            mgr = _ensure_pipeline_manager()
            mgr.save()
        except Exception:
            pass
        asyncio.ensure_future(_notify_pm(ctx, step_num, "dispatched"))
```

**变更后：**
```python
    if sent > 0:
        next_step_info["status"] = "in_progress"
        # ── R122: 记录派活时间戳 + 初始化告警标记 ──
        next_step_info["dispatched_at"] = time.time()
        next_step_info["timeout_alerted"] = False
        # ────────────────────────────────────────────
        try:
            mgr = _ensure_pipeline_manager()
            mgr.save()
        except Exception:
            pass
        asyncio.ensure_future(_notify_pm(ctx, step_num, "dispatched"))
```

两个字段均写入 step 字典，后续跟随 `mgr.save()` 持久化到 JSON。`dispatched_at` 用 `time.time()` 浮点数存储，与系统内其他时间戳一致。

#### 后台扫描协程（`server/ws_server/main.py`）

**启动入口：** 在 `on_message` 处理函数入口处（约第 1349 行），与 `_ensure_git_scan()` 并列：

```python
    _ensure_git_scan()
    _ensure_pipeline_timeout_scanner()  # R122: 管线超时扫描
```

**扫描协程实现：** 遵循 `_ensure_git_scan` → `_start_git_sync_loop` → `_pipeline_git_sync_scan` 的三层模式。

```python
# ── R122: 管线超时告警 ─────────────────────────────────

def _ensure_pipeline_timeout_scanner() -> None:
    """在 handler 初始化时调用一次。启动管线超时扫描定时循环。"""
    if config.PIPELINE_TIMEOUT_ALERT_MINUTES <= 0:
        logger.info("[R122] 管线超时告警已禁用（PIPELINE_TIMEOUT_ALERT_MINUTES=0）")
        return
    if state._PIPELINE_TIMEOUT_SCAN_TASK is None or state._PIPELINE_TIMEOUT_SCAN_TASK.done():
        state._PIPELINE_TIMEOUT_SCAN_TASK = asyncio.create_task(
            _start_pipeline_timeout_scan_loop()
        )
        logger.info(
            "[R122] 管线超时扫描已启动（interval=%ds, threshold=%dmin）",
            config.PIPELINE_TIMEOUT_SCAN_INTERVAL,
            config.PIPELINE_TIMEOUT_ALERT_MINUTES,
        )


async def _start_pipeline_timeout_scan_loop():
    """独立的超时扫描定时循环。"""
    while True:
        await asyncio.sleep(config.PIPELINE_TIMEOUT_SCAN_INTERVAL)
        try:
            await _pipeline_timeout_scan()
        except Exception as e:
            logger.warning("[R122] pipeline_timeout_scan error: %s", e)
```

#### 扫描核心逻辑（`_pipeline_timeout_scan`）

```python
async def _pipeline_timeout_scan():
    """遍历所有 RUNNING 管线，检查 in_progress 的 step 是否超时。"""
    threshold_seconds = config.PIPELINE_TIMEOUT_ALERT_MINUTES * 60
    now = time.time()
    mgr = _ensure_pipeline_manager()

    for round_name in list(state._PIPELINE_STATE.keys()):
        ctx = mgr.get(round_name)
        if not ctx:
            continue
        if ctx.status != PipelineStatus.RUNNING:
            continue

        for step_info in (ctx.steps or []):
            if step_info.get("status") != "in_progress":
                continue

            dispatched_at = step_info.get("dispatched_at")
            if dispatched_at is None:
                # 旧数据 — 无法判断超时，跳过
                continue

            elapsed = now - dispatched_at
            if elapsed < threshold_seconds:
                continue  # 未超时

            if step_info.get("timeout_alerted"):
                continue  # 已告警，不重复

            # ── 触发告警 ──
            step_key = step_info.get("name", "?")
            step_title = step_info.get("title", step_key)
            pm_id = config.PIPELINE_PM_AGENT_ID
            if not pm_id:
                logger.warning("[R122] 无 PM_AGENT_ID 配置，无法发送超时告警")
                step_info["timeout_alerted"] = True
                try:
                    mgr.save()
                except Exception:
                    pass
                continue

            alert_content = (
                f"⏰ 管线 {round_name} 超时告警\n"
                f"步骤: {step_key} ({step_title})\n"
                f"已等待: {int(elapsed // 60)} 分钟\n"
                f"阈值: {config.PIPELINE_TIMEOUT_ALERT_MINUTES} 分钟\n"
                f"建议: 检查对应 bot 是否在线，手动介入或跳过该 step"
            )

            await _send_to_agent(pm_id, {
                "type": "broadcast",
                "channel": f"_inbox:{pm_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": alert_content,
                "ts": now,
            })

            step_info["timeout_alerted"] = True
            try:
                mgr.save()
            except Exception:
                pass

            logger.info(
                "[R122] %s %s 超时告警已发送（%dmin > %dmin）",
                round_name, step_key,
                int(elapsed // 60), config.PIPELINE_TIMEOUT_ALERT_MINUTES,
            )
```

#### state 模块变更

在 `state.py`（或 `main.py` 顶部）的全局状态字典中新增：

```python
_PIPELINE_TIMEOUT_SCAN_TASK: asyncio.Task | None = None
```

#### 启动位置确认

`on_message` 入口处（约第 1349 行）已有 `_ensure_git_scan()`，在其后并列添加 `_ensure_pipeline_timeout_scanner()`。扫描协程使用 `asyncio.create_task` 启动，不阻塞主事件循环。

---

## 3. 向后兼容性

| 场景 | 影响 | 说明 |
|:----|:----:|:-----|
| 旧持久化 JSON（无 `dispatched_at` 字段） | ✅ 无影响 | 扫描发现 `dispatched_at` 为 None 时跳过该 step（日志 debug） |
| 旧持久化 JSON（无 `timeout_alerted` 字段） | ✅ 无影响 | `step_info.get("timeout_alerted")` 返回 None（== False）→ 可能触发一次告警（合理行为：重启后旧 step 超时仍需提醒 PM） |
| `PIPELINE_TIMEOUT_ALERT_MINUTES=0` | ✅ 优雅禁用 | 扫描直接不启动，日志提示已禁用 |
| 无 RUNNING 管线 | ✅ 无影响 | `for` 循环跳过，零开销 |
| 容器重启 | ✅ 无影响 | `dispatched_at` 和 `timeout_alerted` 已持久化到 JSON，重启后状态可感知 |
| 并发多管线同时超时 | ✅ 无锁竞争 | 各管线独立遍历，`_send_to_agent` 是 async 非阻塞，无竞态 |

---

## 4. 验收验证

### 4.1 对应需求 A

| # | 验收项 | 验证方式 | 预期 |
|:-:|:------|:--------|:-----|
| A-1 | `in_progress` 的 step 写入 `dispatched_at` 时间戳 | 手动触发派活 + 查看 JSON | `step_info` 字典含 `dispatched_at: float` + `timeout_alerted: false` |
| A-2 | 超时扫描协程每 5 分钟正常运行，不阻塞主循环 | 查看启动日志 | `[R122] 管线超时扫描已启动（interval=300s, threshold=30min）` |
| A-3 | step 正常完成时不触发告警 | 完成一个 step，等待扫描周期 | 无告警消息，日志无 `超时告警` |
| A-4 | step 超时 30 分钟后 PM 收到告警 | 调低阈值为 1 分钟，派活后等待扫描 | PM 收到 `⏰ 管线 Rxxx 超时告警` |
| A-5 | 同一 step 不再重复告警 | 等待 2 个扫描周期 | 仅第一次触发告警，`timeout_alerted=True` |
| A-6 | 无超时的管线不产生副作用 | 正常管线扫描 3 个周期 | 无告警消息，日志仅 `scan done` 或 debug |

---

## 5. 不做事项（再次确认）

| 排除项 | 理由 |
|:-------|:-----|
| ❌ 需求 B（regex 松匹配） | PM 明确搁置，有超时告警兜底 |
| ❌ 需求 C（小谷协议规范化） | PM 明确搁置 |
| ❌ 自动重试超时 step | PM 确认只告警不自动跳过 |
| ❌ 自动跳下一步 | 跳过不等于完成 |
| ❌ PipelineContext 新增字段 | `dispatched_at`/`timeout_alerted` 直接写在 step dict，不修改 dataclass |

---

> **审核记录：**
> - v1.0 提交方向审查：[2026-07-16]
> - 方向审查结论：🟢 通过
