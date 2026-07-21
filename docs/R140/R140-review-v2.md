# R140 代码审查报告 — 管线引擎核心路径修复（二次审查）

> **审查人：** 🔍 小周
> **基线：** `9f52658e13`（R139 末）
> **审查目标：** `ec3478ad82`（R140 含修复）
> **结论：** ✅ **通过**

## 一、审查清单逐项验证

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| A-1 | 经理（L4）能用 `##advance##R{N}##step=N` | L4 权限，非 PM-only | ✅ | `pipeline_engine.py:723` — `_get_agent_level(agent_id)`，level < 4 拒绝 |
| A-2 | `##advance##R{N}##step=5` 从 Step 2 跳到 Step 5 | 中间 pending 步标记 skipped | ✅ | `pipeline_engine.py:750-759` — for 循环中 step_num < target && status=="pending" → "skipped" |
| A-3 | 跨步后正确派活指定步 | `auto_dispatch(ctx, target)` | ✅ | `pipeline_engine.py:778` — `asyncio.ensure_future(self.auto_dispatch(ctx, target, ...))` |
| A-4 | 模板缺失时通知发起者 | 不静默 | ✅ | `pipeline_engine.py:926` — `_send_dispatch_notify` + "派活模板缺失" |
| A-5 | agent_id 为空时通知发起者 | 不静默 | ✅ | `pipeline_engine.py:915` — `_send_dispatch_notify` + "未找到目标 agent" |
| A-6 | `##start` 回复显示"Step 2 已派活给 {name}" | 非"Step 1 已派活" | ✅ | `pipeline_engine.py:592` — `"Step 2（技术方案）已派活给 {step2_agent_name}"` |
| A-7 | `##start` 派活失败显示原因 | 失败原因 + 手动推进指引 | ✅ | `pipeline_engine.py:610` — `"⚠️ Step 2 自动派活失败..."` |
| A-8 | `已完成 ✅` 推进后若派活失败，通知发送者 | 通知机制 | ✅ | `pipeline_engine.py:371` — `_auto_dispatch_with_notify(ctx, next_step, agent_id)` |
| R1 | `##start` 正常创建管线 + 派活 | 未破坏 | ✅ | 创建流程未改，仅回复消息变化 |
| R2 | `已完成 ✅ Step N` 正常推进 | 未破坏 | ✅ | `try_advance` 仅增加通知参数 |
| R3 | `##stop` 正常停止 | 未破坏 | ✅ | 无改动 |
| R4 | 编译无错误 | 无语法/import 错误 | ✅ | 见下方 Import 验证 |

## 二、改动文件总览

| # | 文件 | 动作 | 行数变化 | 状态 |
|:-:|:-----|:------|:--------:|:----:|
| 1 | `server/ws_server/pipeline_engine.py` | 修改 | **+150 -26** | ✅ |
| 2 | `server/ws_server/main.py` | 修改 | **+26 -1** | ✅ |
| 3 | `server/ws_server/scenario_matcher.py` | 修改 | **+3 -1** | ✅ |

## 三、首次审查 🔴 问题修复验证

**首次审查发现：** `##advance` 路由未连接 PipelineEngine — `scenario_matcher.py` 仍然调用 `_main._handle_hash_advance`（main.py 的旧 PM-only handler）。

**修复验证 (commit `ec3478ad82`)：**

```python
from . import main as _main_mod
engine = _main_mod._ensure_engine()
return await engine.handle_hash_advance(round_name, kv, agent_id, ws)
```

✅ `_ensure_engine()` 定义于 `main.py:46`，是稳定的工厂函数。
✅ `engine.handle_hash_advance` 包含 L4 权限检查 + 跨步推进逻辑。
✅ 路由修复正确，首次审查的 🔴 问题已解决。

## 四、代码质量检查

### 4.1 死代码提醒

`main.py:3393-3446` 的旧 `_handle_hash_advance` 不再被任何代码调用（已验证：全仓库 grep 仅在定义处命中）。无功能影响，建议后续清理轮删除。

### 4.2 通知架构验证

✅ 通知优先级：WS 连接 → Agent Inbox。
✅ 所有静默失败点（AUTO_DISPATCH_ENABLED=0、模板缺失、agent_id 空、离线）均已覆盖。
✅ 所有通知有 try/except 保护，不会抛出异常。

### 4.3 Import 依赖验证

- `pipeline_engine.py:708` — `from .scenario_matcher import _get_agent_level` 函数体内 lazy import ✅
- `scenario_matcher.py:428` — `from . import main as _main_mod` 函数体内 lazy import ✅

### 4.4 侧效应验证

| 侧效应 | 结论 |
|:-------|:----:|
| `auto_dispatch` 新参数 `notify_ws=None, notify_agent_id=None` 向后兼容 | ✅ |
| `handle_hash_advance` 重构后 `_try_advance_pipeline` 不再被 advance 调用 | ✅ |
| 跨步标记 `skipped` 被 status 映射覆盖 | ✅ (`main.py:3704` `"skipped": "⏭"`) |
| `_send_to_agent` 在 PipelineEngine 上可用 | ✅ (`pipeline_engine.py:101`) |

## 五、汇总 & 结论

### 亮点

- ✅ 首次审查 🔴 问题已修复
- ✅ 全部 8 项验收 (A-1 ~ A-8) 实现正确
- ✅ 4 项回归 (R1-R4) 零影响
- ✅ 代码质量良好：lazy import、try/except 保护、签向后兼容
- ✅ 4 个静默失败点全部增加通知

### 结论

> ✅ **通过** — 代码实现完全覆盖需求和技术方案要求。无阻塞性缺陷。

### 建议顺序

1. 合并至 dev
2. 泰虾安排功能验收 A-1~A-8 + 回归 R1~R4
3. 后续清理轮删除 `main.py` 死代码 `_handle_hash_advance`
