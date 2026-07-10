---
pipeline:
  name: "R92-ARDB10 AutoRouter 全自动管线端到端验证 🚂"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R92-ARDB10/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R92-ARDB10/R92-ARDB10-tech-plan.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: 验证方案
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step3
        role: developer
        title: 修复/验证脚本
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step4
        role: qa
        title: 执行验收
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: operations
        title: 闭环确认
  steps:
    step2:
      role: architect
      title: 验证方案
    step3:
      role: developer
      title: 修复/验证脚本
    step4:
      role: qa
      title: 执行验收
    step5:
      role: operations
      title: 闭环确认
  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
      developer:
        mention_keyword: "developer;开发"
      qa:
        mention_keyword: "qa;测试"
      operations:
        mention_keyword: "operations;运维"
---

# R92-ARDB10 技术方案 — AutoRouter 全自动管线端到端验证 🚂

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于：** R92 全自动管线验证（原 Step 6 验证计划）

---

## 1. 验证目标

R92 实现了 `!pipeline_start` 到 `_admin` 频道的广播机制（`dev@1318f17`），代码审查 🟢 通过（`e8e7788`），静态测试 🟢 通过（`0333fef` 27/27）。

本管线（R92-ARDB10）的目标是**在真实环境下运行端到端全自动管线验证**，确认：

| # | 验证环节 | 断言 |
|:-:|:---------|:-----|
| E2E-1 | `!pipeline_start` 发到 `_admin` | 广播到达 AutoRouter |
| E2E-2 | AutoRouter 监听并解析广播 | `_on_pipeline_ready()` 触发 |
| E2E-3 | 拓扑加载 | WORK_PLAN 的 frontmatter 解析成功 |
| E2E-4 | 自动派活 Step 2 | arch bot 收件箱收到任务 |
| E2E-5 | Step 完成 → 自动接力 | dev bot 收件箱收到 Step 3 任务 |
| E2E-6 | 全线闭环 | PM 收到 🏁 管线已完成通知 |

---

## 2. 架构方案

### 2.1 全链路数据流

```
小谷发 !pipeline_start R92-ARDB10 --work_plan_url <url>
  │
  ▼
handler.py _cmd_pipeline_start()
  │
  ├─① _send(ws, msg) → 回复小谷（原有行为）
  │
  └─② _broadcast_to_channel(_admin, payload) ← R92 新增
       │
       ▼
       AutoRouter _handle_message()
         │  "管线已启动" in content ✅
         │  _extract_round("R92-ARDB10") → "R92"
         │
         ▼
       _on_pipeline_ready("R92-ARDB10")
         │
         ├─ _fetch_topology("R92-ARDB10")
         │   └─ 从 dev 分支 WORK_PLAN.md 解析 frontmatter
         │
         └─ _dispatch_step(round, step2, ...)
              │  "arch" → ws_xxxx（爱泰/arch bot）
              │
              ▼
              arch bot inbox: 【R92-ARDB10 Step 2 任务】
```

### 2.2 关键检查点

| 检查点 | 信号 | 成功标志 |
|:-------|:-----|:---------|
| CK-1 | `_admin` 广播被 AutoRouter 接收 | AutoRouter 日志: `[AR] [R92-ARDB10] 🟢 管线就绪` |
| CK-2 | WORK_PLAN 拓扑解析 | `[AR] [R92-ARDB10] 🟢 管线就绪, chain=4 steps` |
| CK-3 | Step 2 派活到 arch bot | arch bot inbox 收到任务通知 |
| CK-4 | arch 完成 → Step 3 自动接力 | dev bot inbox 收到 Step 3 |
| CK-5 | 全线闭环 | PM inbox: `🏁 R92-ARDB10 全部 Step 已完成！` |

### 2.3 故障模式

如果 AutoRouter 未自动派活，兜底方案：

| 故障 | 原因 | 快速修复 |
|:-----|:-----|:---------|
| CK-1 失败 | `_admin` 广播没到 AutoRouter | 检查 AutoRouter 的 WS 连接状态 + `_pm_inbox_channel` 配置 |
| CK-2 失败 | WORK_PLAN 不存在/格式错误 | 确认 `docs/R92-ARDB10/WORK_PLAN.md` 已推 dev |
| CK-3 失败 | 角色→agent_id 映射缺失 | 运行 `!agent_card list` 确认 arch bot 注册且 `pipeline_roles` 含 `architect` |
| CK-4 失败 | 派活消息发送异常 | 检查 WS 连接 + inbox 路由 |
| CK-5 失败 | chain 解析/list_done 逻辑异常 | 检查 AutoRouter `_notify_all_done` |

---

## 3. 验证脚本

当 AutoRouter 手动验证需要时，建议脚本 `scripts/verify_auto_router_e2e.py`：

```python
# 1. 检查 AutoRouter 是否在线
# 2. 模拟发送 _admin 广播
# 3. 验证 AutoRouter 处理结果
```

脚本验证项：
- `_broadcast_to_channel` 函数正常调用
- `_on_pipeline_ready` 正确解析拓扑
- `_dispatch_step` 正确查找角色→agent_id
- 日志输出格式正确

---

## 4. 验收清单

| # | 验收项 | 期望 | 验证方式 |
|:-:|:-------|:-----|:---------|
| ✅-1 | 管线启动广播到 `_admin` | AutoRouter 日志有 `🟢 管线就绪` | 日志检查 |
| ✅-2 | WORK_PLAN 解析成功 | chain=4 steps 正确 | 日志检查 |
| ✅-3 | Step 2 派活到 arch bot | arch bot 收到任务 | inbox 检查 |
| ✅-4 | arch 完成 ✅ 后 Step 3 自动派活 | dev bot 收到任务 | inbox 检查 |
| ✅-5 | 全部 Step 完成闭环 | PM 收到 `🏁` 通知 | inbox 检查 |
| ✅-6 | 异常时兜底可用 | 不阻塞其他管线 | 并行管线测试 |
