# R128 技术方案 — Bug + Critical 修复轮

> **轮次：** R128
> **类型：** 代码修复（Genre B — 多位置修复）
> **版本：** v1.0
> **日期：** 2026-07-19
> **角色：** 📐 架构师（小开）
> **状态：** ✅ 待审核

---

## §1 概述

R127 管线流转测试中发现 6 个 Bug，影响管线自动流转的可靠性和可观测性。本轮集中修复，全部涉及 `server/ws_server/main.py`（2 处）和 `server/ws_server/__main__.py`（1 处），总计 ~34 行净增。

### 1.1 Bug 全景

| # | 问题简述 | 严重度 | 文件 | 行数 | 类型 |
|:-:|:---------|:------:|:----|:----:|:-----|
| **B-1** | 派活消息在 Web 端显示两条（经理+系统） | 🔴 P1 | main.py | -12 | 冗余保存 |
| **B-3** | `##status` 缺 `in_progress` 图标，已派活显示 ⬜ | 🟡 P2 | main.py | +1 | 字典缺失 |
| **B-4** | 完成消息正则严格，bot 偏差即静默不推进 | 🟡 P2 | main.py | ~+15 | 正则放宽 |
| **B-2** | 离线 bot 派活丢失，重试队列不够可靠 | 🟡 P2 | main.py | ~+25 | 重试优化 |
| **C-1** | `engine` 注入位置不当，## 命令无声失败 | 🔴 Critical | main.py | +1 | 初始化修复 |
| **C-3** | `engine._retry_loop()` 在 engine=None 时崩溃 | 🔴 Critical | __main__.py | +4 | 初始化修复 |

### 1.2 修复策略

```
按风险排列（低→高）
├── B-3: status_icons +1 行字典添加   → 零风险，直接改
├── B-1: ms.save_message -12 行删除    → 低风险，确认删除正确块
├── B-4: 正则放宽 15 行                → 中风险，需验证不误匹配
├── B-2: 重试退避优化 25 行            → 中风险，需验证退避超限逻辑
├── C-1: engine 注入修复 1 行          → 低风险，确保启动时序
└── C-3: __main__.py 初始化修复 4 行   → 低风险，确保启动时序
```

---

## §2 问题根因与修复详述

### 2.1 B-1 — 派活消息在 Web 端显示两条

**现象：** Web 端每个 dispatch 出现两条消息：一条显示「经理 → bot」，一条显示「系统 → bot」。内容相同，发送者不同。

**根因分析：** `_auto_dispatch()`（L3041）和 `_send_to_agent()`（L2487）各调用了一次 `ms.save_message()`：

```
_auto_dispatch()
  ├─ ms.save_message(from_name="小谷")    ← L3120-3129  第 1 次保存
  └─ _send_to_agent()
       ├─ ws.send(payload)                 ← 实际发 WS 消息
       └─ ms.save_message(from_name="系统") ← L2507-2516  第 2 次保存
```

两次持久化写入同一消息数据库，Web 端查询时返回两条内容相同但发送者不同的记录。

**修复：** 删除 `_auto_dispatch()` 中的 `ms.save_message` 调用块（L3118-3131）。

```diff
     # ── R109 修复: 派活消息落库 ──
-    try:
-        ms.save_message(
-            msg_id=payload["id"],
-            msg_type="broadcast",
-            from_agent=payload["agent_id"],
-            from_name=payload["from_name"],
-            content=content,
-            ts=payload["ts"],
-            data_dir=config.DATA_DIR,
-            channel=f"_inbox:{target_agent_id}",
-        )
-    except Exception:
-        pass  # 入库失败不阻塞派活

     sent = await _send_to_agent(target_agent_id, payload)
```

**例化后的代码：**

```python
    sent = await _send_to_agent(target_agent_id, payload)
    logger.info(...)
```

**验证：** Web 端每个 dispatch 只显示一条「系统 → bot」。`_send_to_agent` 中的 `ms.save_message` 保留，确保消息入库。

---

### 2.2 B-3 — `##status` 缺 `in_progress` 图标

**现象：** Step 已成功派活（`_auto_dispatch` 将 status 设为 `"in_progress"`），但 `##status` 输出仍显示 `⬜`，看起来跟未派活一样。

