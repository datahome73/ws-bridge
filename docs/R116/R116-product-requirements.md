# R116 管线全自动就绪 — 协议文档更新 + Bot 重新学习

> **轮次：** R116
> **类型：** 文档 + 验证轮
> **PM：** 小谷
> **基线：** R115（`_extract_artifact_kv()` + artifacts 注入已闭环，15/15 ALL GREEN）

---

## 一、背景

R111→R115 完成了以下 auto 基础设施建设：

| 组件 | 轮次 | 功能 |
|:-----|:----:|:-----|
| `##start##R{N}##k=v` relay 协议 | R111 | PM 一条消息创建管线 + 派活 Step 1 |
| `_try_advance_pipeline()` | R113 | 自动识别 `已完成 ✅ R{N} Step {N}`，推进 Step |
| `_extract_artifact_kv()` + artifacts 注入 | R115 | 从完成消息提取 `##key=value`，注入 PipelineContext |
| `_auto_dispatch()` + `_render_template()` | R107/R115 | 自动渲染模板 + 用 L4 凭证派活下一步 |
| `AUTO_DISPATCH_ENABLED=True` | R108 | 生产配置已启用 |
| Relay 前缀规则（5 条） | R87→R115 | `收到 ✅` / `已完成 ✅` / `退回 🔄` / `失败 ❌` / `##` 命令 |

**代码层面 auto 链路已全部就绪。** 但 `docs/inbox-message-protocol.md` 仍停留在 R87 v2.0 版本，严重落后于实际协议（缺少 `##key=value`、`##start` 协议、Step 完成格式等）。各 bot 读到的仍是旧协议，无法正确理解当前通信格式。

**R116 目标：** 更新协议文档 → 通知各 bot 重新学习并确认 → 启动全自动管线验证。

---

## 二、故障分析

### 2.1 协议文档滞后清单

| # | 缺少内容 | 影响 | 对应轮次 |
|:-:|:---------|:-----|:--------:|
| 1 | `##start##R{N}##k=v` 管线创建协议 | Bot 不知道 PM 如何启动管线 | R111 |
| 2 | `已完成 ✅ R{N} Step {N}##key=value` 完成格式 | Bot 仍回 `✅ 完成` 旧格式，不触发 step 推进 + artifacts 提取 | R113/R115 |
| 3 | 8 场景 `##key` 清单（A-H） | Bot 不知道 Step 2~6 各自的 `##key` 必填字段 | R114 |
| 4 | `##status` / `##stop` / `##help` 命令 | Bot 不知道如何查询管线状态 | R111 |
| 5 | `_inbox:server` + `to_agent` 派活路由 | Bot 不知道 PM 通过 server 中转派活 | R102 |
| 6 | 残留「AutoRouter 服务模型」章节 | 误导（AutoRouter 已被 relay 协议替代） | R88→R111 |

### 2.2 Bot 学习空白

各 bot 当前对 `##key=value` 协议一无所知——它们的系统提示词或参考文档中没有定义 Step 完成时应该嵌入哪些上下文信息。导致：

- Step 3（爱泰）完成时不知道要带 `commit_sha=` / `files_changed=` / `branch_name=`
- Step 4（小周）完成时不知道要带 `review_report_url=` / `review_decision=`
- Step 5（泰虾）完成时不知道要带 `test_result=` / `test_report_url=`
- 即使 server 端已能解析 `##key=value`，bot 不发送则 artifacts 永远为空

---

## 三、需求方案

### 方向 A：协议文档重写（核心产出）

**产出文件：** `docs/inbox-message-protocol.md` → **v3.0**

**改动范围：**

#### A.1 废除 / 删除

| 章节 | 原因 |
|:-----|:------|
| §8.8 AutoRouter 服务模型 | AutoRouter 已被 Relay Prefix Protocol 取代（R111 决定），不再是实际架构 |
| §8.6 前缀规则中 `✅ 完成` 格式 | 更新为 `已完成 ✅ R{N} Step {N}##key=value` 格式 |
| §6 Gateway 整合示例 | 各 bot 已独立部署，无需此章节 |

#### A.2 新增 / 重写

| 章节 | 内容 | 来源 |
|:-----|:------|:-----|
| **§B: Relay Prefix Protocol** | `##start##R{N}##k=v`、`##status##R{N}`、`##stop##R{N}`、`##help` 四个命令的格式和使用说明 | R111 协议 |
| **§C: Step 完成协议** | `已完成 ✅ R{N} Step {N}##key=value` 格式详解，包括 split 规则、key 命名规范、value 约束 | R113/R114/R115 |
| **§D: 8 场景 `##key` 清单** | 场景 A~H 完整表格，每场景的前缀、发送者、必填/可选 keys、示例消息 | R114 skill（`inbox-communication-protocol` v1.1） |
| **§E: R114 Dev 上下文注入** | 8 项必填字段（tech_plan_url/requirements_url/scope_files/base_branch/design_decision/api_contract/data_model_change/test_scope） | R114 协议 |
| **§F: Step 6 部署 SOP** | 7 字段交接协议（branch/commit_sha/image_tag/test_summary/test_report_url/deploy_ports/health_check_path） | R115 |
| **§G: Bot 通信 Checklist** | 每 bot 处理 inbox 的 8 步 SOP，含 `##key=value` 嵌入要求 | 全流程经验 |

#### A.3 保留并更新

