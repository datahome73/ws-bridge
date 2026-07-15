# R119 代码审查报告 — 自动派活全流程 5 项修复

> **审查人：** 🔍 小周
> **审查目标：** 5 fix commits on `dev`（f560daf / 54cc097 / 59acf9a / bff10b5 / 5c9e6f0）
> **文件：** `server/ws_server/main.py` + `server/ws_server/__main__.py`
> **参考文档：** [技术方案](./TECH_PLAN.md)，[实现说明](./IMPLEMENTATION_NOTES.md)
> **结论：** ✅ **通过 — 0 Critical, 1 Observation, 建议合并**

---

## 一、审查清单逐项验证

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| 1 | 重启后 Step 1 不丢失 | current_step 保持为 2 | ✅ | f560daf: `mgr.save()` 在 ctx.current_step=2 后落盘 |
| 2 | 重启后派活自动恢复 | 日志 [R119] 恢复派活 | ✅ | 54cc097: `_restore_pipeline_dispatches()` + __main__.py on_startup |
| 3 | 恢复派活入重试队列 | 等 bot 连上再发 | ✅ | 59acf9a: `_enqueue_retry` 替代直接 `ensure_future(_auto_dispatch)` |
| 4 | await 修复 | _restore_pipeline_timers 加 await | ✅ | 59acf9a: `await _restore_pipeline_timers()` |
| 5 | 重复派活保护 | Step 标记 in_progress | ✅ | bff10b5: `next_step_info["status"] = "in_progress"` + mgr.save() |
| 6 | 派活消息路由正确 | type=broadcast + channel=_inbox:{target} | ✅ | 5c9e6f0: type message->broadcast, channel _inbox:server->_inbox:{target} |
| 7 | in_progress 在重启后也被恢复 | _restore_pipeline_dispatches 处理 in_progress | ✅ | 5c9e6f0: `status not in ("pending", "in_progress")` |

---

## 二、文件改动总览

| Fix | Commit | 文件 | 行数 |
|:---:|:-------|:-----|:----:|
| 1 | f560daf | main.py | **+5** |
| 2 | 54cc097 | main.py + __main__.py | **+39** |
| 3 | 59acf9a | main.py | **+2 -2** |
| 4 | bff10b5 | main.py | **+7** |
| 5 | 5c9e6f0 | main.py + __main__.py | **+12 -4** |

**总计：** 5 个 fix，2 文件，**+65 -6 行**

---

## 三、发现项

### 🔴 Critical: 无

### 🔴 Concern: _restore_pipeline_dispatches 初始版本直接调用 _auto_dispatch（已修复）

**位置：** Fix 2 (54cc097) → Fix 3 (59acf9a)

**现象：** v1 的 `_restore_pipeline_dispatches()` 直接 `asyncio.ensure_future(_auto_dispatch(ctx, step_num))`，但启动时 bot 可能尚未建立 WS 连接，派活消息必然失败。

**修复：** Fix 3 改为 `_enqueue_retry(ctx, step_num)`，消息在 bot 连上后由重试循环发送。✅ 已回改。

### 🟡 Observation 1: Fix 3 (await) 与 Fix 5 (restore) 的先后依赖

**位置：** 59acf9a vs 5c9e6f0

**分析：** Fix 3 将 recovering dispatch 改为 `_enqueue_retry`，但 Fix 5 又将 `_restore_pipeline_dispatches` 的 filter 从 `!= "pending"` 扩展为 `not in ("pending", "in_progress")`。这两个 fix 的依赖关系：
- 如果没有 Fix 3 (enqueue_retry)，扩展为 in_progress 时 recover 会直接调 _auto_dispatch，在 bot 未连上时失败
- Fix 3 先提交、Fix 5 后提交，顺序正确 ✅

### 🟡 Observation 2: __main__.py logging.basicConfig force=True

**位置：** 5c9e6f0 __main__.py

`logging.basicConfig(level=logging.INFO, ..., force=True)` 强制重置所有 logger。如果系统中有其他自定义 handler（如文件日志），会被覆盖。

**分析：** ws-bridge 容器日志当前仅用 stdout handler，无文件日志。force=True 在新创建的 logger 上不会造成 side effect。但如果有后续开发添加文件日志 handler，此配置会静默覆盖。

**建议：** 🟢 非阻塞。当前环境下 effect 正确。

### 💡 Suggestion: __main__.py on_startup 顺序

app.on_startup 按注册顺序执行。`_restore_dispatches` 依赖 retry loop 已启动。当前代码中 retry loop 在 `_restore_dispatches` 之前注册，顺序正确。建议增加注释标注此依赖。