**根因分析：** `_handle_hash_status()` 的 `status_icons` 字典（L3638-3644）只有 `pending/active/done/failed/skipped`，没有 `in_progress`：

```python
status_icons = {
    "pending": "⬜",
    "active": "🟢",
    "done": "✅",
    "failed": "❌",
    "skipped": "⏭",
    # "in_progress" ❌ 缺失 — 回退到默认 ⬜
}
```

L3658 `icon = status_icons.get(st, "⬜")` 中对不匹配的 key 回退到默认 `⬜`，与 `pending` 状态无法区分。

**修复：** 在 `status_icons` 字典中新增一行：

```diff
     status_icons = {
         "pending": "⬜",
         "active": "🟢",
+        "in_progress": "🔄",
         "done": "✅",
         "failed": "❌",
         "skipped": "⏭",
     }
```

**验证：** `##status` 中已派活但未完成的 step 显示 `🔄`，与 pending(`⬜`) 可明显区分。

---

### 2.3 B-4 — 完成消息格式容错不足

**现象：** Bot 发送完成消息后，`_try_advance_pipeline()` 因正则不匹配而静默忽略，管线不推进、不报错、不提示。用户无任何反馈。

**根因分析：** L2561 的正则要求消息**以** `已完成 ✅ R{N} Step {N}` 精确开头：

```python
m = re.match(r"已完成 ✅ R(\\d+) Step (\\d+)", content)
```

`re.match` 锚定在字符串开头。bot 实际发出的消息可能因以下原因不匹配：

| 偏差类型 | 示例 | 原因 |
|:---------|:-----|:-----|
| 前导空格 | ` 已完成 ✅ R128 Step 4` | bot 编辑疏忽 |
| emoji 变体 | `已完成 ✔️ R128 Step 4` | 多平台 emoji 渲染差异 |
| 语序变化 | `✅ 已完成 R128 Step 4` | Habitica 同步格式 |
| 大小写 | `已完成 ✅ R128 step 4` | 自动补全不一致 |
| 前缀追加 | `已完成 ✅ R128 Step 4，已推 dev` | AI 自然输出 |

**修复：** 将 L2561 的单行正则替换为容错版本：

```diff
-    m = re.match(r"已完成 ✅ R(\\d+) Step (\\d+)", content)
+    m = re.search(r"(?:已完成|完成)\\s*[✅✔️]\\s*R(\\d+)\\s*[Ss]tep\\s*(\\d+)", content)
```

变化说明：

| 维度 | 原正则 | 新正则 |
|:-----|:-------|:-------|
| 锚定方式 | `re.match`（从头匹配） | `re.search`（全文搜索） |
| 动词 | 仅 `已完成` | `已完成` 或 `完成` |
| emoji | 仅 `✅` | `✅` 或 `✔️` |
| 空格 | 精确空格 | `\s*` 任意空白 |
| 大小写 | `Step` 大写 | `[Ss]tep` 大小写均可 |

**验证矩阵：**

| 消息格式 | 预期结果 | 说明 |
|:---------|:--------:|:-----|
| `已完成 ✅ R128 Step 4` | ✅ 推进 | 标准格式，向后兼容 |
| `✅ 已完成 R128 Step 4，已推 dev` | ✅ 推进 | 常见变体 |
| `完成 ✔️ R128 step 4` | ✅ 推进 | emoji+大小写都不同 |
| `已完成 ✅ R128 Step 4##sha=abc1234` | ✅ 推进 | 含 key=value 参数 |
| `搞定了 R128 Step 4` | ❌ 忽略 | 完全不匹配，无误推进 |
| `已完成 ✅ R129 Step 2 测试完毕` | ✅ 推进 | 末尾有额外文本 |

**不做：** 不修改 `_handle_reject` 的退回正则（L3163），因为 `退回 🔄` 格式受 bot 模板管控，偏差少且 PM 人工介入纠正。

---

### 2.4 B-2 — 离线 bot 派活重试不够可靠

**现象：** 目标 bot 离线时 `_auto_dispatch` 调用 `_send_to_agent` 返回 `sent=0`，消息进入 `_enqueue_retry`。但重试队列有 3 个问题：

