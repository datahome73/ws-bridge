# R128 需求文档 — Bug + Critical 修复轮

> **轮次：** R128
> **类型：** Bug 修复轮（含 R127 Critical 阻塞缺陷）
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 草稿待审

---

## §1 背景

R127 管线流转过程中发现了 4 个 Bug，均影响管线自动流转的可靠性和可观测性。本轮集中修复。

### Bug 全景

| # | 问题 | 严重度 | 来源 | 影响范围 | 修复量 |
|:-:|:-----|:-----:|:-----|:---------|:------:|
| **C-1** | `engine` 局部变量永远为 None，所有 ## 命令无声失败 | 🔴 Critical | R127 QA | 容器启动即挂 | ~10 行 |
| **C-3** | `engine._retry_loop()` 在 engine=None 时崩溃 | 🔴 Critical | R127 QA | 容器启动即挂 | 1 行 |
| **B-1** | Web 端派活消息显示两条（经理+系统） | 🔴 P1 | 实测发现 | Web 端消息列表 | 1 行删除 |
| **B-3** | `##status` 缺 `in_progress` 图标，已派活显示 ⬜ | 🟡 P2 | 实测发现 | `##status` 命令输出 | 1 行新增 |
| **B-4** | 完成消息格式严格正则，bot 偏差即静默不推进 | 🟡 P2 | 实测发现 | 管线自动推进 | ~20 行 |
| **B-2** | 离线 bot 派活丢失，重试队列不够可靠 | 🟡 P2 | 实测发现 | 离线场景派活 | ~25 行 |

> **注意：** 按实际影响面排序。B-2 的修复涉及重试队列逻辑，风险相对较高，优先保障 B-1/B-3/B-4。

---

## §2 Bug 详述

### B-1 — 派活消息在 Web 端显示两条

**现象：** Web 端每个 dispatch 出现两条消息：一条显示「经理 → bot」，一条显示「系统 → bot」。内容相同，发送者不同。

**根因：** `_auto_dispatch()`（L3118-3131）和 `_send_to_agent()`（L2505-2516）都调用了 `ms.save_message()` 持久化同一条派活消息：

```
_auto_dispatch()
  ├─ ms.save_message(... from_name="小谷")   ← 1 次保存
  └─ _send_to_agent()
       ├─ ws.send(payload)                   ← 实际发 WS 消息
       └─ ms.save_message(... from_name="系统") ← 冗余保存
```

**修复：** 删除 `_auto_dispatch()` 中的 `ms.save_message` 调用（L3118-3131），保留 `_send_to_agent()` 中的系统身份持久化。

**验证：** Web 端每个 dispatch 只显示一条「系统 → bot」。

---

### B-3 — `##status` 缺 `in_progress` 图标

**现象：** Step 已成功派活（`_auto_dispatch` 将 status 设为 `"in_progress"`），但 `##status` 输出仍显示 `⬜`，看起来跟「未派活」一样。

**根因：** `_handle_hash_status()` 的 `status_icons` 字典（L3667）只有 `pending/active/done/failed/skipped`，没有 `in_progress`：

```python
status_icons = {
    "pending": "⬜",
    "active": "🟢",
    "done": "✅",
    # "in_progress" ❌ 缺失
}
```

不匹配的 key 回退到默认 `⬜`，与 pending 混淆。

**修复：** `status_icons["in_progress"] = "🔄"` — 一行代码。

**验证：** `##status` 中已派活的 step 显示 `🔄`，与 pending(`⬜`) 可区分。

---

### B-4 — 完成消息格式容错不足

**现象：** Bot 发送完成消息，`_try_advance_pipeline()` 因正则不匹配而静默忽略，管线不推进、不报错、不提示。

**根因：** 正则要求消息**以** `已完成 ✅ R{N} Step {N}` 精确开头（`re.match` + 精确格式）。bot 实际发出的消息可能有：
- 前导空格 / 多余前缀
- 不同标点（全角/半角冒号）
- 不同 emoji 变体（✅ vs ✔️）
- 不同语序

```python
# 当前 — 严格匹配：必须以这串开头
m = re.match(r"已完成 ✅ R(\d+) Step (\d+)", content)
```

