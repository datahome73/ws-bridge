# R58 工作计划 — 系统通知→自然 @mention 触发改造 + 管线自动推进修复

> **版本：** v1.1 ✅（已归档）
> **状态：** 🏁 管线完成 ✅ — 已归档
> **项目协调人：** 🧐 PM
> **日期：** 2026-06-30
> **基于需求文档：** `docs/R58/R58-product-requirements.md` v0.1 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 通知触发新机制

> R58 引入「系统通知伪装成人」新机制。各角色在执行 `!step_complete` 时要了解：
> - `!step_complete` 不再仅依赖 `_send_to_agent`（from_name="系统"）通知下一角色
> - **新增主力路径：** 用 PM 角色身份 + 自然 @mention 格式 + 完整上下文，走工作室广播
> - 旧路径（`_send_to_agent`）保留为回退双保险（不删除）
> - 被 **PM 身份 @mention** 的目标 bot 应该像收到人类 PM 消息一样回复确认并开始工作
> - 这不是异常，是**新的正常通知方式**

### 0.2 主备映射（本轮）

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案的人 ≠ 编码的人 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | ⛔ 无备用 | 仅 admin 有部署凭证/密码 |

> **⚠️ Step 6 重要限制：** 合并部署环节**无法换人**——仅 admin-bot（小爱）拥有生产容器的 SSH/账号密码，其他角色无部署凭证。如果 Step 6 卡住（admin 不响应），PM 不走备用换人，直接 TG 通知项目负责人处理。这不会成为本轮瓶颈——目前卡点在前面的触发环节，小爱正常。

> 主备由项目协调人（PM）在本 WORK_PLAN 中指定。项目负责人审核通过。各角色按照主备规则执行，**不能自己审自己**。

### 0.3 Step 交接不回声

Step 交接系统消息仅被 @mention 的目标 bot 回复 ACK。其他角色零输出。

### 0.4 本条行为规则的确认

当管线启动后点名到你的 Step 时，回复 ACK 后读取本条规则全文，按规则执行。

---

## 1. 管线总览

```
🔶 前置决策区（已完成 ✅）
  Step A  需求文档 ✅（项目负责人审核通过，commit 4be9eff）
  Step B  工作计划 ✅（即将审核）
        ↓
🟢 自动化管线（6 步自动接力）
  Step 1  管线启动 → 建工作室+点名
  Step 2  技术方案（arch 主角 / dev 备用）
  Step 3  编码实现（dev 主角 / arch 备用）
  Step 4  代码审查（review 主角 / qa 备用）
  Step 5  测试验证（qa 主角 / review 备用）
  Step 6  合并部署归档（admin 主角 / arch 备用）
```

### 改动范围

仅第①类服务器代码（`server/handler.py`），聚焦 3 个方向：

| 方向 | 改动 | 位置 | 估算 |
|:----:|:----|:----|:----:|
| **A（P0）** | Step 交接通知 → PM 自然 @mention 格式改造 | `_cmd_step_complete` + `_persist_broadcast` 调用点 + `_cmd_pipeline_start` | ~25 行 |
| **B（P1）** | 初始点名 ACK 超时降为软检查 | `_broadcast_active_channel` 或 `_cmd_pipeline_start` 超时处理 | ~5 行 |
| **C（P2）** | `!pipeline_status` 增加通知状态跟踪 | `_cmd_step_complete` 记录点 + `_cmd_pipeline_status` | ~10 行 |

**不纳入：** F-16 Agent Card 角色映射、F-3 角色体系、多管线并行、bot 网关修改

---

## 2. 管线步骤

### Step 1：管线启动（服务端自动）

| 项目 | 说明 |
|:-----|:------|
| **触发** | PM 在 `_admin` 频道执行 `!pipeline_start R58 --from step2 --mode auto` |
| **执行者** | 🤖 服务端自动 |
| **操作** | ① 暂停大厅接收 ② 建工作室 `ws:R58-dev` ③ `MSG_SET_ACTIVE_CHANNEL` 切频道 ④ 广播 PM 身份 @mention 点名 ⑤ 点名架构师附上下文 |
| **产出** | 管线状态 📊 + 工作室就绪 |

> **验证：** 触发后立即 `!pipeline_status` 确认 Step 指针在 step2

### Step 2：技术方案

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🏗️ arch-bot |
| **备用** | dev-bot |
| **产出** | `docs/R58/R58-tech-plan.md` (commit sha) |
| **内容** | 方向 A（系统通知→自然 @mention 改造）+ 方向 B（ACK 软检查）+ 方向 C（状态跟踪）的技术方案 |
| **完成条件** | ✅ 推 dev + 工作室 QA 讨论通过 |

**架构师须知：**

1. **方向 A 核心改动点（`handler.py`）：**
   - `_cmd_step_complete` 中 Step 交接点名/通知段（当前 ~L1536-1606）
   - 主力通知路径：`from_name` 从 `"系统"` 改为 PM 名称（读取配置/环境变量）
   - 消息内容：`@{bot_name} 🚨 Step「{step}」到你了！\n\n📄 需求：{req_url}\n📋 WORK_PLAN：{plan_url}\n🔗 上一步产出：{output_ref}`
   - 发送方式：工作室广播到所有在线成员 WS（同 handle_broadcast 路径）
   - 保留 `_send_to_agent` 作为双保险回退（不删除）