| 问题 | 当前值 | 影响 |
|:-----|:------:|:-----|
| 首轮重试间隔过长 | 60s | bot 刚断线时 60s 无任何动作，用户体验差 |
| 退避策略固定 | 每次 60s | 连续 5 次间隔相同，无指数退避 |
| PM 通知不足 | 仅 1 次 | 第 1 次失败通知后，后续失败静默 |

**根因分析：**

`_enqueue_retry`（L2788-2800）硬编码 `next_retry_at: time.time() + 60`：

```python
_pending_retries[round_name] = {
    "ctx": ctx,
    "step_num": step_num,
    "retry_count": 0,
    "next_retry_at": time.time() + 60,   # ⬅ 固定 60s
    "notify_sent": False,
}
```

`_retry_loop`（L2753-2785）中，重试失败后再次 `+ 60`；`notify_sent` 只发一次：

```python
else:
    entry["next_retry_at"] = time.time() + 60    # ⬅ 每次失败都是 60s
```

**修复：** 三处修改：

**① `_enqueue_retry` — 首轮间隔 15s：**

```diff
     _pending_retries[round_name] = {
         "ctx": ctx,
         "step_num": step_num,
         "retry_count": 0,
-        "next_retry_at": time.time() + 60,
+        "next_retry_at": time.time() + 15,
         "notify_sent": False,
     }
```

**② `_retry_loop` — 指数退避 + 3 次通知 PM：**

```diff
             else:
-                entry["next_retry_at"] = time.time() + 60
+                # 指数退避: 15s → 30s → 60s → 120s → 240s (最后 1 次不超 120s)
+                wait = min(15 * (2 ** entry["retry_count"]), 120)
+                entry["next_retry_at"] = time.time() + wait
-                if not entry.get("notify_sent"):
+                if entry["retry_count"] >= 3 and not entry.get("notify_sent"):
                     entry["notify_sent"] = True
                     asyncio.ensure_future(
                         _notify_pm(ctx, step_num, "retrying",
-                                   f"尝试 {entry['retry_count']+1}/5"))
+                                   f"尝试 {entry['retry_count']+1}/5，退避 {wait}s"))
```

**③ `_retry_loop` — 日志消息更新（反映新的退避间隔）：**

```diff
-                logger.info("[R118] 重试排队: %s step%d 等待 60s",
-                            round_name, step_num)
+                logger.info("[R128] 重试排队: %s step%d 等待 %ds (尝试 %d/5)",
+                            round_name, step_num, wait, entry["retry_count"])
```

**退避表：**

| 重试次数 | 间隔 | 累计时间 | 行为 |
|:--------:|:----:|:--------:|:-----|
| 1 | 15s | 15s | 首次重试 |
| 2 | 30s | 45s | 二次重试 |
| 3 | 60s | 105s | 三次 → 通知 PM |
| 4 | 120s(上限) | 225s | 四次 |
| 5 | 120s(上限) | 345s | 五次 → exhausted，通知 PM failed |

**验证：** 离线 bot 重连后 15s 内收到重试派活。3 次失败（~105s）后 PM 收到通知。5 次失败（~345s）后停止重试并通知 PM。

---

### 2.5 C-1 — `engine` 变量永远为 None（R127 集成 bug）

**现象：** 容器启动后，`##start` / `##status` 等所有 `##` 命令无声失败，返回空回复或无响应。

**根因分析：** 此 bug 在 R127 提取后才会出现。R127 将 `scenario_matcher.handle_hash_cmd` 中的 `from .main import _handle_hash_*` 改为通过 `engine` 实例调用。但 `engine` 初始化依赖 `_ensure_engine()` 惰性初始化函数，而 scenario_matcher 的 handler 在 `_ensure_engine()` 首次调用前就可能触发。

```python
# R127 后的 main.py
_engine: Optional[PipelineEngine] = None     # 模块级变量

def _ensure_engine() -> PipelineEngine:
    global _engine
    if _engine is None:
        _engine = PipelineEngine(...)
    return _engine

# 注册规则时注入 engine 引用
_sm._engine = _engine                          # ❌ 此时 _engine 还是 None！
```

**修复（在 R127 骨架集成时同步实施）：** 在 `__main__.py` 的 `on_startup` 中先调用 `_ensure_engine()` 确保 engine 已初始化，再将 `_sm._engine = _ensure_engine()` 确保注入的是已初始化的实例。

