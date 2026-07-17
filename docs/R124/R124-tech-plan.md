# R124 技术方案

> **作者：** 📐 Arch（小开）
> **版本：** v1.0
> **依据：** `docs/R124/R124-product-requirements.md` v1.0 ✅
> **状态：** 待审核

---

## 1. 总体设计

### 1.1 问题与根因

R123 完成后管线已具备跨 Step 上下文字动注入能力，但**自动流转仍存在 4 个缺口**：

| 缺口 | 根因 | 影响 |
|:-----|:------|:-----|
| **驳回不退** | `退回 🔄` 仅走 relay 通知路由（L3033-3056），不操作 PipelineContext 状态机 | 自动流转在首次退回即被阻断 |
| **做完不清理** | 管线完成仅标记 `status=completed`，不移除活跃上下文 | 数据膨胀，`pipeline_contexts.json` 堆积 |
| **缺乏产出验证** | `已完成 ✅` 是唯一的推进条件，bot 虚构 SHA 也能通过 | 信任脆弱 |
| **超时处理单一** | 30min 超时仅告警一次（L612），无重试或状态标记 | 离线即卡死，PM 必须手动处理 |

### 1.2 架构变更

**变更策略（4 项独立增强，互不耦合）：**

```
                    ┌─ 需求 A: 驳回状态回退 ─────────────────┐
_handle_server_relay│ L3033-3056: 退回后插入 _handle_reject() │
                    └─────────────────────────────────────────┘

                    ┌─ 需求 B: 自动归档 ───────────────────────┐
_try_advance_pipeline│ L2505-2508: 全 step done 后调用 archive │
                    └─────────────────────────────────────────┘

                    ┌─ 需求 C: 产出验证 ───────────────────────┐
_try_advance_pipeline│ L2479 后: SHA 验证 + 可选远程 git 检查  │
                    └─────────────────────────────────────────┘

                    ┌─ 需求 D: 超时增强 ───────────────────────┐
_pipeline_timeout_scan│ L612 后: 30min 重发 + 45min timeout 标记│
                    └─────────────────────────────────────────┘
```

### 1.3 涉及文件

| 文件 | 改动类型 | 预估行数 | 对应需求 |
|:----|:--------|:--------:|:--------:|
| `server/ws_server/main.py` | 修改（3 处已有函数 + 新增 3 个辅助函数） | ~+155 行 | A/B/C/D |
| `server/common/config.py` | 新增 3 个配置项 | ~+8 行 | C/D |
| `server/ws_server/pipeline_context.py` | 不修改（`PipelineContext` 已有 `steps`/`status`，新字段通过实例 dict 动态存取） | 0 行 | A/B |

**合计：~163 行，全部在已有模块内，无新增文件。**

---

## 2. 详细设计

### 2.1 需求 A — 驳回自动回退（`_handle_reject`）

#### 2.1.1 插入点

`_handle_server_relay` 中「规则 3: 退回 🔄」区块（L3033-3056），在转发 PM 和自动确认之后、`return True` 之前，插入回退逻辑。

```python
# 当前代码（L3033-3056，仅转发 PM + 自动确认）：
# ═══ 规则 3: 退回 🔄 ═══
if content.startswith("退回 🔄"):
    ...  # 转发 PM + 自动确认 (不动)
    # 🔴 R124 新插入:
    asyncio.ensure_future(_handle_reject(content, agent_id))
    return True
```

#### 2.1.2 `_handle_reject` 函数设计

