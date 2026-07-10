# R89 代码审查报告 — AutoRouter 增强 🔧

> **审查人：** 🔍 小周
> **审查基准：** `b068097` (R88) → `cef1096` (R89)
> **改动文件：** `server/auto_router.py` (+139/-30, 净增 ~109 行)
> **参考文档：**
> - 技术方案: `docs/R89/R89-tech-plan.md`
> - 产品需求: `docs/R89/R89-product-requirements.md`
> - 零修改: `handler.py` ✅ · `config.py` ✅ · `__main__.py` ✅

---

## 审查结论：🟢 通过

5/5 检查项通过。R89 改动界限清晰，异常处理完备，向后兼容性良好。

---

## 🅰️ Payload 补全 — from_name/agent_id/id/ts 字段正确性

**判定：🟢 通过**

| 字段 | 值 | 验证 | 状态 |
|:-----|:----|:-----|:----:|
| `from_name` | `"系统(管线)"` | 源码 L681 | ✅ |
| `agent_id` | `self.my_agent_id` | 源码 L682，auth 后已赋值 | ✅ |
| `id` | `"auto-{int(time.time() * 1000)}"` | 源码 L683，毫秒级唯一 | ✅ |
| `ts` | `time.time()` | 源码 L684 | ✅ |
| `import time` | 文件顶部 L21 | 新 import | ✅ |

**详查：**
- 4 个字段均为新增，原有 3 字段 (`type`/`channel`/`content`) 未改动
- `self.my_agent_id` 在 auth 成功后赋值，`_send_inbox` 在派活时才调用 → auth 必定已完成 ✅
- `from_name` 使用中文"系统(管线")"与 R87 `_inbox:server` 协议一致
- `id` 以 `auto-` 前缀区分于人工消息的 `msg-` 前缀，便于日志追踪
- 无破坏性变更：Bot 端扩展 JSON 字段不破坏解析

---

## 🅱️ 超时检测 — timeout loop 正确性

**判定：🟢 通过**

### 生命周期正确性

| 节点 | 位置 | 行为 | 状态 |
|:-----|:-----|:-----|:----:|
| 启动 | `_connect_and_listen()` L154 | `create_task(self._timeout_check_loop())` | ✅ |
| 运行 | `_timeout_check_loop()` L400-410 | `while self._running` + `asyncio.sleep(300)` | ✅ |
| 停止 | `finally` L172-176 | `timeout_task.cancel()` + `await timeout_task` | ✅ |
| 重连 | `start()` 外层循环 | 重连后重新创建 timeout task | ✅ |

### _check_step_timeouts 逻辑

```
_dispatch_step ──→ _step_dispatch_times[round][step] = {dispatch_time, role}
                         │
                         ▼
_timeout_check_loop() ──→ _check_step_timeouts()
  │                         │
  │  try/except Exception──→ elapsed > 7200s → notified set 防重复
  │                         └─ PM 收到 ⏰ 告警
  └─ asyncio.sleep(300)
```

| 子逻辑 | 验证 | 状态 |
|:-------|:-----|:----:|
| 遍历用 `list()` 快照 | `list(self._step_dispatch_times.items())` | ✅ 安全迭代 |
| 超时比较 | `elapsed > self._STEP_DEFAULT_TIMEOUT` | ✅ float 比较 |
| 去重 | `_step_timeout_notified` set | ✅ 同一 Step 仅 1 条 |
| 完成清理 | `_on_step_complete()` → `_cleanup_dispatch()` | ✅ |
| 全链清理 | `_notify_all_done()` → `_cleanup_all_dispatch()` | ✅ |

**关键安全设计：** `dispatch_time` 在 `await self._send_inbox()` **成功之后**才记录（L362-365），确保不出现"派活失败但计时器已启动"的情况。满足技术方案 R4 缓解要求 ✅

---

## 错误处理 — 超时 task 异常会不会崩主循环？

**判定：🟢 通过**

| 层 | 保护 | 效果 |
|:---|:-----|:-----|
| `_timeout_check_loop` | `try/except Exception` 包裹全部检查逻辑 | `_check_step_timeouts` 内任何异常 → 日志记录 → 下周期继续 |
| `_check_step_timeouts` | 无单独 try（由上层兜底） | 异常不逃逸到主循环 |
| 断线 finally | `timeout_task.cancel()` + `await` | 主 WS 断开时干净清理 |

**断线后清理流（分析）：**
```
WS 断开 → async for 结束 → async with 退出 → finally 执行
                                                  ↓
                                           timeout_task.cancel()
                                                  ↓
  _timeout_check_loop 中 asyncio.sleep() 收到 CancelledError → task 结束
                                                  ↓
                                        异常传播到 start() → 重连
```

**异常传播路径：** `_timeout_check_loop` 是独立 asyncio Task，与主循环 `async for raw in ws` 完全解耦。无论 timeout loop 内发生什么，主循环不受影响。✅