```python
# main.py — rule registration area (~L4817)
_sm._engine = _ensure_engine()  # 而非 _sm._engine = _engine
```

**验证：** 容器启动后 `##status` 正常返回。所有 `##` 命令正常工作。

---

### 2.6 C-3 — `engine._retry_loop()` 在 engine=None 时崩溃（R127 集成 bug）

**现象：** 容器启动时 aiohttp `on_startup` 事件触发 `_start_retry_loop` → `asyncio.create_task(engine._retry_loop())` → `engine` 为 None → `AttributeError` → 容器启动失败。

**根因分析：** `__main__.py` L838-841 直接从 `main` 模块导入全局变量 `engine`，未确保已初始化：

```python
async def _start_retry_loop(app):
    from .main import engine                # engine 可能是 None
    asyncio.create_task(engine._retry_loop())  # ❌ None._retry_loop() → AttributeError
```

**修复：** 改为使用 `_ensure_engine()` 安全获取实例：

```diff
 async def _start_retry_loop(app):
-    from .main import engine
+    from .main import _ensure_engine
+    engine = _ensure_engine()
     asyncio.create_task(engine._retry_loop())
     logger.info("[R118] retry loop started")
```

同理修复 `_restore_dispatches`：

```diff
 async def _restore_dispatches(app):
-    from .main import _restore_pipeline_dispatches
-    await _restore_pipeline_dispatches()
+    from .main import _ensure_engine
+    engine = _ensure_engine()
+    await engine.restore_pipeline_dispatches()
```

**验证：** 容器正常启动，retry 循环日志 `[R118] retry loop started` 出现。`_restore_dispatches` 无错误。

---

## §3 改动汇总

### 3.1 文件改动清单

| 文件 | 修改 | 行数变化 | 涉及 Bug |
|:-----|:-----|:--------:|:---------|
| `server/ws_server/main.py` | B-1: 删除 `ms.save_message` 块 (L3118-3131) | **-12** | B-1 |
| `server/ws_server/main.py` | B-3: `status_icons` 加 `"in_progress": "🔄"` (L3638-3644) | **+1** | B-3 |
| `server/ws_server/main.py` | B-4: `_try_advance_pipeline` 正则放宽 (L2561) | **~+15** | B-4 |
| `server/ws_server/main.py` | B-2: `_enqueue_retry` 首轮 15s + `_retry_loop` 退避 (L2797, L2777-2784) | **~+25** | B-2 |
| `server/ws_server/main.py` | C-1: `_sm._engine = _ensure_engine()` (L4817 附近) | **+1** | C-1 |
| `server/ws_server/__main__.py` | C-3: `from .main import _ensure_engine` + 2 处调用 (L838-848) | **~+4** | C-3 |
| **合计** | | **~+34** | **6 个 bug** |

### 3.2 修改位置精确行号

| Bug | 文件 | 行号范围 | 改动类型 |
|:----|:-----|:--------:|:---------|
| B-1 | main.py | **L3118-3131** | 整块删除 |
| B-3 | main.py | **L3638-3644** (字典内新增 key) | 单行插入 |
| B-4 | main.py | **L2561** | 单行替换 |
| B-2① | main.py | **L2797** (`60` → `15`) | 常量改小 |
| B-2② | main.py | **L2777-2784** (退避逻辑 + 通知触发) | ~8 行替换 |
| C-1 | main.py | L4817 附近 | 单行替换 |
| C-3① | __main__.py | **L838-841** | ~3 行替换 |
| C-3② | __main__.py | **L845-848** | ~3 行替换 |

---

## §4 数据流图

### 4.1 B-1 修复前后的消息持久化路径

```diff
 # 修复前
 _auto_dispatch()
   ├─ ms.save_message()        ← 第 1 次（from_name="小谷"）
   └─ _send_to_agent()
        ├─ ws.send()           ← 实际 WS 消息
        └─ ms.save_message()   ← 第 2 次（from_name="系统"）

 # 修复后
 _auto_dispatch()
   └─ _send_to_agent()
        ├─ ws.send()           ← 实际 WS 消息
        └─ ms.save_message()   ← 唯一次（from_name="系统"）
```

### 4.2 B-4 正则匹配范围

