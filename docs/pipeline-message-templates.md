# ws-bridge 管线派活消息模板集

> 整理自 R103-R105 三轮全流程派活实践。
> 用于 R106 Pipeline Context 的消息模板定义。

---

## 模板总览

| Step | 角色 | 模板用途 |
|:----:|:-----|:---------|
| Step 2 | 架构师（小开） | 技术方案评估 |
| Step 3 | 开发（爱泰） | 编码实现 |
| Step 4 | 审查（小周） | 代码审查 |
| Step 5 | 测试（泰虾） | 验证测试 |
| Step 6 | 运维（小爱） | 合并部署 |

---

## 模板：Step 2 — 架构师

```
📋 R{round} Step 2 — 技术方案 到你了！

{round_title}

📄 需求文档：
https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/R{round}-product-requirements.md

📋 WORK_PLAN：
https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/WORK_PLAN.md

🔍 任务：
{task_description}

⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 2
```

**变量说明：**

| 变量 | 示例 | 来源 |
|:-----|:------|:------|
| `{round}` | `R106` | Pipeline Context |
| `{round_title}` | `Pipeline Context + Step 自动推进` | Pipeline Context |
| `{task_description}` | 具体技术方案要求 | 需求文档摘要 |

---

## 模板：Step 3 — 开发

```
📋 R{round} Step 3 — 编码实现 到你了！

{round_title}

📄 需求文档：
https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/R{round}-product-requirements.md

📋 WORK_PLAN：
https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/WORK_PLAN.md

🔧 变更文件：
{file_changes}

{additional_context}

提交格式：feat(R{round}): Step 3 - {commit_description}

⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 3
```

**变量说明：**

| 变量 | 示例 | 来源 |
|:-----|:------|:------|
| `{file_changes}` | 变更文件清单，如 `server/web_viewer.py — +15 行` | 需求文档 §四 |
| `{additional_context}` | 架构师技术方案链接、注意事项 | Step 2 产出 |
| `{commit_description}` | 提交说明，如 `Web 服务增加 /api/workspaces 端点` | 需求文档标题 |

---

## 模板：Step 4 — 审查

```
📋 R{round} Step 4 — 代码审查 到你了！

{round_title}

📄 需求文档：
https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/R{round}-product-requirements.md

💻 提交：{commit_sha}
https://github.com/datahome73/ws-bridge/commit/{commit_sha}

📋 审查文件：
{files_list}

验收标准（{n} 项）：
{acceptance_criteria}

⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 4
```

**变量说明：**

| 变量 | 示例 | 来源 |
|:-----|:------|:------|
| `{commit_sha}` | `404d39a` | Step 3 产出 |
| `{files_list}` | 变更文件列表 | Step 3 产出 |
| `{acceptance_criteria}` | 验收标准逐项 | 需求文档 §三 |
| `{n}` | `8` | 验收项数量 |

---

## 模板：Step 5 — 测试

```
📋 R{round} Step 5 — 测试验证 到你了！

{round_title}

💻 提交：{commit_sha}
https://github.com/datahome73/ws-bridge/commit/{commit_sha}

🔍 验收标准（{n} 项）：
{acceptance_criteria_with_details}

⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 5
```

---

## 模板：Step 6 — 部署

```
📋 R{round} Step 6 — 合并部署 到你了！

{round_title}

💻 编码提交：{dev_commit}（{dev_name}）
✅ 审查通过（{review_name}）
🦐 测试通过（{qa_name}）

📋 操作：
{deploy_instructions}

⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 6
```

**变量说明：**

| 变量 | 示例 | 来源 |
|:-----|:------|:------|
| `{dev_commit}` | `404d39a` | Step 3 产出 |
| `{dev_name}` | `爱泰` | Pipeline Context |
| `{review_name}` | `小周` | Pipeline Context |
| `{qa_name}` | `泰虾` | Pipeline Context |
| `{deploy_instructions}` | 合并 dev→main + docker build + 重启 | Step 2 技术方案 + 部署惯例 |

---

## 消息公共字段（JSON 层）

所有派活消息使用同一个 JSON 结构：

