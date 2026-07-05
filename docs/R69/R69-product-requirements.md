# R69 产品需求 — 收件箱上下文增强 + 待办清理 🔄

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-05
> **基线：** `a92e9e5`（R68 合并部署完成）
> **R68 测试状态：** ✅ 37/37 全部通过
> **本轮改动范围：** `server/handler.py` + 文档清理

---

## 0. 先验：R68 收件箱通道验证

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| `INBOX_CHANNEL_PREFIX` 常量 | ✅ | `shared/protocol.py` L169 |
| 收件箱工具函数（get/is/resolve） | ✅ | `server/persistence.py` L154-170 |
| `handle_broadcast` 收件箱路由 | ✅ | `handler.py` L4115-4151（admin 拦截后 → channel resolution 前） |
| 权限：仅 admin 可写 | ✅ | `sender_role != "admin"` 检查 |
| 单播投递 | ✅ | `if aid == owner_id` 过滤 |
| `_send_inbox_task()` 函数 | ✅ | `handler.py` L2240-2309 |
| step_complete 走收件箱 | ✅ | `_cmd_step_complete()` 调用 |
| step_handoff 走收件箱 | ✅ | `_cmd_step_handoff()` + fix fallback |
| 工作室轻量通知 | ✅ | `handler.py` L2304-2309 |
| 审查 Warnings（W-1/W-2） | ✅ 已修复 | `89ac235` + `3b5a101` |
| **总计** | **✅ 37/37 全部通过** | R68 测试报告 |

**结论：** R68 收件箱通道基础设施完整，管线交接收件箱派活正常运转。

---

## 1. 问题背景

### 1.1 现状：收件箱消息内容太薄

当前 `_send_inbox_task()` 生成的收件箱消息：

```
📥 任务分配 — R69 Step「编码」

背景上下文：
  上一 Step 产出：abc1234

任务描述：
  请按技术方案完成 step3

参考文档：
  📄 需求：https://...
  📋 WORK_PLAN：https://...
  🔗 上一步产出：abc1234
```

**问题：** Arch 花了 15 分钟写技术方案（关键决策、选型、约束），这些信息在 Dev 的收件箱里完全丢失。Dev 只知道「上一步产出 abc1234」，但不知道**上一步决定了什么**。

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | **`step_outputs` 太瘦** | 只存 `{sha, timestamp}`，缺 `summary`/`title`/`artifact_url` |
| 2 | **收件箱消息静态模板** | 硬编码字符串，不会从 step_outputs 读取结构化信息 |
| 3 | **`!step_complete` 参数太少** | 只支持 `--output`，不支持传递关键结论/URL |
| 4 | **前序产出摘要缺失** | Dev 需读完 Arch 全部文档才能知道关键结论 |

### 1.2 R68 审查遗留项

R68 代码审查报告遗留 1 个 💡 建议（新入 TODO L-5）：

| 项 | 描述 | 修复 |
|:---|:-----|:-----|
| L-5 | `_send_inbox_task` payload 缺 `agent_id`/`from_agent` 字段 | 函数签名 +2 调用点传 `pm_agent_id` |

同时 TODO 中还堆积了 3 个低成本清理项（F-15、L-4、D-3/D-4）。

---

## 2. 功能需求

### 设计原则

> **收件箱是「干净任务队列」，消息内容应该让 Bot 一眼看懂前因后果，不需要再跳转额外文档。**
>
> 核心思路：`!step_complete` 时携带的结构化信息（summary + URL）→ 写入 `step_outputs` → `_send_inbox_task` 读取并渲染到收件箱消息中。

---

### 方向 A（核心）：收件箱消息上下文注入 🔴 P0 — ~35 行

#### A1 — `step_outputs` 数据结构扩展

当前：

```python
step_outputs["step2"] = {"sha": "abc1234", "timestamp": ...}
```

扩展为：

