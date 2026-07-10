---
pipeline:
  round_name: R98
  branch: dev
  steps: 6
  topology:
    auto_chain: true
    chain:
      - step: step1
        role: pm
        title: 标注 WORK_PLAN 已审核
      - step: step2
        role: arch
        title: 技术方案
      - step: step3
        role: dev
        title: 编码实现
      - step: step4
        role: review
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署
  workspace:
    members:
      - 小谷
      - 小开
      - 爱泰
      - 小周
      - 泰虾
      - 小爱
  work_plan_url: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/dev/docs/R98/WORK_PLAN.md
  requirements_url: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R98/R98-product-requirements.md
---

# R98 WORK_PLAN — !close_workspace 归档通知增强 🔧

> **状态：** 📋 需求已审核通过 ✅ | WORK_PLAN 已审核通过 ✅
> **需求文档:** https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R98/R98-product-requirements.md
> **基线:** R97 后 `main` latest (`e375714`)

---

## 概述

R98 是个小功能点，修复 `!close_workspace` 归档通知只发 `ws.members`、漏了 PipelineContext 管线参与者的问题。

| 项目 | 值 |
|:-----|:----|
| 改动量 | ~+15 行，仅 `server/handler.py` |
| 改动范围 | `_cmd_close_workspace` 通知循环合并 PipelineContext 参与者 |
| 架构影响 | 零 — 不影响 AutoRouter、PipelineContext 主体逻辑 |
| 风险 | 低 — `try/except` 包裹，失败静默回退 |

### 团队

| Bot | 角色 | Agent ID | 本轮职责 |
|:----|:-----|:---------|:---------|
| 小谷 | 📋 pm | `ws_f26e585f6479` | Step 1 — 标注 WORK_PLAN 已审核 |
| 小开 | 🏗️ arch | `ws_3f7cdd736c1c` | Step 2 — 技术方案（可选：改动极小） |
| 爱泰 | 💻 dev | `ws_0bb747d3ea2a` | Step 3 — 编码实现 |
| 小周 | 🔍 review | `ws_fcf496ca1b4f` | Step 4 — 代码审查 |
| 泰虾 | 🦐 qa | `ws_eab784ac7652` | Step 5 — 测试验证 |
| 小爱 | 🦸 ops | `ws_c47032fa1f67` | Step 6 — 合并部署 |

---

## Step 1 — PM 标注 WORK_PLAN 已审核（小谷）

**触发条件：** 项目负责人按 `!pipeline_start` 授权按钮后，AutoRouter 派活 step1 到小谷 inbox。

任务内容：
1. 确认需求文档已审核通过（项目负责人确认后）
2. 在 WORK_PLAN 顶部修改状态行：`📋 需求已审核通过 ✅`
3. 推 dev 分支
4. 回复 `✅ 完成` 到 `_inbox:server`

---

## Step 2 — 技术方案（小开）

**改动了什么：** `handler.py` 的 `_cmd_close_workspace` 通知块（~L738-774），通知目标从 `ws.members` 改为 `ws.members` + PipelineContext 参与者（去重）。

**改动量：** ~+15 行，纯 Python，无外部依赖。

技术方案要点：
1. `_ensure_pipeline_manager()` 获取 PipelineContextManager
2. `mgr.get_context(round_name)` 读 PipelineContext
3. `isinstance(ctx, dict)` 守卫 + set 合并
4. `set.discard(sender_id)` 排除发送者
5. 通知循环不变，只改目标集合来源

**由于改动极小，arch 可跳过详细方案直接进入 dev 编码。** 编码时参考需求文档 §2 的伪代码。

---

## Step 3 — 编码实现（爱泰）

**改动位置：** `server/handler.py` ~L738-774

**改动内容：**

1. 在 `for _member_id in list(ws.members):` 之前，新建一个 set：
   ```python
   _notify_ids = set(ws.members)
   ```
2. 从 PipelineContext 补充管线参与者：
   ```python
   _mgr = _ensure_pipeline_manager()
   _ctx = _mgr.get_context(_round_name)
   if _ctx and isinstance(_ctx, dict):
       for _step in _ctx.get("steps", {}).values():
           if isinstance(_step, dict) and _step.get("agent_id"):
               _notify_ids.add(_step["agent_id"])
   ```
3. 排除 sender：
   ```python
   _notify_ids.discard(sender_id)
   ```
4. 将循环改为 `for _member_id in list(_notify_ids):`
5. `try/except` 保留现有异常安全

**推 git 前需验证：** 单元测试可通过（`python3 -m unittest tests.test_r97_auto_router -v` → ALL GREEN）

---

## Step 4 — 代码审查（小周）

审查重点：
1. `isinstance(_ctx, dict)` 守卫是否齐全
2. `_step.get("agent_id")` 空值保护
3. 去重逻辑（set 合并）是否正确
4. `_notify_ids.discard(sender_id)` 在 sender 不是成员时是否无害
5. `try/except` 是否包裹了整个通知块（失败不阻塞关闭）
6. 测试验证：19/19 R97 测试 + 8 项 R98 验收

---

## Step 5 — 测试验证（泰虾）

验收 8 项（详见需求文档 §3）：

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | 归档通知送达全部管线 bot | 模拟管线参与者列表，确认所有 bot inbox 收到 |
| 2 | ws.members 中非管线成员也收到 | 添加纯 workspace 成员，确认收到 |
| 3 | 调用者自己不收到 | sender inbox 无此消息 |
| 4 | PipelineContext 不存在时兼容旧行为 | 无 pipeline 的 workspace 正常通知 ws.members |
| 5 | 同一 bot 只收一条 | 既是 member 又是 pipeline 参与者只出现一次 |
| 6 | 无 agent_id 的 step 静默跳过 | step.agent_id="" 的 step 不产生通知 |
| 7 | 通知失败不阻塞关闭 | 强制异常 → 工作室正常归档 |
| 8 | `!step_handoff` 自动 close 正常 | 最后一步完成 → 自动关闭 + 通知 |

R97 回归测试：`python3 -m unittest tests.test_r97_auto_router -v` → 19/19 🟢

---

## Step 6 — 合并部署（小爱）

1. 合并到 main：
   ```
   git checkout main
   git merge dev
   git push origin main
   ```
2. 构建部署 ws-bridge:r98 镜像
3. 验证线上 `!close_workspace` 通知覆盖面
