# R106: Pipeline Context + Step 自动接力

> **版本：** v1.0
> **日期：** 2026-07-13
> **状态：** 📝 需求文档
> **轮次：** R106（分两阶段）

---

## 一、背景

当前管线全流程需要 PM 手工 6 次派活：

```
写需求→推 git→派 Step2→等bot→派 Step3→等bot→派 Step4→等bot→派 Step5→等bot→派 Step6→等bot→部署
```

R102-R105 打好了基础：Server 中继（`_inbox:server` + `to_agent`）、回复格式协议（`skills/reply-format-protocol.md`）、Bot 统一回复模板都已就位。现在可以迈出自动化第一步。

**核心问题：** Server 目前收到 `已完成 ✅ R{N} Step {N}` 后只会转发给 PM，不会自动推进下一步。PM 必须手工拼消息、查 agent_id、发 `to_agent`。

---

## 二、设计思路

分两轮走：

### R106a: Pipeline Context + Step 状态自动推进

**目标：** Server 能理解「管线状态」，收到完成通知后自动更新状态，不自动派活。

```
Bot 发 "已完成 ✅ R106 Step 2" → Server 解析 round=106, step=2
  → 更新 Pipeline Context: step2.status = "completed", current_step = 3
  → 转发 PM（现有行为不变）
  → 不做自动派活
```

PM 查看状态验证是否符合预期。验证通过后再进入 R106b。

### R106b: 基于 Pipeline Context 自动派活

**目标：** 基于消息模板和 Pipeline Context，服务器自动拼消息、自动发 `to_agent`。

```
Bot 发 "已完成 ✅ R106 Step 2" → Server 解析
  → 更新状态 step2.completed, current_step=3
  → 用 message_templates["step3"] 拼消息
  → 填充 artifacts（commit_sha 等）
  → 自动发 _inbox:server + to_agent={目标 bot 的 agent_id}
```

---

## 三、R106a 需求

### 3.1 Pipeline Context 定义

文件：`server/pipeline_context.py`（新增）

一个简单的 JSON 持久化数据结构：

```json
{
  "round_name": "R106",
  "round_title": "Pipeline Context + Step 自动推进",
  "status": "running",
  "current_step": 1,
  "steps": [
    {"step": 1, "role": "pm",     "agent_id": "{pm_agent_id}", "status": "pending"},
    {"step": 2, "role": "arch",   "agent_id": "{arch_agent_id}", "status": "pending"},
    {"step": 3, "role": "dev",    "agent_id": "{dev_agent_id}", "status": "pending"},
    {"step": 4, "role": "review", "agent_id": "{review_agent_id}", "status": "pending"},
    {"step": 5, "role": "qa",     "agent_id": "{qa_agent_id}", "status": "pending"},
    {"step": 6, "role": "ops",    "agent_id": "{ops_agent_id}", "status": "pending"}
  ],
  "references": {
    "requirements_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/R{round}-product-requirements.md",
    "work_plan_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/WORK_PLAN.md"
  },
  "artifacts": {
    "step1": {"work_plan_commit": ""},
    "step2": {"tech_plan_url": ""},
    "step3": {"commit_sha": "", "files_changed": ""},
    "step4": {"review_report_url": ""},
    "step5": {"test_commit_sha": ""},
    "step6": {"merge_commit": ""}
  }
}
```

### 3.2 Pipeline Context 操作

| 操作 | 说明 |
|:-----|:------|
| `create_context(round_name, round_title, role_agent_map)` | 创建新管线上下文 |
| `advance_step(round_name, completed_step)` | 推进到下一步，更新状态 |
| `get_context(round_name)` | 查询管线上下文 |
| `close_pipeline(round_name)` | 标记管线完成 |

### 3.3 `_handle_server_relay` 增加自动推进钩子

在 `已完成 ✅` 前缀匹配分支中，增加：

```
收到 "已完成 ✅ R{round} Step {N}"
  → 解析 {round} 和 {N}
  → 查 Pipeline Context: get_context({round})
  → 如果存在：advance_step({round}, {N}) → N+1
  → 转发 PM（现有行为不变）
  → 不自动派活（留给 R106b）
```

**改动位置：** `server/main.py` 的 `_handle_server_relay()`（两份副本各加 ~10 行）

### 3.4 `!pipeline_status` 增强

在现有 `!pipeline_status` 命令中增加 Pipeline Context 查询：
```
R106 — 进行中
  Step 1 ✅ pm → 已完成
  Step 2 ✅ arch → 已完成
  Step 3 🔄 dev → 进行中
  Step 4 ⏳ review → 待开始
  Step 5 ⏳ qa → 待开始
  Step 6 ⏳ ops → 待开始
```

### 3.5 不需要改动的

| 项目 | 原因 |
|:-----|:------|
| 前端模板 | 纯后端改动 |
| 回复格式协议 | 已就位 |
| 认证/权限 | 无关 |
| Web 服务 | 无关 |

---

## 四、R106b 需求（预留）

已验证 R106a 的状态推进正确后，第二轮回做：

1. 在 `advance_step` 成功后，自动渲染 `message_templates["step{N+1}"]`
2. 从 `artifacts` 中填充变量（如 `commit_sha`）
3. 发 `_inbox:server` + `to_agent`
4. PM 在关键节点仍可手动覆盖

---

## 五、验收标准（R106a）

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `create_context()` 创建 JSON 文件 | 调用后检查 `data/pipeline_contexts.json` |
| 2 | `advance_step()` 正确推进 current_step | Step 2 完成后 current_step 变为 3 |
| 3 | `获取 context()` 返回正确状态 | 查询确认步骤状态 |
| 4 | Server 收到 `已完成 ✅` 后自动推进 | 派活→bot 完成→检查状态自动更新 |
| 5 | `!pipeline_status` 显示 Pipeline Context | 输入命令查看输出 |
| 6 | 不自动派活（R106a 不突破） | 推进后检查是否有多余消息发出 |
| 7 | 不破坏现有前缀匹配逻辑 | 普通 `已完成 ✅` 消息仍正常转发 PM |

## 六、变更文件清单

| 文件 | 改动 | 估算 |
|:-----|:------|:-----|
| `server/pipeline_context.py` | 新增 | +80 行 |
| `server/main.py` x 2 副本 | `_handle_server_relay` 加推进钩子 | +20 行 |
| `server/handler.py` or `main.py` | `!pipeline_status` 增强 | +15 行 |
| **总计** | | **~+115 行** |

## 七、风险与注意事项

| 风险 | 等级 | 缓解 |
|:-----|:-----|:------|
| 解析 `已完成 ✅ R{N} Step {N}` 时格式不匹配 | 🟡 | 用正则 `r"已完成 ✅ R(\d+) Step (\d+)"` 容错 |
| 多轮次并发（同时跑 R106 和 R107） | 🟡 | `get_context(round_name)` 按轮次名查询 |
| 自动推进后 PM 不知情 | 🟢 | 转发 PM 的行为保留，PM 仍收到通知 |
