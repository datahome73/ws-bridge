# R48 产品需求文档 — 管线通用化 + 完成通知闭环

> **版本：** v0.2 ✅（项目负责人 Q&A 收敛）
> **状态：** ✅ 已审核（项目负责人确认）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-28
> **本轮改动范围：** 仅第①类（服务器代码 —— `server/handler.py` + `server/config.py`）

---

## 1. 问题背景

R47 完成并关闭工作室后，复盘发现两个核心短板：

### 1.1 管线只能为 ws-bridge 自身服务

当前 `!pipeline_start` 的 WORK_PLAN 检查路径和上下文 URL 全部硬编码为 `docs/{round_name}/WORK_PLAN.md`。即使 R45 引入了 `WORK_PLAN_REPO_URL` 环境变量，其路径组合逻辑仍然死死绑定 ws-bridge 的 Round 命名体系：

```python
_remote_url = f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/WORK_PLAN.md"
context_urls = f"需求: docs/{round_name}/... | WORK_PLAN: docs/{round_name}/..."
```

这意味着管线无法用于**非 ws-bridge 的通用开发项目**。比如清迈房产项目（同在 GitHub 仓库中），它的 WORK_PLAN 不会在 `docs/` 目录下，Round 命名也不适用。整个管线基础设施被锁定在了 ws-bridge 自身的开发流程中。

### 1.2 管线完成后无人通知项目负责人

Step 6（合并部署归档）执行完毕后，服务端确实在工作室内返回了 `🏁 R{N} 管线已完成！` 的确认消息，也向 `_admin` 频道写入了清理消息。但**没有人主动在 Telegram 私聊回复项目负责人**：

- admin-bot（可执行此命令的角色）执行完 `!step_complete Step6` 后，只获得了服务端响应文本
- 没有后续通知链路把「管线已完成」这个结论反馈到项目负责人
- 项目负责人无法准确知道开发任务是否已完结，需要自己去查

> **「有始有终」是基本原则。** 谁触发的管线，谁负责在结束后通知项目负责人。

---

## 2. 需求范围

| 方向 | 问题 | 解决方案 | 代码类型 |
|:----:|:-----|:---------|:--------:|
| **A** | WORK_PLAN URL 写死 | `!pipeline_start` 新增 `--work-plan-url` 参数，PM 作为输入项填入 | ① 服务器 |
| **B** | 管线完成后无 TG 通知 | Step 6 完成时，服务端记录触发者并发送完结通知，PM 收到后 TG DM 项目负责人 | ① 服务器 |

---

## 3. 用户体验

### 3.1 方向 A：通用化 Work Plan URL

**当前（R47）：**

```
!pipeline_start R48 --from step2
```

PM 必须先确保 `docs/R48/WORK_PLAN.md` 存在且 URL 正确。只适用于 ws-bridge 自身的 Round 流程。

**期望（R48）：**

PM 触发管线时，将 WORK_PLAN 的可读文档 URL 作为**输入参数**传递：

```
!pipeline_start 清迈房产 --work-plan-url https://raw.githubusercontent.com/.../WORK_PLAN.md --from step2
```

- `--work-plan-url` 可以是 GitHub raw URL、GitLab raw URL、或任何可读的文档 URL
- 当提供了 `--work-plan-url`，管线直接用该 URL 验证 WORK_PLAN 存在性（发 HEAD 请求），不再拼接 `docs/{round_name}/WORK_PLAN.md`
- 该 URL 被存入管线状态，Step 2（技术方案）点名时作为上下文传递给架构师
- 当未提供 `--work-plan-url`，回退到现有行为（使用 `config.WORK_PLAN_REPO_URL`）+ round_name 拼接 —— 完全向后兼容

**体验流程（PM 视角）：**

```
Step A · 项目负责人审核  ✅
Step B · WORK_PLAN 审核  ✅
  ↓
PM 准备启动管线，在 _admin 频道触发：

!pipeline_start chiangmai-estate --work-plan-url https://raw.githubusercontent.com/.../WORK_PLAN.md --from step2

  ↓
服务端验证：远程 URL 可达 → 通过
创建工作室「chiangmai-estate-dev」
点名架构师，上下文附带 WORK_PLAN 链接
```

如果 PM 没有传 `--work-plan-url`（即 ws-bridge 自身 Round），现有流程不变：

```
!pipeline_start R48 --from step2
→ 走 config.WORK_PLAN_REPO_URL + docs/ROUND_NAME/WORK_PLAN.md 验证
→ 点名架构师，上下文附带硬编码 URL
```

### 3.2 方向 B：TG 私聊通知管线完成

**当前（R47）：**

Step 6 完成后，服务端仅返回文本到工作室，同时写入 `_admin` 频道。无后续通知，项目负责人不知道任务完结。

