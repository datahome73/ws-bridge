# ws-bridge Inbox 通信协议 Skill 文档

> **轮次：** R114
> **类型：** 文档轮 — 编写 skill
> **日期：** 2026-07-14

---

## 一、概述

R114 将现有 `_inbox:server` 中继协议、`##` 命令协议、Step 完成消息 `##key=value` 格式、上下文注入协议提炼为 Hermes Agent skill（`inbox-communication-protocol`），供各 bot 在管线开发中加载使用。

核心新增协议定义：

1. **Step 完成消息 `##key=value` 格式** — Bot 完成 Step 时用 `##` 分隔符嵌入产出上下文
2. **Server 端解析闭环** — `_try_advance_pipeline` 从 content 提取 `##key=value` 写入 `PipelineContext.artifacts` → 下一步派活时 `_render_template` 自动注入
3. **各 Step 上下文需求表** — 每步需要的输入 key 和产出的输出 key

---

## 二、Skill 正文（`inbox-communication-protocol`）

### 2.1 通信架构总览

```
PM（小谷）              _inbox:server 中继              Step Bot
    │                        │                            │
    │── ##start##R{N} ──────→│ ① 创建管线 + 派活 Step 1   │
    │                        │── 自动派活 Step 1 ────────→│
    │                        │                            │
    │                        │←── ② ACK ✅ R{N} 收到！───┤
    │←── 系统转发 ACK ──────┤                            │
    │                        │      [Bot 干活...]         │
    │                        │                            │
    │                        │←── ③ 已完成 ✅ R{N} Step N →│
    │                        │    ##sha=xxx##files=...    │
    │←── 转发完成通知 ───────┤                            │
    │                        │── ④ 自动确认 ────────────→│
    │                        │                            │
    │                        │ ⑤ _try_advance_pipeline    │
    │                        │   → 提取 ##key=value 入   │
    │                        │     artifacts              │
    │                        │   → 自动派活 Step N+1 ───→│
```

#### 通道职责

| 通道 | 用途 | 发送方 | 接收方 |
|:-----|:------|:-------|:-------|
| `_inbox:<bot_agent_id>` | 任务派发 / 系统确认 | PM、Server | Bot |
| `_inbox:<PM_agent_id>` | 进度/结果通知 | Server | PM |
| `_inbox:server` | **Bot 回复中继** — 仅 bot 往这里发 | **Bot** | **Server 内部** |

#### 核心原则

- PM 禁止使用 `_inbox:server`
- Bot 回复统一走 `_inbox:server`，不直接回复 PM inbox
- Server 仅按内容前缀匹配规则处理（纯规则，零 LLM 依赖）

---

### 2.2 `##` 命令协议（PM 触发管线）

#### 格式

```
##start##R{N}##key=value##key2=value2
##status##R{N}
##stop##R{N}
##help
```

#### 示例

```
##start##R114##round_title=管线自动化闭环##requirements_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/R114-product-requirements.md
```

#### 命令说明

| 命令 | 作用 | 流程 |
|:-----|:-----|:-----|
| `##start` | 创建 PipelineContext + 派活 Step 1 | 刷新角色映射 → 构建 steps → 创建 ctx → transition_to(RUNNING) → `_auto_dispatch(ctx, 1)` |
| `##status` | 查询管线当前状态 | 返回 Step 状态表 |
| `##stop` | 停止管线 | ctx → CANCELLED |
| `##help` | 显示帮助 | |

#### 支持的 kv 参数（##start）

| key | 说明 | 示例 |
|:----|:-----|:-----|
| `round_title` | 人类可读标题 | `管线自动化闭环` |
| `requirements_url` | 需求文档 URL | `https://raw.githubusercontent.com/...` |
| `work_plan_url` | WORK_PLAN URL | `https://raw.githubusercontent.com/...` |

---

### 2.3 Bot 回复协议（_inbox:server 中继）

#### 前缀匹配规则

Bot 发往 `_inbox:server` 的消息，server **仅根据内容前缀**决定行为：