```python
async def _handle_reject(content: str, sender_agent_id: str) -> None:
    """处理退回 🔄 R{N} Step {N} — 原因 消息。

    管线状态回退 + 通知 PM，不自动重新派活。
    异步后台执行（不阻塞 relay 返回）。
    """
    # 1. 解析轮次和 Step N
    m = re.match(r"退回 🔄 (R\d+) Step (\d+)", content)
    if not m:
        logger.info("[R124] 退回消息格式不匹配: %s...", content[:60])
        return
    round_name = m.group(1)
    rejected_step = int(m.group(2))

    # 2. 获取上下文
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        logger.info("[R124] 退回: 管线 %s 不存在，忽略", round_name)
        return

    # 3. 状态守卫: 已完成/已归档/已取消/已卡死 → 忽略
    if ctx.status in ("completed", "cancelled", "stopped"):
        logger.info("[R124] 退回: %s 状态=%s，忽略", round_name, ctx.status)
        return

    # 4. 提取退回原因
    reject_reason = ""
    # 支持全角 — 或半角 --
    for sep in ("—", "--", "-"):
        if sep in content:
            reject_reason = content.split(sep, 1)[1].strip()[:200]
            break
    if not reject_reason:
        reject_reason = content[:100]  # 退路: 无分隔符时取前 100 字符

    # 5. 轮次级退回计数检查（第 4 次 stuck）
    reject_count = getattr(ctx, "reject_count", 0) + 1
    ctx.reject_count = reject_count
    if reject_count >= 4:
        ctx.status = "stuck"
        mgr.save()
        logger.info("[R124] %s 第 4 次退回，标记 stuck", round_name)
        await _notify_pm(
            ctx, rejected_step, "stuck",
            f"🔄 {round_name} Step {rejected_step} 被退回。管线已卡死（累计退回 {reject_count} 次），"
            f"需要人工介入。\n原因: {reject_reason}",
        )
        return

    # 6. 确定回退起点 index
    # Step 1/2 → 回退到 index 0 (Step 1)
    # Step 3+ → 回退到 index 2 (Step 3 编码)
    rollback_start = 1 if rejected_step <= 2 else 2  # index

    # 7. 重置 affected steps
    step_key_3 = f"step{rollback_start + 1}"  # step3
    for i in range(rollback_start, len(ctx.steps)):
        ctx.steps[i]["status"] = "pending"
        ctx.steps[i]["output"] = None
        ctx.steps[i]["result_msg"] = ""
        ctx.steps[i].pop("reject_reason", None)

    # 8. 记录退回原因到回退目标 step
    ctx.steps[rollback_start]["reject_reason"] = reject_reason

    # 9. 回退管线 current_step
    ctx.current_step = rollback_start + 1  # 1-indexed

    # 10. 持久化 + 通知 PM
    mgr.save()
    await _notify_pm(
        ctx, rejected_step, "rejected",
        f"🔄 {round_name} Step {rejected_step} 被退回（累计 {reject_count}/3）\n"
        f"原因: {reject_reason}\n"
        f"管线已退回到 Step {rollback_start + 1}（编码环节），未自动派活。\n"
        f"请 PM 决定下一步：派活 Dev 重做 or ##advance 跳过。",
    )
    logger.info("[R124] 退回处理完成: %s Step %d → rollback_to Step %d, reason=%s",
                round_name, rejected_step, rollback_start + 1, reject_reason)
```

#### 2.1.3 边界情况

| 场景 | 行为 | 验证 |
|:-----|:------|:-----|
| 管线不存在 | 静默忽略（log only） | A-3 |
| 管线已完成/已取消 | 静默忽略 | A-3 |
| 退 Step 4（Review） | rollback_start=2 → 重置 Step 3~N | A-1 |
| 退 Step 5（QA） | rollback_start=2 → 重置 Step 3~N | A-1 |
| 退 Step 2（Arch） | rollback_start=1 → 重置 Step 2~N | A-1 |
| 退 Step 1（PM） | rollback_start=1 → 重置 Step 1~N（罕见但安全） | A-1 |
| 无 `—` 分隔符 | reject_reason 取消息前 100 字符 | A-6 |
| 第 4 次退回 | 标记 status=stuck，不回退任何 step | A-5 |
| `ctx.reject_count` 不存在旧数据 | `getattr(ctx, "reject_count", 0)` → 0 | D 兼容 |

