# ws-bridge Inbox 通信协议 v3.0

> **轮次：** R115
> **版本：** v3.0
> **类型：** 通信协议定义（bot + server 双视角）
> **状态：** ✅ 定稿
> **日期：** 2026-07-15
> **前置：** R111（##命令）+ R114（Step完成协议）+ R115（Artifact注入）
>
> **supersedes:** `docs/inbox-message-protocol.md` (v2.0), `docs/R114/R114-inbox-communication-protocol-skill.md`

---

## 一、概述

本文档统一定义 ws-bridge 管线体系中所有参与者（bot、PM、Server）之间的消息协议。v3.0 合并了三个阶段的能力：

| 阶段 | 能力 | 轮次 | 状态 |
|:----:|:-----|:----:|:----:|
| 基础 | Inbox 消息收发 + 中继路由 | R87 | ✅ v2.0 |
| 管线 | `##start/status/stop` 管线命令 | R111 | ✅ |
| 完成 | `已完成 ✅` Step 完成通知 + `##key=value` 产物注入 | R114+R115 | ✅ |

---

## 二、消息通道

### 2.1 通道类型

| 通道 | 格式 | 用途 |
|:-----|:-----|:------|
| **个人收件箱** | `_inbox:{agent_id}` | 接收发给自己的消息 |
| **中继通道** | `_inbox:server` | 所有 bot 回复的固定目标 |
| **管理通道** | `_admin` | 管理员命令（!命令），仅限 Level 4+ |

### 2.2 发送规则

- ✔ 所有 bot **回复** → 固定发到 `_inbox:server`
- ✔ PM 派活 → `_inbox:server` + `to_agent` 顶层字段
- ✔ 管理员命令 → `_admin`
- ❌ 禁止直接发到其他 bot 的 `_inbox:{agent_id}`（除非 Level 2 手工直透）

---

## 三、消息格式

### 3.1 收到的消息（inbox JSON）

所有发给 bot 的消息遵循以下 JSON schema：

```json
{
    "type": "broadcast",
    "channel": "_inbox:<接收者_agent_id>",
    "from_name": "发送者显示名",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容",
    "id": "消息唯一ID",
    "ts": 1234567890.0
}
```

| 字段 | 说明 |
|:-----|:------|
| `channel` | 以 `_inbox:` 开头 → 确认是发给你的消息 |
| `from_agent` | 发送者的 agent_id |
| `content` | 消息文本内容（任务/通知/回复） |
| `id` | 消息唯一 ID（去重用） |
| `ts` | Unix 时间戳 |

### 3.2 发送的消息格式

发送消息使用标准 JSON payload：

```json
{
    "type": "message",
    "channel": "_inbox:server",
    "content": "消息内容"
}
```

如需定向派活（PM → 指定 bot）：

```json
{
    "type": "message",
    "channel": "_inbox:server",
    "to_agent": "ws_<target_agent_id>",
    "content": "🏗️ R115 Step 2 — 技术方案..."
}
```

---

## 四、前缀路由规则（Server 视角）

`_inbox:server` 中收到的所有消息，Server 根据 `content` 前缀匹配路由。**匹配顺序决定优先级：**

| 优先级 | 前缀 | 功能 | Router | 起始 R |
|:------:|:-----|:-----|:-------|:------:|
| 1 | `##` | 管线命令（start/status/stop/help） | `_handle_hash_cmd()` | R111 |
| 2 | `test ✅` | 回路测试 | 直接回复 ✅ | R96 |
| 3 | `ACK ✅` / `收到 ✅` | Bot 接活确认 | 转发 PM | R87 |
| 4 | `已完成 ✅` / `✅ 完成` | Step 完成通知 | 转发 PM + 自动确认 + 提取 artifacts + 推进 Step | R87/R115 |
| 5 | `退回 🔄` | 退回 | 转发 PM + 自动确认 | R87 |
| 6 | `失败 ❌` | 失败 | 转发 PM + 自动确认 | R87 |
| 7 | `!` 开头 | 管理员命令 | 透传 `_admin` | R82 |
| 8 | `to_agent` 字段 | 定向派活 | 中继转发到目标 bot | R102 |
| 9 | PM 守卫 | PM 误发到 `_inbox:server` | 拒绝 + 提示用 bot 收件箱 | R87 |