```python
step_outputs["step2"] = {
    "sha": "abc1234",
    "title": "技术方案",
    "output_desc": "Agent Card 存储格式迁移设计",
    "summary": "选型: FastAPI, DB: SQLite, 保持向后兼容",
    "artifact_url": "https://github.com/datahome73/ws-bridge/blob/dev/docs/R69/R69-tech-plan.md",
    "timestamp": ...,
}
```

**新字段来源：**

| 字段 | 来源 | 非必填？ |
|:-----|:------|:--------:|
| `title` | 自动从 `step_config` 的 `title` 注入 | ❌ 自动填充 |
| `output_desc` | 自动从 `step_config` 的 `output_desc` 注入 | ❌ 自动填充 |
| `summary` | **`!step_complete --summary/-s`** 参数 | ✅ 可选（缺省=空） |
| `artifact_url` | **`!step_complete --artifact-url/-u`** 参数 | ✅ 可选（缺省=自动推断） |

#### A2 — `!step_complete` 新增参数

```python
# 新增可选参数
# --summary / -s:  关键结论/摘要（≤200 字符）
# --artifact-url / -u:  产出物 URL（缺省时自动推断）

# 例：
!step_complete step2 --output def1234 --summary "选型:FastAPI,DB:SQLite,兼容优先" --artifact-url https://...
```

**自动 URL 推断规则：**

| Step | 角色 | 产出类型 | 推断 URL |
|:----:|:-----|:---------|:---------|
| Step 2 | arch | 技术方案 | `{repo}/docs/{round}/{round}-tech-plan.md` |
| Step 4 | review | 审查报告 | `{repo}/docs/{round}/{round}-review-report.md` |
| Step 5 | qa | 测试报告 | `{repo}/docs/{round}/test-report.md` |
| Step 3/6 | dev/admin | 代码/部署 | 不推断（SHA 替代） |

#### A3 — `_send_inbox_task` 消息模板增强

改造后收件箱消息：

```
📥 任务分配 — R69 Step 3「编码」
━━━━━━━━━━━━━━━━━━━━━━━
🏗️ 前序 Step 2「技术方案」产出 ✅ (def1234)
  └ 💡 关键结论: 选型FastAPI, DB:SQLite, 兼容优先
  └ 🔗 技术方案: https://.../R69-tech-plan.md

📄 参考资料:
  📄 需求: https://...
  📋 WORK_PLAN: https://...

🎯 你的任务: 请按技术方案完成编码

完成后:
  1. git push dev
  2. !step_complete step3 --output <sha>
```

**改造点：** `_send_inbox_task()` 中读取 `step_outputs`，动态渲染前序 Step 的 title/summary/artifact_url。

#### A4 — `step_outputs` 记录点增强

当前 `step_outputs` 在 `_cmd_step_complete()` 中记录（handler.py L2337-2343）：

```python
step_outputs[step_name] = {
    "sha": output_ref or "",
    "timestamp": time.time(),
}
```

改造后：

```python
step_outputs[step_name] = {
    "sha": output_ref or "",
    "title": step_config.get(step_name, {}).get("title", step_name),
    "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
    "summary": params.get("summary", step_config.get(step_name, {}).get("output_desc", "")),
    "artifact_url": params.get("artifact_url", _infer_artifact_url(step_name, round_name)),
    "timestamp": time.time(),
}
```

### 方向 B（清理）：低成本 TODO 项 🟡 P2 — ~20 行

#### B1 — L-5：`_send_inbox_task` payload 补齐 agent_id

**代码审查💡建议：** `inbox_payload` 缺少 `from_agent`/`agent_id` 字段，与 `handle_broadcast` inbox intercept 的 payload 不一致。

**改动：**
1. `_send_inbox_task` 函数签名新增 `pm_agent_id: str` 参数
2. `inbox_payload` 字典添加 `"agent_id": pm_agent_id` / `"from_agent": pm_agent_id`
3. 2 处调用点（step_complete + step_handoff）传当前 pm agent_id

**代码示例：**