2. **方向 B 改动点：**
   - `!pipeline_start` 的初始点名 ACK 超时不阻断管线
   - 超时后记录日志，继续推进

3. **方向 C 改动点：**
   - `_cmd_step_complete` 中记录各 Step 的「已通知 / 已确认 / 无响应」状态到 `pstate`
   - `_cmd_pipeline_status` 展示这些状态

3. **PM 名称来源：** 建议从配置或 `auth.get_users()` 的 PM 角色成员获取，不在代码中硬编码

4. **⚠️ 特殊注意 — arch/dev 可能不响应 even after from_name fix**
   - 项目负责人反馈：arch 和 dev 几乎每轮都需要额外的 TG 触发，可能和它们自身的 Hermes 网关配置有关
   - 如果方向 A 改造后 arch/dev 仍不响应，技术方案中需提出备用方案：
     - 方案 1：通知消息中增加特殊标记（如 `🚨` 前缀）触发 bot 工作模式
     - 方案 2：Step 交接时增加直接 WS 命令触发（绕过 bot 常规消息处理）
     - 方案 3：PM 保留手动 @mention 能力作为最终兜底
   - **这不是方向 A 失败的标志，而是已知的边缘情况**

5. **需求文档参考：** `docs/R58/R58-product-requirements.md` §2-A/B/C §1.4

### Step 3：编码

| 项目 | 说明 |
|:-----|:------|
| **主角** | 💻 dev-bot |
| **备用** | arch-bot |
| **输入** | `docs/R58/R58-tech-plan.md`（架构师方案） |
| **产出** | 方向 A + 方向 B + 方向 C 的代码提交 |
| **完成条件** | ✅ 推 dev + 附带改动文件清单 |

**开发者须知：**
- 严格按技术方案的行号和函数名编写
- `from_name` 改为 PM 名称时，注意该变量也影响 `_persist_broadcast` 和 WS 广播消息
- `_send_to_agent` 保留不动——只在主力路径上加改
- 改动前先 `git log --oneline -5` 看 dev 最新状态
- 推完跑 `!step_complete step3 --output <sha>`

### Step 4：代码审查

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🔍 review-bot |
| **备用** | qa-bot |
| **输入** | 开发者提交的代码 commit `87da8ef` |
| **产出** | `docs/R58/R58-code-review.md` |

**审查者须知：**
- 交叉验证 `_send_to_agent` 调用点未被意外删除
- 确认 `from_name` 没有硬编码为具体人名（应该从配置读取）
- 验证方向 B 的 ACK 软检查不影响 `_r57_wait_for_ack` 其他调用点
- 双向校验：系统代码改动 + 需求文档引用一致性

### Step 5：测试验证

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🦐 qa-bot |
| **备用** | review-bot |
| **输入** | 开发者提交的代码 |
| **产出** | `docs/R58/R58-test-report.md` (commit `98924ad`) ✅ |

**测试者须知：**
- 核心验收项：`from_name` 从 "系统" → PM 角色名的改动不影响现有逻辑
- 验证 A-1~A-6 验收标准（见需求文档）
- 验证 B-1~B-3 验收标准
- 验证 C-1~C-2 验收标准
- 特别检查：旧路径（`_send_to_agent`）未被删除，回退双保险完整

### Step 6：合并部署归档

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🦸 admin-bot |
| **备用** | ⛔ **无备用** — 仅 admin 有部署凭证 |
| **操作** | ① dev→main 合并 ② 构建+部署生产容器 ③ 健康检查 ④ 更新 TODO.md ⑤ 关闭工作室 |
| **产出** | 部署成功 + 管线完结 ✅ `5c102a0` |
| **卡死处理** | admin 不响应 → PM TG 通知项目负责人，不走备用换人 |

**执行者须知：**
- 先确认 `docs/R58/` 下所有文档齐全
- 再确认 TODO.md 版本号 bump + 变更记录更新
- 合并前确认代码审查+测试已通过

---

## 3. 管线步骤依赖图

```
Step 1 启动
  ↓
Step 2 技术方案（arch） ← 依赖：需求文档 v0.1
  ↓
Step 3 编码（dev）       ← 依赖：技术方案
  ↓
Step 4 代码审查（review）← 依赖：编码提交
  ↓
Step 5 测试验证（qa）    ← 依赖：编码提交
  ↓
Step 6 合并部署（admin） ← 依赖：审查+测试通过
  ↓
🏁 管线完结
```

---

## 4. 紧急联系人

| 场景 | 联系人 | 联系方式 |
|:-----|:-------|:---------|
| 技术方案阻塞 | 🏗️ arch 或 PM | 工作室 @mention |
| 编码阻塞 | 💻 dev 或 PM | 工作室 @mention |
| 管线启动卡死 | PM → 项目负责人 | TG 私聊 |
| 生产部署问题 | admin | 工作室 @mention |

---

> **版本历史：**
> - v1.0 — 初稿，基于 R58 需求文档 v0.1（项目负责人审核通过）