**关键规则：**
- 规则 1（`##`）插入在 PM 守卫**之前**，非 PM 也能启动管线
- 规则 4 自动调用 `_extract_artifact_kv()` 提取 `##key=value` 并写入 `ctx.artifacts`
- 规则 8 要求 `to_agent` 在 JSON 顶层，而非 content 内嵌

---

## 五、`##` 管线命令（Bot ↔ Server）

### 5.1 命令表

| 命令 | 格式 | 功能 | 发送者 |
|:-----|:-----|:------|:-------|
| `##start` | `##start##R{N}##k=v` | 创建管线 + 派活 Step 1 | PM / 任意 Level 4+ |
| `##status` | `##status##R{N}` | 查询管线当前状态 | 任意认证 agent |
| `##stop` | `##stop##R{N}` | 停止/归档管线 | PM |
| `##help` | `##help` | 列出支持的命令 | 任意 |

### 5.2 `##start` 解析规则

```python
content = "##start##R115##round_title=xxx##requirements_url=yyy"
parts = content.split("##")
# → ["", "start", "R115", "round_title=xxx", "requirements_url=yyy"]
```

| 段 | 位置 | 说明 |
|:---|:----:|:------|
| 命令 | `parts[1]` | `start` / `status` / `stop` / `help` |
| 轮次名 | `parts[2]` | 如 `R115`，自动 `.upper()` |
| key=value | `parts[3:]` | 可选，`split("=", 1)` 解析，value 不含 `##` |

### 5.3 `##start` 生命周期

```
发 ##start##R115##k=v
  → _handle_hash_cmd 解析
    → _handle_hash_start
      → mgr.exists(R115) ? 拒绝重复 : 创建 PipelineContext
        → 填充 steps / references / templates
          → mgr.transition_to(RUNNING)
            → _auto_dispatch(ctx, 1) 派活 Step 1 → PM
              → 回复发送者 "✅ R115 管线已启动"
```

---

## 六、管线 Step 完成协议（Bot 视角）

### 6.1 通用格式

```
已完成 ✅ R{N} Step {N}##key1=value1##key2=value2
```

- 所有完成消息统一以 `已完成 ✅` 开头（空格敏感）
- 嵌入的上下文信息用 `##key=value` 格式，依次拼接
- `##key=value` 中 key 全小写蛇形，value 不含裸 `##`
- URL 中的单个 `#` 安全（不被 `##` 匹配器影响）
- URL 中的 `=` 安全（使用 `split("=", 1)` 只分割第一个 `=`）

### 6.2 6 步协议详表

#### Step 1 — PM 工作计划提交

```
已完成 ✅ R{N} Step 1##work_plan_url=<raw URL>
```

| `##` key | 必填 | 说明 |
|:---------|:----:|:------|
| `work_plan_url` | ✅ | WORK_PLAN 文档的 GitHub raw URL |

#### Step 2 — Arch 技术方案

```
已完成 ✅ R{N} Step 2##tech_plan_url=<raw URL>##design_decision=<摘要>
```

| `##` key | 必填 | 说明 |
|:---------|:----:|:------|
| `tech_plan_url` | ✅ | 技术方案文档的 GitHub raw URL |
| `design_decision` | 可选 | 关键设计决策的文字摘要 |

#### Step 3 — Dev 编码实现

```
已完成 ✅ R{N} Step 3##commit_sha=<SHA>##files_changed=<列表>##commit_description=<说明>
```

| `##` key | 必填 | 说明 |
|:---------|:----:|:------|
| `commit_sha` | ✅ | commit SHA（推荐全量，至少 7 位） |
| `files_changed` | ✅ | 变更文件列表，逗号分隔 |
| `commit_description` | 可选 | 提交说明文字 |
| `branch_name` | 可选 | 推送分支名（默认 `dev`） |

#### Step 4 — Review 代码审查

```
已完成 ✅ R{N} Step 4##review_report_url=<raw URL>##review_decision=<结论>
```

| `##` key | 必填 | 说明 |
|:---------|:----:|:------|
| `review_report_url` | ✅ | 审查报告的 GitHub raw URL |
| `review_decision` | ✅ | `通过` / `需修改` / `退回` |

#### Step 5 — QA 测试验证

```
已完成 ✅ R{N} Step 5##test_result=<结果>##test_report_url=<raw URL>
```

| `##` key | 必填 | 说明 |
|:---------|:----:|:------|
| `test_result` | ✅ | `PASS` / `FAIL` |
| `test_report_url` | ✅ | 测试报告的 GitHub raw URL |
| `test_commit_sha` | 可选 | 测试用的 commit SHA |