| 前缀 | 含义 | Server 行为 |
|:-----|:-----|:-----------|
| `ACK ✅` | ACK 确认 | 转发给 PM：`📬 {bot名称} 已接活` |
| `收到 ✅` | ACK 确认（同义） | 同上 |
| `✅ 完成` | 完成通知 | **转发 PM + 自动回确认给 bot + 自动推进管线** |
| `已完成 ✅` | 完成通知（同义） | 同上 |
| `退回 🔄` | 退回/拒绝 | 转发 PM + 自动确认 |
| `失败 ❌` | 失败报告 | 转发 PM + 自动确认 |
| `!` | 命令 | 透传到正常路由 |
| `##` | 管线命令 | `_handle_hash_cmd` 处理 |
| 其他 | 未知 | **沉默**（入库留痕，不转发不报错） |

#### Step 完成消息格式（核心协议）

**标准格式：**

```
已完成 ✅ R{N} Step {N}##key=value##key2=value2...
```

**示例：**

```
已完成 ✅ R114 Step 2##tech_plan_url=https://github.com/datahome73/ws-bridge/blob/dev/docs/R114/R114-tech-plan.md##design_decision=重构 handler 为纯函数模式
```

**解析逻辑（`_try_advance_pipeline` → 新增 `##` 解析）：**

```
输入: "已完成 ✅ R114 Step 2##sha=abc1234##files=main.py,handler.py"
  │
  ├─ 正则: r"已完成 ✅ R(\d+) Step (\d+)" → round_name=R114, step=2
  │
  ├─ 分割: content.split("##") → ["已完成 ✅ R114 Step 2", "sha=abc1234", "files=main.py,handler.py"]
  │
  ├─ 遍历 parts[1:]: "key=value" → artifacts["step2"]["sha"] = "abc1234"
  │                                     artifacts["step2"]["files"] = "main.py,handler.py"
  │
  ├─ 写入 PipelineContext:
  │     ctx.artifacts["step2"] = {"sha": "abc1234", "files": "main.py,handler.py"}
  │
  └─ 下一步派活时 _render_template 自动注入 {sha}, {files}
```

---

### 2.4 上下文注入协议（PipelineContext → 模板）

#### 变量来源优先级

```
1. ctx.artifacts[前一步的产出 KV]    — 最高（覆盖同名变量）
2. ctx.references[文档 URL]          — 中
3. ctx 基本信息 (round_name, round_title) — 低
```

#### 模板渲染

`_render_template(template, ctx, step_num)` 用 Python 的 `str.replace()` 填充 `{变量名}` 占位符。

```python
vars = {
    "round":           ctx.round_name,           # "R114"
    "round_title":     ctx.round_title,          # 人类可读标题
    "requirements_url": ctx.references.get("requirements_url", ""),
    "work_plan_url":    ctx.references.get("work_plan_url", ""),
}
# 补充 artifacts（覆盖同名变量）
for step_key, step_artifacts in ctx.artifacts.items():
    if isinstance(step_artifacts, dict):
        vars.update(step_artifacts)
# 填充模板中的 {var} 占位符
for key, value in vars.items():
    template = template.replace(f"{{{key}}}", str(value))
```

#### 默认模板变量集

| 变量 | 来源 | 示例 |
|:-----|:------|:------|
| `{round}` | PipelineContext | `R114` |
| `{round_title}` | PipelineContext | `管线自动化闭环` |
| `{requirements_url}` | ctx.references | `https://raw.githubusercontent.com/...` |
| `{work_plan_url}` | ctx.references | `https://raw.githubusercontent.com/...` |
| `{sha}` * | ctx.artifacts.step3 | `abc1234` |
| `{tech_plan_url}` * | ctx.artifacts.step2 | `https://github.com/...` |
| `{files}` * | ctx.artifacts.step3 | `main.py,handler.py` |

> * 这些变量来自上一步 bot 的 `##key=value` 完成消息，不是固定的。

---

### 2.5 Step 上下文需求表