```
"已完成 ✅ R128 Step 4##sha=abc"
 └──────────────────────────── re.search 扫描
     └──────────┬─────────── re.match 扫描（旧）
                ✅ 匹配
```

```
"最终结果: 已完成 ✅ R128 Step 4"
 └──────────────┬─────────── re.search 扫描（新）
                ✅ 匹配
 └── ───── re.match 扫描（旧）
                ❌ 不匹配
```

### 4.3 C-1/C-3 启动时序

```diff
 # 修复前（R127 集成时）
 main.py 加载
   └─ _engine = None                           ← 模块级
   └─ _sm._engine = _engine                    ← None 注入
 __main__.py on_startup
   └─ from .main import engine                  ← None
   └─ engine._retry_loop()                      ← ❌ AttributeError

 # 修复后
 main.py 加载
   └─ _engine = None
   └─ _sm._engine = _ensure_engine()            ← 惰性初始化
 __main__.py on_startup
   └─ from .main import _ensure_engine          ← 安全获取
   └─ _ensure_engine()._retry_loop()            ← ✅
```

---

## §5 副作用分析

### 5.1 B-1 副作用

| 影响范围 | 分析 | 风险 |
|:---------|:-----|:----:|
| `_auto_dispatch` 逻辑 | 删除 `ms.save_message` 后，消息仍由 `_send_to_agent` 入库，唯一发送者为「系统」 | 🟢 无 |
| `_send_to_agent` | 不受影响，仍保留 `ms.save_message` | 🟢 无 |
| Web 端查询 | 去掉一条冗余记录，查询结果更干净 | 🟢 正向 |
| 归档/历史 | `_auto_dispatch` 消息仍通过 `_send_to_agent` 入库，归档数据完整 | 🟢 无 |

### 5.2 B-3 副作用

| 影响范围 | 分析 | 风险 |
|:---------|:-----|:----:|
| 已有状态值 | `in_progress` 是新 key，不影响已有 `pending/done/failed` 显示 | 🟢 无 |
| `status_icons` 字典 | 新 key 仅被 `icon = status_icons.get(st, "⬜")` 读取 | 🟢 无 |

### 5.3 B-4 副作用

| 影响范围 | 分析 | 风险 |
|:---------|:-----|:----:|
| 误匹配风险 | `re.search` 比 `re.match` 宽松，可能在普通文本中误检出 | 🟡 低 |
| 误推进风险 | 必须同时满足 `(已完成|完成)` + `✅|✔️` + `R{N}` + `Step {N}` 4 个条件同时出现才推进 | 🟢 极低 |
| `_handle_reject` 正则 | 不修改（L3163），独立风险 | 🟢 无 |

**误匹配防护：** 如果 bot 发送 `"看到了已完成 ✅ R999 Step 2 的报告"` 这种日常文本，`re.search` 会匹配并推进。但实际中不会出现非管线完成消息包含 `已完成 ✅ R{N} Step {N}` 的格式。可接受。

### 5.4 B-2 副作用

| 影响范围 | 分析 | 风险 |
|:---------|:-----|:----:|
| 重试间隔变短 | 15s 首轮 → 更频繁的 `_auto_dispatch` 调用 | 🟢 低（幂等） |
| 3 次后通知 PM | 比原来晚（原来首次即通知，现在是第 3 次后） | 🟡 可接受 |
| 重试耗尽停止 | 不再无限循环，释放队列条目 | 🟢 正向 |

### 5.5 C-1 / C-3 副作用

| 影响范围 | 分析 | 风险 |
|:---------|:-----|:----:|
| `_ensure_engine()` 调用顺序 | 首次调用时 `PipelineEngine` 构造函数需要 `context_mgr` 和 `send_to_agent`、`send_ws` 等参数，这些在模块加载时已就绪 | 🟢 无 |
| 双重初始化 | `_ensure_engine()` 检查 `_engine is None`，不会重复构造 | 🟢 无 |

---

## §6 验收标准

### B1-N: B-1 修复（P1 × 2）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| B1-1 | `_auto_dispatch` 中不再调用 `ms.save_message` | `grep "ms.save_message" main.py | grep -c "auto-"` = 0 |
| B1-2 | Web 端每个 dispatch 只显示一条消息（系统 → bot） | 手动验收 |