#### 2.1.4 通知 PM 格式

`_notify_pm` 新增 `status="rejected"` 和 `status="stuck"` 分支（已有 `dispatched`/`completed`/`failed`/`retrying`）：

- `rejected`: ⚠️ 格式，含退回原因 + 回退信息 + 提示 PM 操作
- `stuck`: 🔴 格式，含累计退回次数，提示人工介入

---

### 2.2 需求 B — 管线自动归档（`_archive_pipeline`）

#### 2.2.1 归档触发位置

`_try_advance_pipeline` 中，在「最后一步已完成」分支（L2505-2509）内：

```python
# 当前代码（L2504-2510）：
if next_step <= ctx.total_steps:
    asyncio.ensure_future(_auto_dispatch(ctx, next_step))
else:
    # 最后一步已完成，标记管线 completed
    asyncio.ensure_future(mgr.transition_to(round_name, PipelineStatus.COMPLETED))
    logger.info("[R107] %s 全管线已完成 ✅", round_name)
    asyncio.ensure_future(_notify_pm(ctx, ctx.total_steps, "completed"))
    # 🔴 R124: 归档
    asyncio.ensure_future(_archive_pipeline(round_name))  # 新增
```

#### 2.2.2 `_archive_pipeline` 函数设计

```python
async def _archive_pipeline(round_name: str) -> None:
    """归档已完成管线：从活跃上下文移除，追加到 pipeline_archive.json。"""
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        return

    # 构造归档记录
    now = time.time()
    archive_record = {
        "round_name": ctx.round_name,
        "status": "completed",
        "archived_at": now,
        "completed_at": getattr(ctx, "updated_at", now),
        "reject_count": getattr(ctx, "reject_count", 0),
        "steps": ctx.steps,
        "artifacts": getattr(ctx, "artifacts", {}),
        "references": getattr(ctx, "references", {}),
        "summary": {
            "total_steps": len(ctx.steps),
            "completed_steps": sum(
                1 for s in (ctx.steps or []) if s.get("status") == "done"
            ),
            "reject_count": getattr(ctx, "reject_count", 0),
            "total_duration_sec": int(
                now - getattr(ctx, "created_at", now)
            ) if getattr(ctx, "created_at", None) else 0,
        },
    }

    # 从活跃上下文移除
    mgr._contexts.pop(round_name, None)
    mgr.save()  # 保存更新后的活跃列表

    # 追加到归档文件
    archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
    records: list[dict] = []
    if archive_path.exists():
        try:
            records = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = []
    records.append(archive_record)

    # 清理：超过 50 条时保留最近 30 条
    MAX_ARCHIVE_TRIM = 50
    KEEP_ARCHIVE = 30
    if len(records) > MAX_ARCHIVE_TRIM:
        records = records[-KEEP_ARCHIVE:]

    try:
        archive_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[R124] 归档完成: %s → %s (%d 条归档)",
                    round_name, archive_path, len(records))
    except (OSError, PermissionError) as e:
        logger.warning("[R124] 归档写入失败: %s", e)
```

#### 2.2.3 手动归档 `##archive##R{N}` 命令

在 `_handle_hash_cmd` 中新增 `archive` 命令分支：

```python
# 在 _handle_hash_cmd 中新增:
elif cmd == "archive":
    return await _handle_hash_archive(round_name, agent_id, ws)
```

`_handle_hash_archive` 实现：

```python
async def _handle_hash_archive(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##archive##R{N} — PM 手动归档管线。"""
    # 权限校验：仅 PM
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_agent_id and agent_id != pm_agent_id:
        await _send(ws, {
            "type": "broadcast", "channel": f"_inbox:{agent_id}",
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": "❌ 无权限: ##archive 仅 PM 可用",
            "ts": time.time(),
        })
        return True

    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {
            "type": "broadcast", "channel": f"_inbox:{agent_id}",
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True

    await _archive_pipeline(round_name)
    await _send(ws, {
        "type": "broadcast", "channel": f"_inbox:{agent_id}",
        "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"📦 {round_name} 管线已手动归档",
        "ts": time.time(),
    })
    return True
```

