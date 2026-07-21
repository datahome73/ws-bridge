# R140 代码审查报告 — 管线引擎核心路径修复

> **审查者：** 🔍 小周
> **日期：** 2026-07-21
> **审查 commit：** `2e65e9b7` — R140 Step 3: fix pipeline engine core paths (permission, cross-step, notify)
> **基准 commit：** `15af5ae`（技术方案）
> **仓库：** `datahome73/ws-bridge` branch `dev`

---

## 0. 审查结论

| 决策 | 值 |
|:-----|:----|
| 🔴 **审查决策** | **需修改 — 退回爱泰💻** |
| 阻塞项 | **P0: `##advance` 路由走旧 main.py 路径，PipelineEngine 的新 L4 权限 + 跨步逻辑未被连接** |

---

## 1. 前置验证

| 验证项 | 方法 | 结果 |
|:-------|:-----|:-----|
| commit 存在远程 | `git log origin-https/dev` → `2e65e9b` 位于 `be52399` 合并之下 | ✅ |
| diff 可获取 | `git diff 15af5ae..2e65e9b` 全量 diff (~113K chars) | ✅ |
| 文件存在 | `git ls-tree -r origin-https/dev --name-only \| grep pipeline_engine` | ✅ |
| docs/R140/ 存在 | `git ls-tree -d origin-https/dev \| grep R140` | ✅ |
| 编译检查 | `python3 -c "compile(open(...))"` | ✅ Syntax OK |
| Import 检查 | `from server.ws_server import pipeline_engine` | ✅ OK |

---

## 2. 架构审查：核心发现

### 🔴 P0-1: `##advance` 路由绕过 PipelineEngine，旧逻辑仍然生效

**命令调用链：**

```
##advance##R{N}##step=N
  → scenario_matcher.handle_hash_cmd()        [scenario_matcher.py L391]
    → import main as _main
    → _main._handle_hash_advance()              [main.py L3521]  ← ❌ 旧路径
```

**旧 `_handle_hash_advance` 的行为：**

```python
# main.py L3521-3557:
# 权限校验：仅 PM 可用
pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
if pm_agent_id and agent_id != pm_agent_id:
    ... "❌ 无权限: ##advance 仅 PM 可用"        # ← 仍 PM-only，不是 L4

step_str = kv.get("step", "")
...
content = f"已完成 ✅ {round_name} Step {step_num}"
ok, reason = _try_advance_pipeline(content, agent_id)  # ← 旧路径，需 completed==current
```

**PipelineEngine 的新实现（未被连接）：**

```python
# pipeline_engine.py L700-780:
async def handle_hash_advance(self, ...):
    level = _get_agent_level(agent_id)
    if level < 4:
        ... "❌ 权限不足"                         # ← L4 权限 ✅
    # 直接操作 ctx.steps，标记 skipped
    for i, s in enumerate(ctx.steps):
        if step_num < target and s.get("status") in ("pending",):
            s["status"] = "skipped"                  # ← 跨步推进 ✅
    ctx.current_step = target
    asyncio.ensure_future(self.auto_dispatch(ctx, target, notify_ws=ws, ...))
```

**影响：** R140 A-1（L4 权限）和 A-2（跨步推进）在 `PipelineEngine` 中正确实现，但 `##advance` 命令路由走到了 `main.py` 的旧函数，**新逻辑 100% 未被使用**。`##advance` 仍然 PM-only、不能跨步。