---

## 四、功能完整性验证

### 4.1 断点链路覆盖

| 断点场景 | 触发路径 | 修复 | 覆盖 |
|:---------|:---------|:-----|:----:|
| 容器重启后 Step 1 状态丢失 | _handle_hash_start → mgr.save() | Fix 1 | ✅ |
| 容器重启后 RUNNING 管线无派活 | on_startup → _restore_pipeline_dispatches | Fix 2 | ✅ |
| 启动时 bot 未连上，消息发不出 | → _enqueue_retry → 重试队列 | Fix 3 | ✅ |
| handle_broadcast 定时器未 await | await _restore_pipeline_timers | Fix 3 | ✅ |
| 派活成功后续重启重复派活 | → in_progress + save | Fix 4 | ✅ |
| 派活消息 type=message 被静默丢弃 | → type=broadcast + channel=_inbox:{target} | Fix 5 | ✅ |
| in_progress 状态下重启后不恢复 | → filter 扩展为 (pending, in_progress) | Fix 5 | ✅ |

### 4.2 消息路由验证

| 维度 | Before (R118) | After (R119 Fix 5) | 正确性 |
|:-----|:-------------|:--------------------|:------:|
| type | "message" (bot 网关跳过) | "broadcast" (bot 网关处理) | ✅ |
| channel | "_inbox:server" (server 收件箱) | "_inbox:{target_agent_id}" (目标 bot 收件箱) | ✅ |
| to_agent | target_agent_id | target_agent_id (不变) | ✅ |
| sent 返回值 | sent=1 (WS 发送成功) | sent=1 (bot 实际收到) | ✅ |

**根因正确性：** Fix 5 的 commit message 精准描述了根因：`_send_to_agent` 返回 sent=1 是因为 WebSocket 发送成功（找到连接→写 socket），但 bot 的 gateway-plugin 只处理 `type='broadcast'`，`type='message'` 被 `_handle_ws_message` 跳过。这不是 `_send_to_agent` 的错，而是 payload 格式不匹配 bot 协议。

### 4.3 并发安全

| 风险点 | 分析 | 安全 |
|:-------|:-----|:----:|
| _restore_pipeline_dispatches 遍历 mgr.get_all_active() 时可能有其他协程修改 | get_all_active() 返回快照列表，遍历安全 | ✅ |
| _enqueue_retry 中的 _pending_retries 字典 | round_name 检查防重复入队 | ✅ |
| mgr.save() 在异常时被 except pass 吞掉 | 不影响主流程，重试队列会补发 | ✅ |

### 4.4 回归风险

| 修改 | 回归风险 | 理由 |
|:-----|:---------|:-----|
| Fix 1: Step 1 落盘 | 🟢 低 | 纯新增 try/save，append 在已有代码之后 |
| Fix 2: 恢复派活函数 | 🟢 低 | 纯新增函数 + on_startup 注册 |
| Fix 3: enqueue_retry + await | 🟢 低 | 修改仅 2 行：_auto_dispatch → _enqueue_retry，加 await |
| Fix 4: in_progress 标记 | 🟢 低 | 纯新增代码，if sent>0 分支内 |
| Fix 5: type/channel 修改 + filter 扩展 | 🟢 低 | payload 字段修改是 R118 同代码区域，无其他消费者 |

---

## 五、汇总 & 结论

### 亮点

- **根因追溯完整：** 5 个 fix 覆盖了从启动恢复 → 状态持久化 → 消息路由的全链路 7 个断点
- **R117 修复的延续：** `_resolve_card_key_to_ws_id()` 桥接正确（R117），但 `_auto_dispatch` 的 payload 格式不匹配 bot 协议（R119 Fix 5）。两个修复合在一起链路才完整
- **防御性设计：** 重试队列 (`_enqueue_retry`) 确保 bot 上线后会补发；in_progress 标记防止重复发送
- **启动恢复闭环：** `_restore_pipeline_dispatches` + `on_startup` 确保容器重启不丢派活
- **Fix chain 提交顺序正确：** Fix 2→3→5 的依赖关系被正确维护

### 结论

> ✅ **审查通过。** 5 个 fix 均正确修复了生产验证中发现的实际断点。核心发现（Fix 5: type/channel 不匹配 bot 协议）是 R117 投产失败的根本原因。改动范围精确、回归风险低、防御措施完备。

---

**审查日期：** 2026-07-15
**审查人：** 🔍 小周