#### 2.2.4 归档后 `##status` 透传

`_handle_hash_status` 中（L3475-3486），`mgr.get(round_name)` 返回 None 时，改为尝试从 archive 文件读取：

```python
# 修改 _handle_hash_status:
ctx = mgr.get(round_name)
if not ctx:
    # 🔴 R124: 尝试从归档文件查找
    archive_info = _find_archive(round_name)
    if archive_info:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"📦 {round_name} 已归档，数据在 pipeline_archive.json\n"
                       f"状态: {archive_info.get('status', 'completed')}\n"
                       f"归档时间: {_fmt_ts(archive_info.get('archived_at', 0))}\n"
                       f"总步数: {archive_info.get('summary', {}).get('total_steps', 0)}"
                       f" / 完成: {archive_info.get('summary', {}).get('completed_steps', 0)}",
            "ts": time.time(),
        })
        return True
    # 原逻辑：管线不存在
    ...
```

辅助函数 `_find_archive`：

```python
def _find_archive(round_name: str) -> dict | None:
    """从 pipeline_archive.json 查找已归档轮次。"""
    archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
    if not archive_path.exists():
        return None
    try:
        records = json.loads(archive_path.read_text(encoding="utf-8"))
        for rec in records:
            if rec.get("round_name") == round_name:
                return rec
    except (OSError, json.JSONDecodeError):
        pass
    return None
```

---

### 2.3 需求 C — Step 产出基本验证

#### 2.3.1 插入点

`_try_advance_pipeline` 中，R115 artifacts 记录之后（L2478）、R120 状态标记之前（L2481）。产出验证的时机在**推进 step 之前**，且**不阻断推进**。

```python
# 当前代码结构 (L2467-2491):
# R115: 提取 artifacts
_kv = _extract_artifact_kv(content)
if _kv:
    ctx.artifacts[_step_key] = _kv
    # 🔴 R124: 验证插入点 ← 在 mgr.save() 之后、mark_done 之前

# advance step
asyncio.ensure_future(mgr.advance_step(...))
# R120: mark done
...
```

#### 2.3.2 SHA 格式验证

```python
# 在 R115 artifacts 保存后插入（L2478 后，L2481 前）：
# ═══ R124: Step 产出基本验证 ═══
if _kv:
    _step_idx_validate = completed_step - 1
    if 0 <= _step_idx_validate < len(ctx.steps):
        _step_v = ctx.steps[_step_idx_validate]
        _output_v = _step_v.get("output") or {}
        if not isinstance(_output_v, dict):
            _output_v = {}
        # C-1: SHA 格式验证
        _sha_v = _kv.get("sha", "")
        if _sha_v:
            import re as _re_sha
            if _re_sha.match(r"^[0-9a-f]{7,40}$", _sha_v):
                _output_v["sha_validation"] = "valid_format"
            else:
                _output_v["sha_validation"] = "invalid_format"
        # 写入 step output（output 字段可能尚未创建）
        _step_v["output"] = _output_v if _output_v else None
        # C-5: 远程 git 验证（可选）——异步触发，不阻塞
        if (config.PIPELINE_OUTPUT_VERIFICATION
                and _sha_v
                and _output_v.get("sha_validation") == "valid_format"):
            asyncio.ensure_future(
                _verify_sha_remote(round_name, completed_step, _sha_v)
            )
# ═══════════════════════════════════════════════
```

**注意：** 验证写入在 `ctx.steps[i]["output"]`，与 R115 artifacts 分离。R115 存储 `ctx.artifacts["step{N}"]` 全量 KV，验证结果存储在 `ctx.steps[i]["output"]["sha_validation"]`，互不冲突。