#### Step 6 — Ops 合并部署

```
已完成 ✅ R{N} Step 6##merge_commit_sha=<SHA>##deploy_version=<版本>
```

| `##` key | 必填 | 说明 |
|:---------|:----:|:------|
| `merge_commit_sha` | ✅ | 合并 dev→main 的 merge commit SHA |
| `deploy_version` | 可选 | 部署版本号 / Docker Tag |

### 6.3 示例：完整 6 步消息链

```
##start##R115##round_title=Artifact注入
已完成 ✅ R115 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/WORK_PLAN.md
已完成 ✅ R115 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-tech-plan.md##design_decision=独立函数+零改动
已完成 ✅ R115 Step 3##commit_sha=abc1234##files_changed=server/ws_server/main.py,tests/test_r115.py##commit_description=R115: artifact injection##branch_name=dev
已完成 ✅ R115 Step 4##review_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-review-report.md##review_decision=通过
已完成 ✅ R115 Step 5##test_result=PASS##test_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-test-report.md
已完成 ✅ R115 Step 6##merge_commit_sha=def5678##deploy_version=v2.74
##stop##R115
```

---

## 七、Artifact 注入机制（Server 内部）

### 7.1 `_extract_artifact_kv()`

当 `已完成 ✅` 消息到达 `_handle_server_relay`，规则 4 触发 `_try_advance_pipeline()`。该函数内部调用：

```python
def _extract_artifact_kv(content: str) -> dict[str, str]:
    parts = content.split("##")
    result = {}
    for p in parts[1:]:          # parts[0] 是前缀，跳过
        if "=" in p:
            k, v = p.split("=", 1)  # 只分割第一个 =
            if k.strip():
                result[k.strip()] = v
    return result
```

### 7.2 写入顺序（同步→异步）

```python
# 在 _try_advance_pipeline() 内部：
_kv = _extract_artifact_kv(content)       # 1. 同步：提取
if _kv:
    step_key = f"step{completed_step}"
    ctx.artifacts[step_key] = _kv          # 2. 同步：写入内存
    mgr.save()                              # 3. 同步：持久化
asyncio.ensure_future(mgr.advance_step(...)) # 4. 异步：推进
```

### 7.3 Artifacts 数据结构

```json
{
  "step1": { "work_plan_url": "https://..." },
  "step2": { "tech_plan_url": "https://...", "design_decision": "..." },
  "step3": { "commit_sha": "abc1234", "files_changed": "main.py", "commit_description": "feat: x" },
  "step4": { "review_report_url": "https://...", "review_decision": "通过" },
  "step5": { "test_result": "PASS", "test_report_url": "https://..." },
  "step6": { "merge_commit_sha": "def5678", "deploy_version": "v2.74" }
}
```

### 7.4 模板变量优先级

`_render_template()` 中变量解析优先级：

| 优先级 | 来源 | 示例变量 |
|:------:|:-----|:---------|
| 1 (高) | `artifacts[step].key` | `tech_plan_url`, `commit_sha` |
| 2 | `references` | `requirements_url`, `work_plan_url` |
| 3 (低) | 基础字段 | `round`, `round_title` |

---

## 八、Bot 回复生命周期（完整时序）

```
                Bot                            Server                           PM
                 │                               │                              │
  ★ 收到任务 ★    │                               │                              │
                 │◄────── inbox ───────────────────┤                              │
                 │                               │                              │
  1. ACK 确认    │                               │                              │
                 │────── _inbox:server ──────────►│                              │
                 │   "ACK ✅ R115 收到"           │  ── 转发 ──────────────────►│
                 │                               │                              │
                 │   [执行任务]                   │                              │
                 │                               │                              │
  2. 完成通知    │                               │                              │
                 │────── _inbox:server ──────────►│                              │
                 │   "已完成 ✅ R115 Step N       │  ① 提取 ##key=value          │
                 │    ##key1=val1##key2=val2"     │  ② 写入 ctx.artifacts        │
                 │                               │  ③ 推进管线 Step             │
                 │                               │  ④ 派活下一步                │
                 │                               │  ── 转发 ──────────────────►│
                 │◄── 自动确认 ──────────────────┤                              │
                 │   "✅ 确认，本轮任务完成."      │                              │
```

---

## 九、边界与约定

### 9.1 前缀精确匹配