```python
msg = {
    'type': 'message',
    'channel': '_inbox:server',
    'content': content,        # ← 上面模板渲染后的文本
    'from_name': '小谷',
    'agent_id': 'ws_f26e585f6479',
    'to_agent': '{target_agent_id}',
    'id': f'msg-{ts}',
    'ts': time.time(),
}
```

| 字段 | 固定值 | 说明 |
|:-----|:--------|:------|
| `type` | `message` | 固定 |
| `channel` | `_inbox:server` | 走 R102 中继 |
| `from_name` | `小谷` | PM 身份 |
| `agent_id` | `ws_f26e585f6479` | PM 的 agent_id |
| `to_agent` | 目标 bot 的 agent_id | 从 Pipeline Context 读取 |
| `content` | 模板渲染结果 | 按 Step 模板填充变量 |

---

## Pipeline Context JSON 结构（基于以上模板设计）

```json
{
  "round_name": "R106",
  "round_title": "Pipeline Context + Step 自动推进",
  "status": "running",
  "current_step": 1,
  "steps": [
    {"step": 1, "role": "pm",     "agent_id": "ws_f26e585f6479", "status": "pending"},
    {"step": 2, "role": "arch",   "agent_id": "ws_3f7cdd736c1c", "status": "pending"},
    {"step": 3, "role": "dev",    "agent_id": "ws_0bb747d3ea2a", "status": "pending"},
    {"step": 4, "role": "review", "agent_id": "ws_fcf496ca1b4f", "status": "pending"},
    {"step": 5, "role": "qa",     "agent_id": "ws_eab784ac7652", "status": "pending"},
    {"step": 6, "role": "ops",    "agent_id": "ws_c47032fa1f67", "status": "pending"}
  ],
  "references": {
    "requirements_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/R{round}-product-requirements.md",
    "work_plan_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R{round}/WORK_PLAN.md"
  },
  "artifacts": {
    "step2": {"tech_plan_url": ""},
    "step3": {"commit_sha": "", "files_changed": ""},
    "step4": {"review_report_url": ""},
    "step5": {"test_commit_sha": ""},
    "step6": {"merge_commit": ""}
  },
  "message_templates": {
    "step2": "📋 R{round} Step 2 — 技术方案 到你了！\n\n{round_title}\n\n📄 需求文档：{requirements_url}\n📋 WORK_PLAN：{work_plan_url}\n\n🔍 任务：{task_description}\n\n⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 2",
    "step3": "📋 R{round} Step 3 — 编码实现 到你了！\n\n{round_title}\n\n📄 需求文档：{requirements_url}\n📋 WORK_PLAN：{work_plan_url}\n\n🔧 变更文件：{file_changes}\n\n提交格式：feat(R{round}): Step 3 - {commit_description}\n\n⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 3",
    "step4": "📋 R{round} Step 4 — 代码审查 到你了！\n\n{round_title}\n\n📄 需求文档：{requirements_url}\n💻 提交：{commit_sha}\n\n📋 审查文件：{files_list}\n\n验收标准（{n} 项）：{acceptance_criteria}\n\n⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 4",
    "step5": "📋 R{round} Step 5 — 测试验证 到你了！\n\n{round_title}\n\n💻 提交：{commit_sha}\n\n🔍 验收标准（{n} 项）：{acceptance_criteria}\n\n⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 5",
    "step6": "📋 R{round} Step 6 — 合并部署 到你了！\n\n{round_title}\n\n💻 编码提交：{dev_commit}（{dev_name}）\n✅ 审查通过（{review_name}）\n🦐 测试通过（{qa_name}）\n\n📋 操作：{deploy_instructions}\n\n⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R{round} Step 6"
  }
}
```

---

## 自动接力逻辑（R106b 目标）

```
收到 "已完成 ✅ R{round} Step {N}"
  → 解析 {round} 和 {N}
  → 查 Pipeline Context 找 round_name == {round}
  → 更新步骤 N 状态为 completed
  → 若 N+1 <= 6：
     → 查 steps[N] 的 agent_id
     → 用 message_templates["step{N+1}"] 渲染消息
     → 填充已收集的 artifacts（commit_sha 等）
     → 发到 _inbox:server + to_agent
  → 若 N == 6：标记整个 pipeline 为 completed
```
