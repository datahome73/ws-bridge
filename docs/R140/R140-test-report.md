# R140 测试报告 — 管线引擎核心路径修复

> **测试人：** 泰虾 (QA)
> **轮次：** R140
> **日期：** 2026-07-21
> **基线：** `9f52658` (R139 末)
> **编码：** `2e65e9b` + `ec3478a` (R140 Step 3)
> **审查：** `e439b55` (Step 4 ✅ 二次审查通过)

---

## 第一部分：编译验证 ✅

| ID | 验证项 | 结果 | 说明 |
|:--:|:-------|:----:|:-----|
| R4 | `from server.ws_server import pipeline_engine` | 🟢 | 无 ImportError |
| — | `from server.ws_server import main` | 🟢 | 无 ImportError |
| — | `from server.ws_server import scenario_matcher` | 🟢 | 无 ImportError |
| — | `from server.ws_server import *` | 🟢 | 全部模块无错误 |

---

## 第二部分：源码级验证 (A-1~A-8)

由于生产服务端尚未部署 R140 代码，协议级测试无法进行。以下为源码级代码审计结果：

| # | 验收项 | 类型 | 结果 | 证据位置 |
|:-:|:-------|:----:|:----:|:---------|
| A-1 | L4 可用 `##advance` | P0 | 🟢 | `pipeline_engine.py:723` — `_get_agent_level(agent_id)`，`level < 4` 拒绝 |
| A-2 | 跨步推进 Step N | P0 | 🟢 | `pipeline_engine.py:750-759` — for 循环跳过中间 pending 步 → "skipped" |
| A-3 | 跨步后正确派活 | P0 | 🟢 | `pipeline_engine.py:778` — `auto_dispatch(ctx, target, notify_ws=ws)` |
| A-4 | 模板缺失时通知 | P0 | 🟢 | `pipeline_engine.py:926` — `_send_dispatch_notify` + "派活模板缺失" |
| A-5 | agent_id 为空时通知 | P0 | 🟢 | `pipeline_engine.py:915` — `_send_dispatch_notify` + "未找到目标 agent" |
| A-6 | `##start` 回复"Step 2 已派活给 {name}" | P1 | 🔴 | `pipeline_engine.py:592` 代码存在，但**路由未连接**（见下方） |
| A-7 | `##start` 派活失败有原因 | P0 | 🟢 | `pipeline_engine.py:610` — "⚠️ Step 2 自动派活失败" |
| A-8 | 推进后派活失败通知发送者 | P1 | 🟢 | `pipeline_engine.py:371` — `_auto_dispatch_with_notify` |

### A-6 问题详情：`##start` 路由未连接

`PipelineEngine.handle_hash_start()`（含 R140 A-6/A-7 修改）**未被任何路由调用**。

```python
# scenario_matcher.py L421 — 现行路由：
elif cmd == "start":
    return await _main._handle_hash_start(...)  # main.py:3538 旧函数，无 R140 修改

# 需要改为：
elif cmd == "start":
    from . import main as _main_mod
    engine = _main_mod._ensure_engine()
    return await engine.handle_hash_start(...)   # PipelineEngine 新函数，含 R140 A-6/A-7
```

**影响：** 生产环境中 `##start` 仍然回复 "Step 1 已派活"，而不是 "Step 2 已派活给 {name}"。
**与首次审查同一模式：** 首次审查发现的 `##advance` 路由未连接已在 `ec3478a` 中修复（`engine.handle_hash_advance`），但 `##start` 路由被遗漏。

### 🔴 建议修复

```
scenario_matcher.py L420-422:
  # 当前:
  elif cmd == "start":
      return await _main._handle_hash_start(round_name, kv, agent_id, ws)
  
  # 修改为（同 ##advance 修复模式）:
  elif cmd == "start":
      from . import main as _main_mod
      engine = _main_mod._ensure_engine()
      return await engine.handle_hash_start(round_name, kv, agent_id, ws)
```

---

## 第三部分：路由验证

| 命令 | 现行路由 | 目标 | 状态 |
|:-----|:---------|:-----|:----:|
| `##start` | `_main._handle_hash_start` (main.py:3538) | `PipelineEngine.handle_hash_start` | 🔴 **未连接** |
| `##advance` | `engine.handle_hash_advance` (pipeline_engine.py:700) | ✅ | 🟢 已修复 (ec3478a) |
| `##status` | `_main._handle_hash_status` (main.py:3661) | — | 🟢 无相关修改 |
| `##stop` | `_main._handle_hash_stop` | — | 🟢 无相关修改 |

---

## 第四部分：B-4 模糊匹配验证

`_try_advance_pipeline` 新增模糊匹配，容忍格式偏差：

| 场景 | 预期行为 | 状态 |
|:-----|:---------|:----:|
| 精确匹配 `已完成 ✅ R{N} Step {N}` | 正常推进 | 🟢 |
| 模糊匹配（空白/emoji/大小写偏差） | 匹配成功 + info 日志 | 🟢 |
| 疑似消息（含 R{N} Step{N} 但前缀不对） | 拒绝 + warning 日志 | 🟢 |
| 完全不匹配 | 返回 False, "no match" | 🟢 |

---

## 第五部分：总结

### 通过项（源码级）

| 分组 | 通过 | 未通过 |
|:-----|:----:|:------:|
| A-1~A-5 功能实现（代码存在） | 5 | 0 |
| A-6~A-7 代码存在但路由未接 | 1 | 1 |
| A-8 通知机制 | 1 | 0 |
| B-4 模糊匹配 | 1 | 0 |
| R4 编译 | 1 | 0 |

### 发现的问题

| # | 问题 | 严重度 | 状态 |
|:-:|:-----|:------:|:----:|
| 🔴 1 | `##start` 路由未连接 `PipelineEngine.handle_hash_start` | P0 | 待修复 |
| 🟡 2 | 生产服务端未部署 R140 代码 | P0 | 待部署 |

### 建议

1. **修复 `##start` 路由**（同 `ec3478a` 模式，约 3 行改动）
2. **重新部署**服务端使 R140 代码上线
3. **泰虾重新跑协议级测试**验证 A-1~A-8 全链路