#### 2.3.3 远程 git 验证（可选，`PIPELINE_OUTPUT_VERIFICATION=1`）

```python
async def _verify_sha_remote(round_name: str, step_num: int, sha: str) -> None:
    """异步验证 SHA 在远程 dev 分支的存在性。不阻断管线推进。"""
    try:
        mgr = _ensure_pipeline_manager()
        ctx = mgr.get(round_name)
        if not ctx:
            return
        _step = ctx.steps[step_num - 1] if step_num - 1 < len(ctx.steps) else None
        if not _step:
            return
        _output = _step.get("output") or {}

        async with asyncio.timeout(5):  # 5s 超时
            # C-2: 检查 SHA 在远程 dev 分支
            proc = await asyncio.create_subprocess_exec(
                "git", "ls-remote", "origin", "dev",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if sha in stdout.decode("utf-8", errors="replace"):
                _output["sha_validation"] = "verified"
            else:
                _output["sha_validation"] = "not_found"
                return

            # C-3: 检查 commit message 是否包含轮次名
            proc2 = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", sha, "-1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate()
            _msg = stdout2.decode("utf-8", errors="replace")
            if round_name in _msg:
                _output["commit_round_match"] = "matched"
            else:
                _output["commit_round_match"] = "mismatched"

        _step["output"] = _output
        mgr.save()
    except asyncio.TimeoutError:
        # 超时不阻断，标记 unchecked
        if ctx and _step:
            _step["output"]["sha_validation"] = "unchecked"
            mgr.save()
    except Exception as e:
        logger.warning("[R124] SHA 验证异常: %s", e)
```

#### 2.3.4 环境变量

新增 config 项（`server/common/config.py`）：

```python
# ── R124: 产出验证 ───────────────────────────────────────
PIPELINE_OUTPUT_VERIFICATION: bool = (
    os.environ.get("PIPELINE_OUTPUT_VERIFICATION", "0") == "1"
)
```

---

### 2.4 需求 D — 超时自动化增强

#### 2.4.1 插入点

`_pipeline_timeout_scan`（L559-620）现有 30min 告警逻辑之后、循环结束之前。

#### 2.4.2 增强后的 _pipeline_timeout_scan

```python
async def _pipeline_timeout_scan(timeout_min: int) -> None:
    """遍历所有 RUNNING 管线，检查 in_progress step 是否超时。

    R122: 30min 告警（已有，不动）
    R124: + 重发派活（re_notified）+ 45min timeout 标记
    """
    from .pipeline_context import PipelineStatus as PS
    now = time.time()
    threshold = timeout_min * 60.0
    mgr = _ensure_pipeline_manager()
    altered = False

    for ctx in mgr.get_all_active():
        if ctx.status != PS.RUNNING and getattr(ctx, "status", None) != "running" and ctx.status.value != "running":
            continue
        step_num = None
        for step in (ctx.steps or []):
            if step.get("status") != "in_progress":
                continue
            dispatched_at = step.get("dispatched_at")
            if not dispatched_at:
                continue
            elapsed = now - dispatched_at

            # 先找 step 序号
            step_key = step.get("name", step.get("step_key", ""))
            try:
                step_num = int(step_key.replace("step", ""))
            except (ValueError, TypeError):
                step_num = None

            # ── R122 已有: 30min 首次告警（不动）──
            if elapsed >= threshold and not step.get("timeout_alerted"):
                step["timeout_alerted"] = True
                altered = True
                pm_id = config.PIPELINE_PM_AGENT_ID
                if pm_id and step_num:
                    await _send_to_agent(pm_id, {...})  # 已有 L590-605
                logger.info("[R122] 超时告警: %s Step %s → PM",
                            ctx.round_name, step_key)

            # ── R124 新增: 30min 重发派活 ──
            retry_min = getattr(config, "PIPELINE_TIMEOUT_RETRY_MINUTES", 30)
            if (retry_min > 0
                    and elapsed >= retry_min * 60
                    and step.get("timeout_alerted")
                    and not step.get("re_notified")):
                step["re_notified"] = True
                altered = True
                asyncio.ensure_future(_auto_re_notify(ctx, step_key, step_num))
                logger.info("[R124] 超时重发: %s Step %s",
                            ctx.round_name, step_key)

            # ── R124 新增: 45min timeout 标记 ──
            mark_min = getattr(config, "PIPELINE_TIMEOUT_MARK_MINUTES", 45)
            if (mark_min > 0
                    and elapsed >= mark_min * 60
                    and step.get("re_notified")
                    and step.get("status") != "timeout"):
                step["status"] = "timeout"
                altered = True
                pm_id = config.PIPELINE_PM_AGENT_ID
                if pm_id and step_num:
                    await _send_to_agent(pm_id, {
                        "type": "broadcast",
                        "channel": f"_inbox:{pm_id}",
                        "from_name": "系统",
                        "from_agent": state.SYSTEM_AGENT_ID,
                        "content": (
                            f"⏰ {ctx.round_name} Step {step_key} bot 已 "
                            f"{int(elapsed // 60)} 分钟未响应，已标记 timeout。\n"
                            f"请 PM 处理。"
                        ),
                        "ts": time.time(),
                    })
                logger.info("[R124] 超时标记: %s Step %s → timeout",
                            ctx.round_name, step_key)

    if altered:
        try:
            mgr.save()
        except Exception:
            pass
```