**期望（R48）：**

1. `_cmd_pipeline_start` 记录触发者（sender_id）到管线状态：`triggerer_agent_id`
2. Step 6 完成（最后一步 → 管线结束）时，服务端向 `_admin` 频道写入一条**特殊格式的完结通知消息**
3. 该消息包含：
   - 管线名称
   - 最终产出（commit SHA / 文档链接）
   - 专属标记：`🔔 [PIPELINE_COMPLETE]`
4. PM 通过 `_admin` 频道收到消息后，主动在 TG DM 回复项目负责人：

```
🔔 R48 管线已完成！✅

工作室已关闭，大厅已恢复接收
最终产出：commit abc1234

下一轮开发可以提需求了。
```

**体验流程：**

```
!step_complete Step6 --output merge:abc1234
  ↓
服务端校验 → 最后一步 →
  ├ 关闭工作室
  ├ 恢复大厅
  ├ 清理管线状态
  ├ 向 _admin 频道写入：
  │   🔔 [PIPELINE_COMPLETE] R48 — 所有 Step 已完结
  │   最终产出: merge:abc1234
  │   工作室已关闭，大厅已恢复
  └ 返回 🏁 管线完成
       ↓
PM 在 _admin 频道看到 🔔 消息
       ↓
PM 在 TG DM 回复项目负责人：「R48 已完成，产出 abc1234」
```

> 这是**半自动**设计：服务端生成完结事件，PM 负责最终 TG 通知。
> 纯自动化（服务端直连 TG API）不在本轮范围内，因为：
> a) 服务端没有 TG 凭据，也不应持有
> b) PM 作为人类角色，看到通知后回复一句「已完成」本身是职责闭环的有意义环节
> c) 未来可以扩展 PM agent 自动回复，但本轮先解决「有通知」的问题

---

## 4. 验收标准

### 方向 A：通用化 Work Plan URL

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | `!pipeline_start projectX --work-plan-url <URL> --from step2` 能用给定的 URL 验证 WORK_PLAN 存在性，不检查本地路径 | 🔴 P0 |
| A-2 | 未传 `--work-plan-url` 时，走默认的 `config.WORK_PLAN_REPO_URL` + round_name 拼接逻辑，现有行为不变 | 🔴 P0 |
| A-3 | `--work-plan-url` 传入的 URL 在点名 Step 2（技术方案）时，作为上下文传递给架构师（代替硬编码的 `docs/{round_name}/WORK_PLAN.md`） | 🟡 P1 |
| A-4 | `--work-plan-url` 传入的 URL 被存入管线状态（`_PIPELINE_STATE`），后续 Step 可随时读取 | 🟡 P1 |
| A-5 | 如果 `--work-plan-url` 的 HEAD 请求失败（404/超时），返回明确的错误提示「❌ WORK_PLAN URL 不可达」 | 🟡 P1 |
| A-6 | `!pipeline_status` 展示信息中包含 work_plan_url（如有） | 🟢 P2 |
| A-7 | 向后兼容：现有 ws-bridge Round 的 `!pipeline_start R49 --from step2` 行为与 R47 完全一致 | 🔴 P0 |

### 方向 B：TG 私聊通知管线完成

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| B-1 | Step 6 完成时（最后一步），`_admin` 频道收到一条 `🔔 [PIPELINE_COMPLETE]` 标记的完结消息 | 🔴 P0 |
| B-2 | 完结消息包含：管线名称（如 R48）、最终产出引用（`--output` 值）、工作室已关闭信息 | 🔴 P0 |
| B-3 | `_cmd_pipeline_start` 自动记录 `triggerer_agent_id` 到管线状态 | 🟡 P1 |
| B-4 | 中间 Step 完成的 `_admin` 进度通知不变（R47 式 `📋 R{N} 进度：...`），仅最后一步变为 `🔔 [PIPELINE_COMPLETE]` | 🟡 P1 |
| B-5 | **（端到端验证）** 完整跑一轮 N 步管线到 Step 6 → 验证 `_admin` 频道确收到完结消息 → PM 在 TG DM 回复项目负责人 | 🟡 P1 |

---

## 5. 不纳入本轮需求

- **❌ 纯自动化 TG 通知**（服务端直连 Telegram API）— 不在本轮范围，PM 看到通知后手动回复项目负责人即可
- **❌ 额外增加 `--req-url` 参数** — WORK_PLAN 是入口文档，内部自然引用需求文档链接（或合二为一），不需要单独传需求文档 URL。需求文档解决「总目标 — 要完成什么任务」，工作计划解决「资源（哪些 bot 参加）+ 流转步骤」。两个文档相辅相成，策划阶段就应准备好。
- **❌ 用 Hermes send_message 工具自动通知** — 这是 PM 职责层面的闭环，不是技术自动化的范围
- **❌ round_name 改为项目名后，工作室创建逻辑的验证**（如名称合规、重名检测）— 保持现有 `create_workspace` 行为，只在 name 参数传 round_name
- **❌ 多个 work-plan 文档传递** — 只传一个主文档 URL
- **❌ 非 GitHub raw URL 的渲染/鉴权**（如 GitLab 私有仓库、Google Docs）— 假设 URL 是无需鉴权的可公开访问链接