| 章节 | 更新内容 |
|:-----|:---------|
| §2 消息结构 | 补充 `to_agent` 字段说明 |
| §4 回复协议 | 从 `✅ 完成` 更新为 `已完成 ✅ R{N} Step {N}` |
| §8 Bot 标准流程 | 按新协议重写通信全景图，加入 `##key=value` 步骤 |
| §8.6 前缀规则 | 增加 `已完成 ✅`、`##` 两条规则 |

### 方向 B：通知各 bot 重新学习

PM 向每个 bot 的 inbox 发送学习任务，要求：

| Step | Bot | 任务 |
|:----:|:----|:-----|
| B.1 | 小开（arch） | 阅读 v3.0 协议，关注 Step 2 `##key=value`（`tech_plan_url`, `design_decision`） |
| B.2 | 爱泰（dev） | 阅读 v3.0 协议，关注 Step 3 `##key`（`commit_sha`, `files_changed`, `branch_name`） |
| B.3 | 小周（review） | 阅读 v3.0 协议，关注 Step 4 `##key`（`review_report_url`, `review_decision`） + QA 附加字段 |
| B.4 | 泰虾（qa） | 阅读 v3.0 协议，关注 Step 5 `##key`（`test_result`, `test_report_url`） |
| B.5 | 小爱（ops） | 阅读 v3.0 协议，关注 Step 6 `##key` + 部署 SOP（`merge_commit_sha`, `deploy_version`） |

**确认方式：** 每个 bot 回复 `已完成 ✅ R116 学习 {角色名}` 到 `_inbox:server`。

**超时处理：** 24h 内未回复的 bot，PM 记录后后续手动补发协议概要。

### 方向 C：全自动管线验证（v3.0 定稿后）

所有 bot 确认学完新协议后，启动一轮全自动管线验证：

1. PM 发 `##start##R116-auto##round_title=全自动管线验证`
2. 预期：Server 自动创建管线 → 派活 Step 1 → PM 确认 Step 1 → 自动派活 Step 2~6
3. **全程零手动干预：** PM 不发任何手动派活消息，所有 Step 推进全靠 `_auto_dispatch()`
4. 验证点：每 step 完成自动派活下一步、artifacts 正确注入、模板正确渲染

---

## 四、不修改的模块

| 模块 | 原因 |
|:-----|:------|
| `server/ws_server/main.py` | auto 链路已完整，无需编码改动 |
| `pipeline_context.py` | artifacts 持久化正常 |
| `viewer.py` | Web 数据刷新 bug 已知，不阻塞全自动 |
| `commands/pipeline.py` | 已被 relay 协议替代 |
| `config.py` | `AUTO_DISPATCH_ENABLED=True` 已启用 |

**唯一代码改动：** 无。纯文档轮（协议文档更新）。

---

## 五、验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `docs/inbox-message-protocol.md` 已更新至 v3.0 | `git log` 显示 commit，文件包含 §A~§G 章节 |
| 2 | 协议文档包含 8 场景 `##key` 清单（A~H） | 场景表完整，示例消息格式正确 |
| 3 | 协议文档包含 `##start` / `##status` / `##stop` / `##help` 命令说明 | 四个命令格式清晰 |
| 4 | 协议文档包含 R114 8 项 Dev 上下文字段 | `tech_plan_url`~`test_scope` 全部列出 |
| 5 | 协议文档包含 Step 6 部署 SOP 7 字段 | `branch`~`health_check_path` 全部列出 |
| 6 | 协议文档已删除废弃的 AutoRouter 章节 | `grep 'AutoRouter'` 不再返回 §8.8 |
| 7 | 协议文档已更新 ACK 前缀为 `收到 ✅` | 不再引用旧 `ACK ✅` 格式 |
| 8 | 各 bot 已收到学习通知 | inbox 发送记录可查 |
| 9 | 各 bot 回复学习确认 | `_inbox:server` 收到 `已完成 ✅ R116 学习 {角色}` |
| 10 | 全自动管线成功运行 | `##start##R116-auto` → 自动完成 Step 1~6，无需手动派活 |

---

## 六、涉及文件

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `docs/inbox-message-protocol.md` | **全文重写 ~500 行** | v2.0 → v3.0，废除 AutoRouter，新增 §B~§G |
| `skills/software-development/inbox-communication-protocol/SKILL.md` | 同步更新 | Hermes skill 与 repo 协议文档保持一致 |
| （其他） | 0 | 纯文档轮，无代码改动 |

---

## 七、风险与注意事项

- **协议文档与 Hermes skill 双源同步：** `docs/inbox-message-protocol.md` 是 bot 可访问的文档（GitHub raw URL），`inbox-communication-protocol` 技能是 PM（我）的参考。两者必须保持同步。方案：以 repo 文档为真相源，skill 从中同步
- **Bot 学习确认可能超时：** 各 bot 的可用性不同，可能有 bot 在 session reset 窗口或不在线。超时后 PM 应发一批次补发协议概要，不需要等全部学完再验证
- **全自动管线验证不涉及生产数据：** 创建 `R116-auto` 管线用于验证即可，完成后自动归档或删除，不干扰真实轮次
- **Web 仪表盘刷新问题已知：** viewer.py 的缓存不刷新的问题在 R114 已分析但未修复。不影响自动派活流程（派活走 WS 消息路径，不依赖 Web 端）。全自动验证时通过 `##status` 而非 Web 端确认管线状态

---

## 八、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-07-14 | R116 初稿 |