#### 2.4.3 `_auto_re_notify` 辅助函数

```python
async def _auto_re_notify(ctx: PipelineContext, step_key: str, step_num: int) -> None:
    """超时后重新发送派活消息给 bot。"""
    step_idx = step_num - 1 if step_num else 0
    step_info = ctx.steps[step_idx] if step_idx < len(ctx.steps) else None
    if not step_info:
        return

    target_agent_id = step_info.get("agent_id", "")
    if not target_agent_id:
        logger.warning("[R124] 重发失败: %s %s 无 agent_id", ctx.round_name, step_key)
        return

    # 从模板重新构造派活消息
    template = ctx.message_templates.get(step_key, "")
    if template:
        content = _render_template(template, ctx, step_num)
    else:
        content = f"🔄 重发 — {ctx.round_name} {step_key}，请继续完成"

    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{target_agent_id}",
        "content": f"⏰ 超时重发\n\n{content}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "to_agent": target_agent_id,
        "id": f"retry-{ctx.round_name}-{step_key}-{int(time.time() * 1000)}",
        "ts": time.time(),
    }

    sent = await _send_to_agent(target_agent_id, payload)
    logger.info("[R124] 超时重发 %s %s → %s: sent=%d",
                ctx.round_name, step_key, target_agent_id, sent)

    # 通知 PM 重发结果
    pm_id = config.PIPELINE_PM_AGENT_ID
    if pm_id:
        await _send_to_agent(pm_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": (
                f"📬 {ctx.round_name} Step {step_key} 超时，已重新发送派活消息 "
                f"给 {step_info.get('agent_name', '?')} "
                f"（发送结果: {'✅' if sent > 0 else '❌'}）"
            ),
            "ts": time.time(),
        })
```

#### 2.4.4 新配置项

```python
# ── R124: 超时自动化增强 ────────────────────────────────
PIPELINE_TIMEOUT_RETRY_MINUTES: int = int(
    os.environ.get("PIPELINE_TIMEOUT_RETRY_MINUTES", "30")
)
PIPELINE_TIMEOUT_MARK_MINUTES: int = int(
    os.environ.get("PIPELINE_TIMEOUT_MARK_MINUTES", "45")
)
```

设 `0` 时禁用对应功能（如 `PIPELINE_TIMEOUT_RETRY_MINUTES=0` 不重发）。

---

## 3. 改动点汇总表（逐行）