**📷 证据 — 路由代码：** [scenario_matcher.py L430](https://raw.githubusercontent.com/datahome73/ws-bridge/2e65e9b/server/ws_server/scenario_matcher.py)
```python
elif cmd == "advance":
    return await _main._handle_hash_advance(round_name, kv, agent_id, ws)
```

**📷 证据 — 旧函数：** [main.py L3521](https://raw.githubusercontent.com/datahome73/ws-bridge/2e65e9b/server/ws_server/main.py)
```python
# 权限校验：仅 PM 可用
pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
if pm_agent_id and agent_id != pm_agent_id:
```

**修复方案：** 修改 `scenario_matcher.py` L430：
```python
# 当前：
return await _main._handle_hash_advance(round_name, kv, agent_id, ws)
# 改为：
from . import main as _main_mod
engine = _main_mod._ensure_engine()
return await engine.handle_hash_advance(round_name, kv, agent_id, ws)
```
或删除 main.py 的旧 `_handle_hash_advance` / `_handle_hash_start` / `_handle_hash_status` / `_handle_hash_stop` / `_handle_hash_archive`，全部通过 PipelineEngine 统一路由。

### 🔴 P0-2: `##archive` / `##status` / `##stop` 同样走旧路径

与 `##advance` 同理，所有 `##` 命令在 `scenario_matcher.py` 中路由到 `_main._handle_hash_*`：

| 命令 | 路由目标 | 新实现是否存在 | 状态 |
|:-----|:---------|:--------------:|:----:|
| `##advance` | `main._handle_hash_advance` | `PipelineEngine.handle_hash_advance` ✅ | ❌ 未连接 |
| `##start` | `main._handle_hash_start` | `PipelineEngine.handle_hash_start` ✅ | ❌ 未连接 |
| `##status` | `main._handle_hash_status` | `PipelineEngine.handle_hash_status` ✅ | ❌ 未连接 |
| `##stop` | `main._handle_hash_stop` | `PipelineEngine.handle_hash_stop` ✅ | ❌ 未连接 |
| `##archive` | `main._handle_hash_archive` | `PipelineEngine.handle_hash_archive` ✅ | ❌ 未连接 |

**影响：** PipelineEngine 中的 5 个 `handle_hash_*` 方法全部为**死代码** — 定义但不被任何路径调用。

> 🔴 **P0 阻塞判断依据：** `##advance` 是 R140 的核心修复目标（A-1 + A-2），未连接即修复未生效。管线运行中实际行为**没有改变**。

---

## 3. 功能点逐项验证

### ✅ A-1: `##advance` L4 权限（PipelineEngine 内实现正确）

```python
# pipeline_engine.py L723-731
level = _get_agent_level(agent_id)
if level < 4:
    ... "❌ 权限不足：##advance 需要 L4 级别，你当前 L{level}"
```
**结论：** 实现正确但未连接路由。

### ✅ A-2: 跨步推进（PipelineEngine 内实现正确）

```python
# pipeline_engine.py L744-755
for i, s in enumerate(ctx.steps):
    step_num = i + 1
    if step_num < target and s.get("status") in ("pending",):
        s["status"] = "skipped"             # 标记中间步为 skipped
    elif step_num == target:
        s["status"] = "in_progress"
        s["dispatched_at"] = time.time()
ctx.current_step = target
```
**结论：** 实现正确但未连接路由。

### ✅ A-3/A-4/A-5: `_auto_dispatch` 失败通知（所有模块内实现正确）

`auto_dispatch` 已增加 `notify_ws` / `notify_agent_id` 参数，并在以下场景通知：

| 失败场景 | 通知消息 | 状态 |
|:---------|:---------|:----:|
| AUTO_DISPATCH_ENABLED=False | `⚠️ {round_name} Step {step_num} 派活失败：自动派活已禁用` | ✅ |
| 模板缺失 | `⚠️ {round_name} Step {step_num} 派活失败：派活模板缺失` | ✅ |
| agent_id 为空 | `⚠️ {round_name} Step {step_num} 派活失败：未找到目标 agent` | ✅ |
| 目标离线 (sent=0) | `⚠️ {round_name} Step {step_num} 派活失败：{agent_name} 离线，已加入重试队列` | ✅ |

`_send_dispatch_notify` 辅助函数正确区分 WS 连接和 agent inbox 两种通知通道。

### ✅ A-6/A-7: `##start` 回复修正

```python
# pipeline_engine.py L582-620
if dispatch_ok:
    "✅ 管线 {round_name} 已创建并启动\n  Step 2（技术方案）已派活给 {step2_agent_name}"
else:
    "✅ 管线 {round_name} 已创建\n⚠️ Step 2 自动派活失败，请使用 ##advance##{round_name}##step=2"
```
**结论：** 实现正确。但 main.py 中也有 `_handle_hash_start`（旧版本），路由实际走的是 main.py 版本，需要确认 main.py 版本是否同步更新。

### ✅ A-8: `已完成 ✅` 推进后派活失败通知

`scenario_rules.py` L150 调用 `_ensure_engine().try_advance(content, agent_id)`，进入 `PipelineEngine.try_advance()`，其中：
```python
# pipeline_engine.py L371
asyncio.ensure_future(
    self._auto_dispatch_with_notify(ctx, next_step, agent_id)
)
```
**结论：** 此路径**已正确连接**，A-8 在 `已完成 ✅` 路径上生效。

---

## 4. 回归验证

| # | 验收项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| R1 | `##start` 正常创建管线 | ⚠️ | 取决于最终路由路径（见 P0） |
| R2 | `已完成 ✅ Step N` 正常推进 | ✅ | PipelineEngine.try_advance 连接正确 |
| R3 | `##stop` 正常停止 | ⚠️ | 取决于最终路由路径 |
| R4 | 编译无错误 | ✅ | `python3 -c "from server.ws_server import pipeline_engine"` ✅ |

---

## 5. 代码质量审查

### 5.1 PipelineEngine 类设计 ⭐

- ✅ **良好设计：** 将 ~2200 行散落函数整合为 PipelineEngine 类，依赖注入清晰（`ctx_mgr`/`send_to_agent`/`send_ws` 通过构造函数传入）
- ✅ `try_advance` 的正则表达式从 `r"已完成 ✅ R(\d+) Step (\d+)"` 扩展为 `r"(?:已完成|完成)\s*[✅✔️]\s*R(\d+)\s*[Ss]tep\s*(\d+)"`（R128 B-4 兼容）
- ⚠️ `_send_dispatch_notify` 在 `notify_ws` 和 `notify_agent_id` 都提供时优先 WS，但 `_auto_dispatch_with_notify` 只传 `notify_agent_id` 不传 `notify_ws` — 功能上可行但非最优

### 5.2 main.py 遗留代码问题

- ❌ main.py 中仍有 5 个 `_handle_hash_*` 旧函数，与 PipelineEngine 新方法形成**双实现**：
  - `_handle_hash_start` (L3666) — 旧版
  - `_handle_hash_advance` (L3521) — 旧版，PM-only
  - `_handle_hash_status` (L3666?) — 旧版
  - `_handle_hash_stop` (L3790) — 旧版
  - `_handle_hash_archive` (L3578) — 旧版
- ❌ `_try_advance_pipeline` (L2743) 是旧版（简单正则，无 A-8 通知），与 PipelineEngine.try_advance 并存

### 5.3 Config.py 变化

- `AGENT_WHITELIST` 中移除了 `"经理"`（而非新增 `PIPELINE_COORDINATOR_AGENT_ID`）
- 方案选择：L4 权限替代了配置项方案，更简洁

### 5.4 `auto_dispatch` 中 `card_key → WS ID fallback` 逻辑变更

旧代码有 `_resolve_card_key_to_ws_id(fallback)` 的完整 fallback 链，新代码改为 `self._resolve_card_key` 回调。需确认 `resolve_card_key` 回调在 PipelineEngine 构造时正确传入。

---

## 6. 边界情况分析

| # | 场景 | 影响 | 状态 |
|:-:|:-----|:----:|:----:|
| ① | `##advance` 路由到旧 main.py 函数 | PM-only + 不能跨步 | ❌ 未修复 |
| ② | `##start` 路由到旧 main.py 函数 | 旧回复「Step 1 已派活」 | ❌ 未修复 |
| ③ | `已完成 ✅` 调用 PipelineEngine.try_advance | 新 regex + A-8 通知 | ✅ 正确 |
| ④ | auto_dispatch 被多次调用 | notify_ws/agent_id 参数默认 None | ✅ 安全 |
| ⑤ | PipelineEngine.handle_hash_advance 从未被调用 | 100% 死代码 | ❌ 浪费 |
| ⑥ | 两个 `try_advance` 实现共存 | 混乱，维护负担 | ⚠️ |
| ⑦ | `_send_dispatch_notify` WS 发送异常 | try/except 兜底 | ✅ |
| ⑧ | `getattr(config, 'PIPELINE_COORDINATOR_AGENT_ID', None)` 未使用 | 选择了 L4 方案 | ✅ |

---

## 7. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:-----|
| 硬编码敏感信息 | ✅ 无 |
| 调试日志/print | ✅ 全部使用 logger |
| TODO/FIXME 残留 | ✅ 无 |
| R 标签准确性 | ✅ R140 标签正确 |
| 死代码 | 🔴 5 个 PipelineEngine.handle_hash_* 方法 + 5 个 main.py _handle_hash_* 旧函数为双实现 |

---

## 8. 验证命令执行结果

```bash
$ python3 -c "compile(open('server/ws_server/pipeline_engine.py').read(), 'pipeline_engine.py', 'exec'); print('✅ Syntax OK')"
# ✅ Syntax OK

$ python3 -c "import sys; sys.path.insert(0, '.'); from server.ws_server import pipeline_engine; print('✅ Import OK')"
# ✅ Import OK
```

---

## 9. 总结

| 验收项 | P0 | 结果 |
|:-------|:--:|:----:|
| A-1: `##advance` L4 权限 | P0 | 🔴 实现正确但**未连接路由** |
| A-2: `##advance` 跨步推进 | P0 | 🔴 实现正确但**未连接路由** |
| A-3: `_auto_dispatch` 模板缺失通知 | P0 | ✅ 实现正确 |
| A-4: `_auto_dispatch` agent_id 为空通知 | P0 | ✅ 实现正确 |
| A-5: `_auto_dispatch` 目标离线通知 | P0 | ✅ 实现正确 |
| A-6: `##start` 说「Step 2 已派活」 | P1 | ⚠️ 正确但需确认 main.py 旧函数已更新 |
| A-7: `##start` 派活失败有原因 | P0 | ⚠️ 同上 |
| A-8: 推进后派活失败通知 | P1 | ✅ `已完成 ✅` 路径已连接 |
| R1-R4: 回归 | P0 | ⚠️ 待 P0 修复后回归 |

**结论：🔴 需修改 — 退回爱泰💻**

**阻塞原因：** `##advance` 命令路由走 `scenario_matcher.py → main.py._handle_hash_advance`（旧路径），PipelineEngine 中的新 L4 权限 + 跨步逻辑未连接。5 个 PipelineEngine.handle_hash_* 方法均为死代码。

**修复最小方案：** 在 `scenario_matcher.py` L430 将路由从 `_main._handle_hash_advance` 改为 `_main._ensure_engine().handle_hash_advance`，并对 start/status/stop/archive 做相同修改。后续可考虑删除 main.py 中的 5 个旧 `_handle_hash_*` 函数以减少双实现。