```python
# 函数签名 + payload
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
    pm_agent_id: str,      # ← 新增
) -> None:
    ...
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "agent_id": pm_agent_id,        # ← 新增
        "from_agent": pm_agent_id,      # ← 新增
        "content": inbox_msg, "ts": time.time(),
    })
```

**调用点传递参数**（step_complete 和 step_handoff 中 `sender_id` 即 pm_agent_id）：

```python
await _send_inbox_task(
    target_agent_id, round_name, next_step, step_config,
    output_ref, ws_id, pm_name, sender_id,  # ← 传 sender_id
)
```

#### B2 — F-15：`!workspace_reset` 命令（~5 行）

在 `_ADMIN_COMMANDS` 字典中注册 `workspace_reset`，功能：
1. 关闭当前活跃工作室 → 归档
2. 成员频道重置为大厅
3. 管线状态清理

实际上是 `!workspace_close` + `!pipeline_close` 的快捷组合。

**实现思路（handler.py _ADMIN_COMMANDS 附近）：**

```python
"workspace_reset": {
    "handler": _cmd_workspace_reset,
    "min_role": "admin",
    "help": "重置工作室 → 关闭当前工作室 + 清理管线状态",
},
```

```python
async def _cmd_workspace_reset(sender_id: str, params: dict) -> str:
    """Reset: close active workspace + clear pipeline state."""
    # 1. Close active workspace
    ws = ws_mod.get_active_workspace(sender_id)
    if not ws:
        return "❌ 无活跃工作室"
    ws_id = ws.id
    ws_mod.archive_workspace(ws_id)
    # 2. Reset agent channels to lobby
    _broadcast_active_channel(p.LOBBY)
    # 3. Clear pipeline state
    for pid in list(_PIPELINE_STATE.keys()):
        _PIPELINE_STATE[pid]["active"] = False
    return f"✅ 工作室 {ws_id[:12]} 已重置（归档 + 回大厅 + 管线清理）"
```

#### B3 — D-3/D-4：文档脱敏 + TODO 更新（文档，~3 文件改动）

| 文件 | 操作 |
|:-----|:------|
| `docs/README.md` | 检查/清理内部角色引用 → 脱敏 |
| `docs/*/WORK_PLAN.md` | 检查含内部分工/角色名的段落 → 替换为通用角色名 |
| `docs/TODO.md` | 更新 v2.33 → v2.34，新增 R69 完成条目 |

#### B4 — L-4：Gateway plugin 配置检查（检查，无需代码）

检查 `gateway-plugin/plugin.yaml` 无内部 URL/端口/角色名泄露。

### 方向 C（体验）：`!pipeline_status` 上下文展示 🟡 P1 — ~10 行

#### C1 — 状态展示 Step 产出详情

当前输出：

```
📦 Step 产出:
  step2: abc1234
```

改造后：

```
📦 Step 产出:
  step2 🏗️ 技术方案 — def1234 (7s ago)
    └ 💡 选型:FastAPI, DB:SQLite, 兼容优先
    └ 🔗 https://.../R69-tech-plan.md
  step3 💻 编码 — a1b2c3d (2m ago)
    └ 💡 实现了收件箱路由
```

**代码位置：** handler.py L512-517（`_pipeline_status` 中 step_outputs 展示段）

---

## 3. 验收标准

### 🎯 3.1 方向 A（核心）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | `!step_complete` 支持 `--summary/-s` | 参数解析 → 存入 `step_outputs.summary` | 执行命令 → grep pstate |
| ✅-2 | `!step_complete` 支持 `--artifact-url/-u` | 参数解析 → 存入 `step_outputs.artifact_url` | 执行命令 → grep pstate |
| ✅-3 | 不传新参数时向下兼容 | 旧调用不报错，summary=output_desc | 不带参数 → ✅ |
| ✅-4 | `step_outputs` 含 `title` 字段 | 自动从 `step_config` 注入 | 检查 step_outputs |
| ✅-5 | `step_outputs` 含 `output_desc` 字段 | 自动从 `step_config` 注入 | 检查 step_outputs |
| ✅-6 | 未传 `--artifact-url` 时自动推断 | step2 → 生成 R69-tech-plan.md raw URL | 不传 -u → 检查 |
| ✅-7 | `_send_inbox_task` 读取 `step_outputs` | 收件箱消息含前序 Step 的 title/summary/URL | 启动管线 → 检查收件箱消息 |
| ✅-8 | 收件箱消息含完整前序上下文 | 格式如 `🏗️ 前序 Step 2「xx」产出 ✅` | 检查消息模板 |
| ✅-9 | 无 summary 时降级（不显示） | summary="" 时前序结论行不出现 | 执行不传 summary |
| ✅-10 | summary ≤200 字符截断 | 超过 200 字符自动截断 | 传长字符串 → 检查 |