> 以下为各 Step 的输入上下文需求和产出 `##key=value` 规范。🟡 部分字段来自 bot 调研反馈，待最终确认。

#### Step 1 — PM（小谷）

| 方向 | 内容 |
|:-----|:------|
| 工作 | 标注 WORK_PLAN 已审核，推 git |
| 接收的输入 | `{round_title}`（来自 `##start` kv） |
| 产出的 `##` keys | （无，Step 1 由 PM 手动完成） |

#### Step 2 — 架构师（小开）

| 方向 | 内容 |
|:-----|:------|
| 工作 | 编写技术方案，设计系统架构 |
| 需要的 `##key` | `requirements_url`（需求文档）、`work_plan_url`（WORK_PLAN） |
| 产出的 `##` keys | `tech_plan_url`（技术方案文档 URL）、`design_decision`（关键设计决策） |

**完成消息示例：**
```
已完成 ✅ R114 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/R114-tech-plan.md##design_decision=重构 handler 为纯函数模式
```

#### Step 3 — 开发（爱泰）

| 方向 | 内容 |
|:-----|:------|
| 工作 | 根据技术方案编码实现 |
| 需要的 `##key` | （来自爱泰调研）`tech_plan_url`（技术方案）、`requirements_url`（需求）、`scope_files`（变更文件范围）、`base_branch`（基线分支）、`design_decision`（设计决策）、`api_contract`（API 契约）、`data_model_change`（数据模型变更）、`test_scope`（测试范围） |
| 产出的 `##` keys | `commit_sha`（提交 SHA）、`files_changed`（变更文件列表）、`commit_description`（提交说明） |

**完成消息示例：**
```
已完成 ✅ R114 Step 3##commit_sha=abc1234##files_changed=server/main.py,server/handler.py##commit_description=Add pipeline auto-archive feature
```

#### Step 4 — 审查（小周）

| 方向 | 内容 |
|:-----|:------|
| 工作 | 代码审查 — 审查代码质量和设计合理性 |
| 需要的 `##key` | `commit_sha`（提交 SHA，用于链接到 diff）、`files_changed`（审查文件列表）、`requirements_url`（对照需求）、`acceptance_criteria`（验收标准） |
| 产出的 `##` keys | `review_report_url`（审查报告 URL）、`review_decision`（通过/需修改/退回） |

**完成消息示例：**
```
已完成 ✅ R114 Step 4##review_report_url=https://github.com/datahome73/ws-bridge/blob/dev/docs/R114/R114-review-report.md##review_decision=通过
```

#### Step 5 — QA（泰虾）

| 方向 | 内容 |
|:-----|:------|
| 工作 | 测试验证 — 运行测试，验证验收标准 |
| 需要的 `##key` | `commit_sha`（编码提交 SHA）、`files_changed`（变更范围）、`acceptance_criteria`（验收标准详情） |
| 产出的 `##` keys | `test_result`（测试结果：PASS/FAIL）、`test_commit_sha`（测试提交 SHA）、`test_report_url`（测试报告 URL） |

**完成消息示例：**
```
已完成 ✅ R114 Step 5##test_result=PASS##test_commit_sha=def5678##test_report_url=https://github.com/datahome73/ws-bridge/blob/dev/docs/R114/R114-test-report.md
```

#### Step 6 — 运维（小爱）

| 方向 | 内容 |
|:-----|:------|
| 工作 | 合并部署 — 合并 dev→main，Docker 构建，部署 |
| 需要的 `##key` | `dev_commit`（编码提交 SHA）、`review_name`（审查者）、`qa_name`（测试者）、`test_result`（测试结果）、`test_commit_sha`（测试提交 SHA） |
| 产出的 `##` keys | `merge_commit_sha`（合并提交 SHA）、`deploy_version`（部署版本 Tag） |

**完成消息示例：**
```
已完成 ✅ R114 Step 6##merge_commit_sha=ghi9012##deploy_version=v2.73
```

#### `##` 键命名规范