| # | 文件 | 行号(约) | 改动 | 类型 | 行数 |
|:-:|:----|:--------:|:-----|:----|:----:|
| 1 | main.py | L3056 | `退回 🔄` handler 后插入 `_handle_reject` 调用 | +1 行 | 1 |
| 2 | main.py | 新增 ~L3107 | `_handle_reject()` 函数 | 新函数 | ~55 |
| 3 | main.py | L2505 | 全管线完成分支中插入归档调用 | +1 行 | 1 |
| 4 | main.py | 新增 ~L2870 | `_archive_pipeline()` 函数 | 新函数 | ~40 |
| 5 | main.py | 新增 ~L2910 | `_find_archive()` 辅助函数 | 新函数 | ~15 |
| 6 | main.py | L3476-3485 | `##status` 归档查找回退 | 修改 ~10 行 | 10 |
| 7 | main.py | L2478 | `_try_advance_pipeline` 中插入验证逻辑 | 新增 ~20 行 | 20 |
| 8 | main.py | 新增 ~L2930 | `_verify_sha_remote()` 异步验证函数 | 新函数 | ~30 |
| 9 | main.py | L612+ | `_pipeline_timeout_scan` 增强（重发+timeout标记） | 修改 ~30 行 | 30 |
| 10 | main.py | 新增 ~L2960 | `_auto_re_notify()` 重发函数 | 新函数 | ~35 |
| 11 | main.py | L3250 | `##archive` 命令注册 | +2 行 | 2 |
| 12 | main.py | 新增 ~L3340 | `_handle_hash_archive()` 函数 | 新函数 | ~35 |
| 13 | config.py | L107+ | 新增 `PIPELINE_OUTPUT_VERIFICATION/...RETRY/...MARK` | 新增 8 行 | 8 |
| 14 | main.py | help 文本 | `##archive` 帮助内容 | +1 行 | 1 |
| **合计** | | | | | **~248 行** |

---

## 4. 向后兼容性

| 场景 | 影响 | 说明 |
|:-----|:----:|:------|
| 旧 JSON 无 `reject_count` 字段 | ✅ | `getattr(ctx, "reject_count", 0)` → 0 |
| 旧 JSON 无 `reject_reason` 字段 | ✅ | `step.pop("reject_reason", None)` / `step.get("reject_reason", "")` |
| 旧 JSON 无 `status="timeout"` | ✅ | timeout 标记仅在新扫描过程中设置，旧 step 原样读取 |
| 旧 JSON 无 `re_notified` 字段 | ✅ | `step.get("re_notified")` → None/falsy → 跳过重发 |
| 旧管线已 completed | ✅ | 状态守卫在 `_handle_reject` 中拦截，不回退 |
| 归档后活跃列表变化 | ✅ | 归档仅移除已完成管线，不影响进行中的管线 |
| 旧管线 `##status` | ✅ | 未归档的从 `mgr.get()` 正常读取；已归档的从 archive 文件回查 |
| 旧 `PIPELINE_TIMEOUT_ALERT_MINUTES` | ✅ | 不动，R122 原有逻辑保留 |
| 已有 R115/R120/R123 逻辑 | ✅ | 验证只在 `_kv` 存在时触发，零侵入 |

---

## 5. 验收验证

### 5.1 需求 A — 驳回状态回退

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| A-1 | 发 `退回 🔄 R124 Step 4 — 原因` | `ctx.steps[2].status == "pending"`, Step 3~4 output=null |
| A-2 | 同上 | `ctx.steps[2]["reject_reason"] == "原因"` |
| A-3 | 发 `退回 🔄 R123 Step 4`（R123 已完成） | 忽略，status 不变 |
| A-4 | 回退后 PM 通知 | 通知含原因 + 退回 Step 信息 |
| A-5 | 连续退 4 次 | 第 4 次 `ctx.status == "stuck"`，不重置任何 step |
| A-6 | 退 `退回 🔄 R124 Step 4`（无 `—`） | reject_reason 取前 100 字符 |
| A-7 | 回退后是否自动派活 | 否（不调用 `_auto_dispatch`） |