### 🎯 3.2 方向 B（清理）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-11 | L-5：`_send_inbox_task` payload 含 `agent_id`/`from_agent` | inbox_payload JSON 含两字段 | grep 检查 |
| ✅-12 | `!workspace_reset` 命令可用 | 关闭工作室 + 回大厅 + 清理 | 执行命令 → 检查状态 |
| ✅-13 | `docs/README.md` 无内部角色名 | grep 零匹配 | grep 检查 |
| ✅-14 | `gateway-plugin/plugin.yaml` 无内部泄露 | grep 零匹配 | 目视检查 |
| ✅-15 | TODO.md 版本更新 + R69 条目 | v2.34，R69 完成 ✅ | 检查 TODO.md |

### 🎯 3.3 方向 C（增强）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-16 | `!pipeline_status` 展示 Step 标题+摘要+URL | 状态输出含结构化的产出详情 | 执行命令 → 检查格式 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| `_render_context` 模板引擎改造 | 当前 step_outputs 已含所需字段 | 无需额外模板变量，收件箱消息直接硬编码读取 |
| `${steps.stepN.*}` 模板变量扩展 | 当前收件箱不走 frontmatter context，直接硬编码渲染 | 简化实现 |
| Web 端管线仪表盘 | 前端改造 | 专属轮次 |
| F-3 workspace_admin 角色 | 角色体系改造 | 专属轮次（影响面大） |
| R36-B 新虾注册流程 | 注册流程改造 | 专属轮次（涉及 auth） |
| F-9 Web 端 Tab 页空白 | 纯前端问题 | 专属轮次 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** `_cmd_step_complete()` 新增 `--summary`/`--artifact-url` + `step_outputs` 扩展 + `_send_inbox_task` 消息模板增强 + payload agent_id + `_infer_artifact_url()` 新函数 + `!workspace_reset` 命令 | ~55 行 |
| `server/handler.py` | **修改** `_pipeline_status()` 展示 Step 标题/摘要/URL | ~10 行 |
| `docs/TODO.md` | 版本更新 + R69 条目 | ~5 行 |
| `docs/README.md` | 脱敏检查 | ~0 行（无代码） |
| `gateway-plugin/plugin.yaml` | 脱敏检查 | ~0 行（无代码） |
| **合计** | | **~70 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| Agent 不传 `--summary` | summary 为空，不显示前序结论行 | 降级为不渲染，不报错 |
| summary 含特殊字符 | 消息格式错乱 | 限制 ≤200 char + `.replace()` 常见有害字符 |
| `_send_inbox_task` 老调用的兼容性 | 函数签名新增 `pm_agent_id` 参数 | 2 个调用点已确认全部更新 |

---

## 6. 脱敏检查清单

- [ ] docs/R69/*.md 零内部名残留
- [ ] `grep -nE 'bot名|内部名|真实ID' docs/R69/*.md` 零匹配
- [ ] handler.py 代码零内部 URL/端口泄露
- [ ] gateway-plugin/plugin.yaml 零内部信息
- [ ] docs/README.md 零内部角色名
- [ ] 使用角色名/通用名（admin/PM/dev/arch/review/QA）替代具体 bot 名

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — 收件箱上下文增强 + TODO 清理 |