| 规范 | 说明 | 示例 |
|:-----|:------|:------|
| 全小写 + 下划线 | 蛇形命名法 | `tech_plan_url`, `commit_sha` |
| 语义明确 | 不用缩写歧义词 | `commit_sha` 优于 `sha`，`files_changed` 优于 `files` |
| URL 加 `_url` 后缀 | 标识链接字段 | `tech_plan_url`, `requirements_url` |
| 结果/状态用 `_result`/`_decision` | 标识决策字段 | `test_result`, `review_decision` |
| 版本号用 `_version` | 标识版本 | `deploy_version` |

---

### 2.6 完整管线全流程（6 Step 自动接力）

#### 启动

```
PM → _inbox:server:
  ##start##R114##round_title=管线自动化闭环##requirements_url=...
```

Server:
1. 创建 PipelineContext + transition_to(RUNNING)
2. _auto_dispatch(ctx, 1) → 派活 Step 1 给 PM 自己

#### Step 1 - Step 6 自动接力

```
# Step 1 (PM):  标注 WORK_PLAN 已审核
# PM 审核需求文档 → 推 git

# Bot 回复 → server 自动处理:
_inbox:server:
  已完成 ✅ R114 Step 1##work_plan_url=...

Server auto-dispatch → Step 2 (arch):
_inbox:ws_3f7cdd736c1c:
  📋 R114 Step 2 — 技术方案 到你了！
  📄 需求文档：{requirements_url}
  📋 WORK_PLAN：{work_plan_url}

# Step 2 (arch 小开): 写技术方案 → git push
_inbox:server:
  已完成 ✅ R114 Step 2##tech_plan_url=https://...

Server auto-dispatch → Step 3 (dev 爱泰):
  artifacts["step2"] = {"tech_plan_url": "https://..."}
  模板 {tech_plan_url} 被填充

# Step 3 (dev 爱泰): 编码 → git push
_inbox:server:
  已完成 ✅ R114 Step 3##sha=abc1234##files=server/main.py,server/handler.py

Server auto-dispatch → Step 4 (review 小周):
  artifacts["step3"] = {"sha": "abc1234", "files": "server/main.py,server/handler.py"}
  模板 {sha} → abc1234, {files} → server/main.py,server/handler.py

# Step 4-6 同理...
```

#### 管线完成

```
# Step 6 完成后
if next_step > ctx.total_steps:
    mgr.transition_to(round_name, COMPLETED)
    mgr.archive(round_name)
```

---

### 2.7 各 bot CheckList

每个 bot 必须满足以下行为：

| # | 行为 | 要求 |
|:-:|:-----|:-----|
| 1 | 收到 `_inbox:` 消息 | 必须处理，不因 `mention_mode` 过滤 |
| 2 | 回复 ACK | 5 秒内回复到 `_inbox:server`，`ACK ✅ R{N} 收到！` |
| 3 | 执行任务 | LLM 正常处理 |
| 4 | 回复完成 | 完成后回复到 `_inbox:server`，`已完成 ✅ R{N} Step {N}##key=value` |
| 5 | 不回复确认 | 收到 server 自动确认后不再回复 |
| 6 | `##` 嵌入 | 完成消息中嵌入下一 bot 需要的上下文信息 |

---

## 三、参考代码入口

| 模块 | 文件 | 关键函数 |
|:-----|:-----|:---------|
| `_handle_server_relay` | `server/ws_server/main.py` | 前缀匹配 + 中继转发 |
| `_handle_hash_cmd` | 同上 | `##start/status/stop/help` |
| `_try_advance_pipeline` | 同上 | PipelineContext advance + 自动派活下一步 |
| `_auto_dispatch` | 同上 | 派活消息构建 + _send_to_agent |
| `_render_template` | 同上 | 模板变量填充 |
| `PipelineContext` | `server/ws_server/pipeline_context.py` | artifacts / references / message_templates 字段 |

---

## 四、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-07-14 | R114 首次编写 — 协议规范 + Step 上下文需求表 |