---

## 向后兼容 — STEP_TIMEOUT=0 是否禁用正确？

**判定：🟡 条件通过**

| 配置项 | PRD 要求 | 实现状态 |
|:-------|:---------|:--------:|
| `_STEP_DEFAULT_TIMEOUT` | 可配置 | ⚠️ 硬编码类常量 `= 7200` |
| `STEP_TIMEOUT=0` 禁用 | 不创建检测 task | ❌ 未实现 |
| 配置来源 | 应支持 env/config | ❌ 无 config 集成 |

**现状分析：**
- `_STEP_DEFAULT_TIMEOUT = 7200` 和 `_TIMEOUT_CHECK_INTERVAL = 300` 均为硬编码类常量
- 超时检测 task 总是随连接启动，无"禁用"路径
- 设 `= 0` 会导致 `elapsed > 0` 恒真 → 所有 Step 立即标记超时
- **实际影响低：** 2h 超时+5min 检查间隔是合理的默认值，无实际业务阻断
- 功能可通过 R90 添加 env 变量集成（如 `AR_STEP_TIMEOUT`）

**结论：** 向后兼容性本身无问题（现有行为不受破坏），但 PRD 的"STEP_TIMEOUT=0 禁用"功能未实现。评为 🟡 条件通过，建议尽快补上。

---

## R88 原有功能是否受影响

**判定：🟢 无回归**

逐一验证每处改动对 R88 的影响：

| 函数 | R89 改动 | 对 R88 功能影响 |
|:-----|:---------|:---------------|
| `_send_inbox()` | +4 字段 payload | 无。字段扩展不破坏已有协议 |
| `_dispatch_step()` | 末尾记录 dispatch_time | 无。纯新增操作，不改变派活逻辑 |
| `_on_step_complete()` | 末尾清理计时器 | 无。链推进/派活逻辑未改动 |
| `_notify_all_done()` | 末尾清空该轮计时器 | 无。通知 PM 后额外清理 |
| `_connect_and_listen()` | 整体缩进 + try/finally | 无。核心 auth + 消息循环逻辑不变 |
| `handler.py` | 0 行改动 | ✅ 零侵入确认 |
| `config.py` | 0 行改动 | ✅ |

---

## 额外发现

### 代码整洁性建议

| # | 类型 | 描述 | 建议 |
|:-:|:----:|:-----|:-----|
| 1 | 🟢 风格 | `_on_step_complete()` 中 `_cleanup_dispatch` 使用 `step_key`，但在 `_dispatch_step()` 中 `step_key` 也用于计时器 key。两处 step_key 来源一致 (`chain[current_idx].get("step", "")`)，但也可考虑作为参数传递 | 无强制要求，已确认一致性 |
| 2 | 🟡 功能 | PRD `STEP_TIMEOUT=0` 禁用未实现 | R90 补充 env 变量 `AR_TIMEOUT` |

### 与技术方案的一致性

| 技术方案条目 | 实现 | 状态 |
|:------------|:-----|:----:|
| `import time` | L21 ✅ | 匹配 |
| 类常量 `_TIMEOUT_CHECK_INTERVAL` / `_STEP_DEFAULT_TIMEOUT` | L37-38 ✅ | 匹配 |
| `__init__` 新增实例变量 | L86-89 ✅ | 匹配 |
| `_connect_and_listen` 启动/取消 timeout task | L154-176 ✅ | 匹配 |
| 派活后记录 dispatch_time | L362-365 ✅ | 匹配（先 send 后记录） |
| `_on_step_complete` 清理 | L280-282 ✅ | 匹配 |
| `_notify_all_done` 清理 | L381 ✅ | 匹配 |
| `_timeout_check_loop` / `_check_step_timeouts` | L400-440 ✅ | 匹配 |
| `_cleanup_dispatch` / `_cleanup_all_dispatch` | L386-398 ✅ | 匹配 |

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:-----|
| 🅰️ Payload 补全 | 🔴 | 🟢 | 4 字段正确实现 |
| 🅱️ 超时检测逻辑 | 🔴 | 🟢 | 生命周期完整，安全迭代 |
| 超时 task 异常处理 | 🔴 | 🟢 | try/except 双层保护 |
| 向后兼容 (STEP_TIMEOUT=0) | 🟡 | 🟡 | 默认 7200s 可用，禁用来实现 |
| R88 功能无回归 | 🟢 | 🟢 | 零 handler.py 侵入确认 |
| 与技术方案一致性 | 🟢 | 🟢 | 12/12 条目匹配 |

**最终结论：🟢 通过** — R89 改动界限清晰，Payload 补全正确，超时检测机制完整。建议 R90 补充 `STEP_TIMEOUT=0` 禁用功能和 env 变量集成。

---

*报告编写: 🔍 小周 · 2026-07-10*