---

## 6. 设计要点

### 6.1 方向 A 的关键变更

**核心原则：** `--work-plan-url` 在 Step 1（`!pipeline_start` 的初始化阶段）录入，存入管线状态后，后续所有 Step 都能通过 `_PIPELINE_STATE[round_name].get("work_plan_url")` 读取。Step 1 本身是服务端的自动化初始化环节（建工作室、点名、派活），不需要 bot 执行；`--work-plan-url` 在此阶段作为输入参数传入并持久化。

**`server/config.py`** — 保持 `WORK_PLAN_REPO_URL` 不变，作为默认值来源

**`server/handler.py`** — `_cmd_pipeline_start` 需要：

1. 添加 `work_plan_url = params.get("work_plan_url", "")` 解析
2. 如果传了 `work_plan_url`：
   - 验证：发 HEAD 请求到该 URL，200 → 通过，否则返回错误
   - 存入管线状态：`_PIPELINE_STATE[round_name]["work_plan_url"] = work_plan_url`
   - context 中使用该 URL 代替硬编码
3. 如果没传：走现有 `config.WORK_PLAN_REPO_URL` + round_name 拼接行为（完全不变）

**`server/handler.py`** — `_cmd_rollcall_next` 上下文需要：

- Step 2 的点名上下文传入 work_plan_url（如有）
- 格式：`WORK_PLAN: {work_plan_url}`

> **注意：** 不单独传递需求文档 URL。WORK_PLAN 是入口文档，它对内部的引用关系（如需求文档链接、角色分工、Step 定义）由策划阶段维护。架构师拿到 WORK_PLAN 后自然能读到需求文档；对于外部项目，WORK_PLAN 可能已与需求文档合二为一。

### 6.2 方向 B 的关键变更

**`server/handler.py`** — `_cmd_pipeline_start` 管线状态存储扩展：

```python
_set_pipeline_state(round_name, {
    "active": True,
    "current_step": start_step,
    "ws_id": ws_id,
    "started_at": time.time(),
    "work_plan_url": work_plan_url or None,   # 方向 A 新增
    "triggerer_id": sender_id,                 # 方向 B 新增
})
```

**`server/handler.py`** — `_cmd_step_complete` 最后一步（管线结束）分支追加：

当前（~行 1264-1269）已有向 `_admin` 频道写入 `📊 {round_name} 管线已完成 ✅` 的逻辑（`ms.save_message()` + `write_chat_log()`）。需要：

1. 扩展消息内容，加入 `🔔 [PIPELINE_COMPLETE]` 前缀
2. 加入产出引用（`--output` 参数值）
3. 加入触发者信息（`_PIPELINE_STATE[round_name].get("triggerer_id", "")`）

```python
cleanup_msg = (
    f"🔔 [PIPELINE_COMPLETE] {round_name} — 所有 Step 已完结 ✅\n"
    f"最终产出: {output_ref}\n"
    f"工作室已关闭，大厅已恢复接收"
)
```

---

## 7. 决策记录（Q&A 收敛）

> 以下 Q&A 由项目负责人在 2026-06-28 TG DM 中逐条确认。

| # | 问题 | 决策 | 体现位置 |
|:-:|:-----|:----|:---------|
| Q1 | `--work-plan-url` 在 Step 1 录入后，后续 Step 是否需要？ | ✅ **需要。** Step 1 是服务端自动化初始化（建工作室、点名、派活），`--work-plan-url` 在此阶段传入并持久化到管线状态。后续所有 Step 可通过 `_PIPELINE_STATE` 读取。 | §6.1 核心原则 |
| Q2 | 🔔 完结消息是否需要写入 `write_chat_log()`？ | ✅ **需要。** 完结消息同步写入 `write_chat_log()` 追加到 `_admin` 频道聊天日志，方便历史复盘。 | §6.2 写入路径说明 |
| Q3 | 是否额外加 `--req-url` 参数提供需求文档 URL？ | ❌ **不加。** 本轮只解决 `--work-plan-url`。WORK_PLAN 是入口文档，内部自然引用需求文档链接（或合二为一）。需求文档解决「总目标 — 任务」，工作计划解决「资源 + 流转步骤」，两者相辅相成，策划阶段就已准备好。 | §5 不纳入 + 设计原则说明 |

> 技术方案（具体实现方式）由架构师决定。