### 5.2 需求 B — 管线自动归档

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| B-1 | 全 step done → pipeline_archive.json 新增记录 | 活跃列表中移除 |
| B-2 | 归档记录数据完整性 | 含 steps/artifacts/references/summary/archived_at |
| B-3 | `##archive##R124` 手动归档 | 归档成功，活跃列表移除 |
| B-4 | 归档后 `##status##R124` | 返回「已归档，数据在 pipeline_archive.json」 |
| B-5 | PM 收到归档通知 | `📦 R124 管线已完成并归档` |

### 5.3 需求 C — 产出验证

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| C-1 | `##sha=abc1234` (7 字符 hex) | `output["sha_validation"] == "valid_format"` |
| C-2 | `##sha=not-a-sha!@#$` | `output["sha_validation"] == "invalid_format"` |
| C-3 | 无 `##sha` | output 中无 sha_validation 字段 |
| C-4 | 任意验证情况 | 管线照常推进，不阻断 |
| C-5 | `PIPELINE_OUTPUT_VERIFICATION=1` | 远程 git 检查触发（异步，不阻塞） |
| C-6 | 远程 git 检查超时 | `sha_validation == "unchecked"` |

### 5.4 需求 D — 超时增强

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| D-1 | 30min 超时后 | `re_notified` 标记，bot 收到重发消息 |
| D-2 | 45min 超时后 | `step.status == "timeout"`，PM 收到通知 |
| D-3 | `PIPELINE_TIMEOUT_RETRY_MINUTES=0` | 不重发 |
| D-4 | timeout 后 `##advance` | 仍然可手动推进 |
| D-5 | 原有 30min 首次告警 | 完全保留，不破坏 |

### 5.5 回归验证

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| R-1 | 全 6 步自动派活 | 零断流，step 自动推进至完成 |
| R-2 | ruff lint | `ruff check server/ws_server/main.py` 通过 |
| R-3 | `pipeline_contexts.json` 旧数据加载 | 无报错，output/null/timeout_alerted 正常读取 |

---

## 6. 不做事项（明确排除）

| 排除项 | 理由 |
|:-------|:------|
| ❌ 修改 `pipeline_context.py` 数据结构 | 已有字段满足需求，新字段动态存取 |
| ❌ Git 自动检测推进 | 正交功能，R124 聚焦超时/重试/归档 |
| ❌ Bot 自动选择/角色热切换 | 超出 R124 范围 |
| ❌ 前端管线盘面大改 | 仅增加归档线和非活跃状态标记 |
| ❌ 修改 bot 回复协议格式 | 不新增前缀/命令，复用 `退回 🔄` |
| ❌ 跨 step 并行派活 | 需重新设计拓扑模型，R124 聚焦线性完成 |

---

## 7. 开放讨论

| # | 问题 | 建议 | 决策 |
|:-:|:-----|:-----|:----:|
| 1 | 归档路径 `/app/data/pipeline_archive.json` vs 同目录 `pipeline_contexts.json` 旁 | 建议与 `pipeline_contexts.json` 同目录（`config.DATA_DIR`） | 🔲 |
| 2 | `reject_count` 是否应持久化到 `PipelineContext` 字段？ | 建议 `getattr/setattr` 动态存取，不改 dataclass 定义。序列化时通过 `to_dict` 的 `**tags` 兜底 | 🔲 |
| 3 | `PIPELINE_OUTPUT_VERIFICATION` 默认值？ | 建议默认 `0`（关闭），远程 git 有额外延迟 | 🔲 |
| 4 | archive 文件并发写入安全？ | 单进程串行保存，无并发问题。归档点唯一（全 step done 后） | 🔲 |

---

> **审核记录：**
> - v1.0 提交审核：[2026-07-17]