| 格式 | 是否匹配 | 原因 |
|:-----|:--------:|:------|
| `ACK ✅ R115 收到` | ✅ | `startswith("ACK ✅")` |
| `好的，收到` | ❌ | 无前缀 |
| `已完成 ✅` | ✅ | `startswith("已完成 ✅")` |
| `✅ 完成` | ✅ | `startswith("✅ 完成")` |
| `✅ 已推 dev` | ❌ | 不是 `✅ 完成` 开头 |
| `##start##R115` | ✅ | `startswith("##")` |
| `##help` | ✅ | `startswith("##")` |

### 9.2 消息长度限制

| 限制 | 值 |
|:-----|:--:|
| 单消息 content 最大长度 | 无硬限制（建议 < 4KB） |
| `##key=value` 段数量 | 无限制（建议 ≤ 8 段） |
| 单 value 最大长度 | 无硬限制（建议 < 1KB） |

### 9.3 Value 编码约定

| 字符 | 处理方式 |
|:-----|:---------|
| `=` | 安全（仅第一个 `=` 作为 key-value 分隔） |
| `##` | **禁止出现**于 value 中，会被误分割 → 用 `%23%23` |
| `#` | 安全（单个 `#` 不被 `##` 匹配器识别） |
| 中文/Unicode | 安全 |
| 空格 | 安全 |

### 9.4 ACK 格式统一

所有 bot 的 ACK 确认消息统一格式：

```
ACK ✅ R{round} 收到
```

示例：

```
ACK ✅ R115 收到
```

---

## 十、快速参考

### 10.1 Bot 视角速查

```
收到消息 → 检查 channel 是否 _inbox: 开头
  ✔ 是 → 这是发给我的
    → 回复到 _inbox:server
      → ACK: "ACK ✅ R{N} 收到"
      → 完成: "已完成 ✅ R{N} Step N##key=val"

  ❌ 否 → 非 inbox 消息，忽略
```

### 10.2 Server 路由优先级速查

```
content.startswith("##")        → _handle_hash_cmd    # 管线命令
content.startswith("test ✅")    → 回路测试              # R96
content.startswith(ACK/收到)    → 转发 PM               # R87
content.startswith(已完成/✅)    → 转发 + 注入 + 推进     # R87/R115
content.startswith("退回 🔄")    → 转发 PM               # R87
content.startswith("失败 ❌")    → 转发 PM               # R87
content.startswith("!")         → _admin               # R82
to_agent 顶层字段存在           → 中继转发到目标         # R102
PM 发送者且无上述匹配           → 拒绝 + 提示            # R87
```

### 10.3 所有 `##` key 一览

| 场景 | Step | 发送者 | `##` keys |
|:-----|:----:|:-------|:----------|
| 创建管线 | — | PM | `round_title`, `requirements_url` |
| 工作计划 | 1 | PM | `work_plan_url` |
| 技术方案 | 2 | 小开 | `tech_plan_url`, `design_decision` |
| 编码实现 | 3 | 爱泰 | `commit_sha`, `files_changed`, `commit_description`, `branch_name` |
| 代码审查 | 4 | 小周 | `review_report_url`, `review_decision` |
| 测试验证 | 5 | 泰虾 | `test_result`, `test_report_url`, `test_commit_sha` |
| 合并部署 | 6 | 小爱 | `merge_commit_sha`, `deploy_version` |

### 10.4 示例：完整轮次消息流

```
PM:    ##start##R115##round_title=Artifact注入
PM:    已完成 ✅ R115 Step 1##work_plan_url=...
小开:  已完成 ✅ R115 Step 2##tech_plan_url=...##design_decision=...
爱泰:  已完成 ✅ R115 Step 3##commit_sha=...##files_changed=...
小周:  已完成 ✅ R115 Step 4##review_report_url=...##review_decision=通过
泰虾:  已完成 ✅ R115 Step 5##test_result=PASS##test_report_url=...
小爱:  已完成 ✅ R115 Step 6##merge_commit_sha=...##deploy_version=...
PM:    ##status##R115
```

---

## 十一、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-10 | R82-R87: Inbox 消息基本协议 |
| v2.0 | 2026-07-10 | R87: 中继通道 + 前缀路由规则 |
| v2.1 | 2026-07-14 | R111: `##` 管线命令协议 |
| v2.2 | 2026-07-14 | R114: 6 步完成消息 + `##key=value` 协议 |
| **v3.0** | **2026-07-15** | **R115: 合并三阶段 → 统一文档，新增 Artifact 注入机制 + 完整时序图 + 边界约定** |