### B3-N: B-3 修复（P2 × 2）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| B3-1 | `status_icons` 字典包含 `"in_progress"` key | 代码检查 |
| B3-2 | 已派活 step 在 `##status` 中显示 `🔄` 而非 `⬜` | 运行时验证 |

### B4-N: B-4 修复（P2 × 4）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| B4-1 | `已完成 ✅ R128 Step X` 能被识别推进 | 运行测试 |
| B4-2 | `✅ 已完成 R128 Step X，已推 dev` 能被识别推进 | 运行测试 |
| B4-3 | `完成 ✔️ R128 step X` 能被识别推进 | 运行测试 |
| B4-4 | `搞定了 R128 Step X` 不被推进（无误匹配） | 运行测试 |

### B2-N: B-2 修复（P2 × 3）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| B2-1 | 首轮重试间隔为 15s（原 60s） | 代码检查 |
| B2-2 | 第 3 次重试失败后通知 PM | 代码检查 + 运行时 |
| B2-3 | 连续 5 次重试失败后停止重试（不无限循环） | 代码检查 |

### C1-N: C-1 修复（Critical × 2）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| C1-1 | `_sm._engine = _ensure_engine()` 确保注入的是已初始化实例 | 代码检查 |
| C1-2 | 容器启动后 `##status` 正常返回 | 运行时 |

### C3-N: C-3 修复（Critical × 3）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| C3-1 | `__main__.py` on_startup 中先调用 `_ensure_engine()` 再访问 `engine._retry_loop()` | 代码检查 |
| C3-2 | 容器正常启动，retry 循环日志出现 | 日志验证 |
| C3-3 | `_restore_dispatches` 同理使用 `_ensure_engine()` | 代码检查 |

### RV-N: 回归验证（P0 × 2）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| RV-1 | `py_compile` 全量零错误 | `python -m py_compile server/ws_server/*.py` |
| RV-2 | `##start` / `##status` / `##advance` / `##archive` 全部正常 | 运行时回归 |

### 验收计数

| 分组 | Critical | P1 | P2 | P0 | 合计 |
|:-----|:--------:|:--:|:--:|:--:|:----:|
| B-1 | 0 | 2 | 0 | 0 | **2** |
| B-3 | 0 | 0 | 2 | 0 | **2** |
| B-4 | 0 | 0 | 4 | 0 | **4** |
| B-2 | 0 | 0 | 3 | 0 | **3** |
| C-1 | 2 | 0 | 0 | 0 | **2** |
| C-3 | 3 | 0 | 0 | 0 | **3** |
| RV | 0 | 0 | 0 | 2 | **2** |
| **合计** | **5** | **2** | **9** | **2** | **18** |

---

## §7 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不改 `_handle_reject` 的正则** | 退回消息由 bot 模板管控，偏差少，PM 人工介入纠正 |
| ❌ | **不改 `_try_advance_pipeline` 的业务逻辑** | B-4 只放宽正则，不改推进逻辑、artifacts 提取、SHA 验证 |
| ❌ | **不改 pipeline_context / task_card / state** | 数据模型不受影响 |
| ❌ | **不新增重试持久化（DB 重试队列）** | B-2 重试队列仍在内存中，持久化是后续轮次的优化点 |
| ❌ | **不修改 scenario_matcher.py** | C-1 修复在 main.py 的规则注册区完成，不修改 scenario_matcher |
| ❌ | **不改 `_send_to_agent` 的 `ms.save_message`** | `_send_to_agent` 的保存保留，确保消息入库 |

---

## §8 文件改动清单

| 操作 | 文件 | 行数变化 | Bug |
|:----|:-----|:--------:|:----|
| ✅ 修改 | `server/ws_server/main.py` | **~+30** | B-1~B-4, C-1 |
| ✅ 修改 | `server/ws_server/__main__.py` | **~+4** | C-3 |
| ❌ 不碰 | `server/ws_server/scenario_matcher.py` | — | — |
| ❌ 不碰 | `server/ws_server/pipeline_context.py` | — | — |
| ❌ 不碰 | `server/ws_server/pipeline_sync.py` | — | — |
| ❌ 不碰 | `server/ws_server/state.py` | — | — |

---

*文档结束 — 技术方案版本 v1.0*