**修复：** 两处放宽：
1. 改用 `re.search` 替代 `re.match`，允许前后有额外文本
2. 增加容差变体匹配：`已完成` 或 `完成`，`✅` 或 `✔️`，`Step` 或 `step`

```python
# 修复后
m = re.search(r"(?:已完成|完成)\s*[✅✔️]\s*R(\d+)\s*[Ss]tep\s*(\d+)", content)
```

**验证：** bot 发送以下格式均能被识别：
- `已完成 ✅ R128 Step 4`
- `✅ 已完成 R128 Step 4，已推 dev`
- `完成 ✔️ R128 step 4`

---

### B-2 — 离线 bot 派活丢失

**现象：** 目标 bot 离线时 `_auto_dispatch` 调用 `_send_to_agent` 返回 sent=0，消息进入 `_enqueue_retry` 重试队列。但重试队列可靠性不足，消息可能永久遗失。

**根因：** `_enqueue_retry` 的重试机制：
- 首轮重试间隔 60s（过长）
- 无超限淘汰/降级机制（无限重试）
- 无 PM 通知（PM 不知道 retry 失败）

```python
_pending_retries[round_name] = {
    "ctx": ctx,
    "step_num": step_num,
    "retry_count": 0,
    "next_retry_at": time.time() + 60,    # ⬅ 60s 太长了
    "notify_sent": False,
}
```

**修复：**
1. 首轮重试间隔从 60s 缩短到 **15s**
2. 增加退避：15s → 30s → 60s → 120s，**3 次后通知 PM**
3. 连续 5 次失败后标记为 `retry_exhausted` 并通知 PM（不再无限重试）

**验证：** 离线 bot 重建连接后能在 15s 内收到重试派活。3 次失败后 PM 收到通知。

---

### C-1 — `engine` 变量永远为 None，所有 ## 命令无声失败

**现象：** 容器启动后，`##start` / `##status` / `##stop` / `##advance` 全部无声失败。7 个 bot 断连，服务不可用。

**根因：** `main.py` L42 定义 `engine: Optional[PipelineEngine] = None` 模块级变量，通过 `_ensure_engine()` 惰性初始化。但 `scenario_matcher` 的 `_sm_handle_*` 等 handler 直接引用模块级 `engine` 而非调用 `_ensure_engine()`。若 `##` 命令在 `_ensure_engine()` 首次调用之前到达，`engine` 为 None → 调用 `engine.xxx()` 时抛出 `AttributeError`。

```python
# main.py L42
engine: Optional[PipelineEngine] = None     # 永远是 None 直到 _ensure_engine() 被调

# scenario_matcher 中直接引用 engine（而非 _ensure_engine()）
_sm._engine = engine                        # 赋值时 engine 可能还是 None
```

**修复：** 两处修复：
1. `__main__.py` 中启动 `on_startup` 时先调用 `_ensure_engine()` 确保 engine 已初始化
2. `_sm._engine = engine` 改为 `_sm._engine = _ensure_engine()`，确保注入的是已初始化的实例

**验证：** 容器启动后 `##status` 正常返回，所有 `##` 命令正常工作。

---

### C-3 — `engine._retry_loop()` 在 engine=None 时崩溃

**现象：** 容器启动时 aiohttp `on_startup` 事件触发 `_start_retry_loop` → `asyncio.create_task(engine._retry_loop())` → `engine` 为 None → `AttributeError` → 容器启动失败。

**根因：** `__main__.py` L840 直接从 `main` 模块导入 `engine` 变量并调用其方法，未先确保 engine 已初始化：

```python
# __main__.py L838-840
async def _start_retry_loop(app):
    from .main import engine                # engine 可能是 None
    asyncio.create_task(engine._retry_loop())  # ❌ None._retry_loop() 崩溃
```

**修复：** `from .main import engine` 改为 `from .main import _ensure_engine; engine = _ensure_engine()`。

**验证：** 容器正常启动，retry 循环日志 `[R118] retry loop started` 出现。

---

## §3 改动范围

| 文件 | 修改 | 涉及 Bug/Defect | 行数 |
|:-----|:-----|:---------|:----:|
| `server/ws_server/main.py` | `_sm._engine = engine` → `_sm._engine = _ensure_engine()` | C-1 | +1 |
| `server/ws_server/__main__.py` | `from .main import engine` → `from .main import _ensure_engine; engine = _ensure_engine()` (2 处) | C-1, C-3 | ~+4 |
| `server/ws_server/main.py` | 删除 `_auto_dispatch` 中的 `ms.save_message` 调用 | B-1 | -12 |
| `server/ws_server/main.py` | `status_icons` 加 `"in_progress": "🔄"` | B-3 | +1 |
| `server/ws_server/main.py` | `_try_advance_pipeline` 正则放宽 + 变体匹配 | B-4 | ~+15 |
| `server/ws_server/main.py` | `_enqueue_retry` + `_retry_scanner` 重试优化 | B-2 | ~+25 |
| **合计** | | | **~+34 行** |

> 净增 ~29 行（4 处修改，全部在 `main.py`）。

---

## §4 验收标准

### C1-N: C-1 修复（Critical）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| C1-1 | `_sm._engine` 注入的是 `_ensure_engine()` 返回值而非模块级 `engine` 变量 | 功能 |
| C1-2 | 容器启动后 `##status` 正常返回，不出现无声失败 | 验收 |

### C3-N: C-3 修复（Critical）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| C3-1 | `__main__.py` on_startup 中先调用 `_ensure_engine()` 再访问 `engine._retry_loop()` | 功能 |
| C3-2 | 容器正常启动，retry 循环日志 `[R118] retry loop started` 出现 | 验收 |
| C3-3 | `_restore_dispatches` 同理使用 `_ensure_engine()` 而非直接引用 `engine` | 功能 |

### B1-N: B-1 修复（P1）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| B1-1 | `_auto_dispatch` 中不再调用 `ms.save_message` | 功能 |
| B1-2 | Web 端每个 dispatch 只显示一条消息（系统 → bot） | 验收 |

### B3-N: B-3 修复（P2）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| B3-1 | `status_icons` 字典包含 `"in_progress"` key | 功能 |
| B3-2 | 已派活 step 在 `##status` 中显示 `🔄` 而非 `⬜` | 验收 |

### B4-N: B-4 修复（P2）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| B4-1 | `已完成 ✅ R128 Step X` 能被识别推进 | 功能 |
| B4-2 | `✅ 已完成 R128 Step X，已推 dev` 能被识别推进 | 功能 |
| B4-3 | `完成 ✔️ R128 step X` 能被识别推进 | 功能 |
| B4-4 | 完全不匹配的消息（`搞定了 R128 Step X`）仍被忽略（无误推进） | 回归 |

### B2-N: B-2 修复（P2）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| B2-1 | 首轮重试间隔为 15s（原 60s） | 功能 |
| B2-2 | 3 次重试失败后通知 PM | 功能 |
| B2-3 | 连续 5 次重试失败后标记 exhausted 停止重试（不再无限循环） | 功能 |

### RV-N: 回归验证（P0）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| RV-1 | `py_compile` 全量零错误 | 编译 |
| RV-2 | `##start` / `##status` / `##advance` / `##archive` 全部正常 | 回归 |

---

## §5 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不改 R127 pipeline_engine.py 的业务逻辑** | 只修 engine 初始化方式，不改 extract 后的 PipelineEngine 方法体 |
| ❌ | **不改 `_try_advance_pipeline` 的业务逻辑** | B-4 只放宽正则，不改推进逻辑 |
| ❌ | **不新增重试持久化** | B-2 重试队列仍在内存中，持久化是后续轮次的事 |

---

---

## §6 验收检查表

### 文件改动清单

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| ✅ 修改 | `server/ws_server/main.py` | ~30 行 |
| ✅ 修改 | `server/ws_server/__main__.py` | ~4 行 |
| ❌ 不碰 | 其他文件 | — |

### 验收计数

| 分组 | Critical | P0 | P1 | P2 | 合计 |
|:-----|:--------:|:--:|:--:|:--:|:----:|
| C-1 | 2 | — | — | — | 2 |
| C-3 | 3 | — | — | — | 3 |
| B-1 | — | — | 2 | — | 2 |
| B-3 | — | — | — | 2 | 2 |
| B-4 | — | — | — | 4 | 4 |
| B-2 | — | — | — | 3 | 3 |
| RV | — | 2 | — | — | 2 |
| **合计** | **5** | **2** | **2** | **9** | **18** |
