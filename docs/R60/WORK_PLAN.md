# R60 工作计划 — 系统消息中 agent ID → 角色名/ bot 名 显示

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** 📋 定稿待管线启动
> **项目协调人：** 🧐 PM
> **日期：** 2026-06-30
> **基于需求文档：** `docs/R60/R60-product-requirements.md` v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 改动极小，严禁 scope creep

R60 只做 **一件事**：替换系统消息中的 agent ID 为可读名称。

- **不改入：** `_cmd_pipeline_status`、`_cmd_create_workspace`、Web 端渲染、`logger.info` 日志
- **不改出：** 不引入新配置、新命令、新 API 字段
- 编码者超出 scope 的改动，审查者直接打回

### 0.2 主备映射（本轮）

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案的人 ≠ 编码的人 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

### 0.3 Step 交接不回声

Step 交接系统消息仅被 @mention 的目标 bot 回复 ACK。其他角色零输出。

---

## 1. 管线总览

```
🔶 前置决策区（已完成 ✅）
  Step A  需求文档 ✅（项目负责人 审核通过）
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

仅 `server/handler.py`，**1 个工具函数 + 5 处替换**：

| 方向 | 改动 | 位置 | 估算 |
|:----:|:----|:----|:----:|
| A+B | 提取 `_get_agent_display()` + 替换 5 处 agent_id[:N] | `_handle_auth` + `_send_to_agent` + `_notify_member_changed` | ~12 行新增 + ~5 行修改 |
| C | 可选：agent Card display_name 检查（零代码） | — | 0 行 |

**总估算：** ~17 行净改（含工具函数）

---

## 2. 管线步骤

### Step 1：管线启动（服务端自动）

| 项目 | 说明 |
|:-----|:------|
| **触发** | PM 在 `_admin` 频道执行 `!pipeline_start R60 --mode auto` |
| **执行者** | 🤖 服务端自动 |
| **操作** | ① 暂停大厅接收 ② 建工作室 `ws:R60-dev` ③ `MSG_SET_ACTIVE_CHANNEL` 切换到工作室 ④ 点名全员 ⑤ 点名架构师附上下文 |
| **产出** | 管线状态 📊 + 工作室就绪 |

> **验证：** 触发后立即 `!pipeline_status` 确认 Step 指针在 step2

### Step 2：技术方案

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🏗️ arch-bot |
| **备用** | dev-bot |
| **产出** | `docs/R60/R60-tech-plan.md` |
| **内容** | 方向 A（5 处 agent_id 替换）的精确行号改动方案 + 测试策略 + `_get_agent_display()` 工具函数签名设计 |
| **完成** | ✅ 推 dev + 工作室 QA 讨论通过 |

**架构师须知：**
- `_get_agent_display()` 工具函数：负责从 `display_name` > `name` > `role` > `agent_id[:12]` 优先级查找
- 5 处替换位置（R59 代码基线）：

  | # | 行号 | 当前代码 | 替换目标 |
  |:-:|:----:|:---------|:---------|
  | 1 | L205 | `{agent_id[:16]}` → `{_get_agent_display(agent_id)}` |
  | 2 | L210 | `{agent_id[:16]}` → `{_get_agent_display(agent_id)}` |
  | 3 | L1803 | `@{agent_id[:12]}` → `@{_get_agent_display(agent_id)}` |
  | 4 | L1820 | `@{agent_id[:12]}` → `@{_get_agent_display(agent_id)}` |
  | 5 | L3399 | `member_id[:12]` → `_get_agent_display(member_id)` |
- `_load_agent_cards()` 已在模块中定义，直接调用即可
- 注意 `auth.get_users()` 是全量读——技术方案决定是否需要缓存（5s TTL）或直接调用

### Step 3：编码

| 项目 | 说明 |
|:-----|:------|
| **主角** | 💻 dev-bot |
| **备用** | arch-bot |
| **产出** | commit SHA + `R60_test.py`（≥20 断言） |
| **约束** | 编码者 ≠ 方案编写人 ✅ |
| **完成** | ✅ commit 推 dev |

**编码者须知：**
1. 提取 `_get_agent_display(agent_id)` 工具函数，放在 handler.py 中 `_load_agent_cards()` 附近
2. 替换 L205、L210、L1803、L1820、L3399 的 agent_id[:N] 引用
3. 编写 `tests/R60_test.py`：≥20 个断言，覆盖工具函数 4 条优先级路径 + 5 处替换读风
4. 现有 R57 + R58 测试不受影响
5. 提交前自检：`grep -n 'agent_id\[\|member_id\[' server/handler.py` 确认仅剩合法引用（logger.info / 注册通道等）

### Step 4：代码审查

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🔍 review-bot |
| **备用** | qa-bot |
| **产出** | `docs/R60/R60-code-review.md` |
| **检查重点** | ① 5 处替换是否彻底（grep 残留验证）② `_get_agent_display()` 优先级链正确 ③ 编码者没有超出 scope ④ `auth.get_users()` 调用频率合理 ⑤ 没有新配置/新命令引入 ⑥ PM 先做 diff 质量门 |
| **完成** | ✅ commit 推 dev |

### Step 5：测试验证

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🦐 qa-bot |
| **备用** | review-bot |
| **产出** | `docs/R60/R60-test-report.md` |
| **完成** | ✅ commit 推 dev |

#### 验收清单（直接引用需求文档）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | `_admin` 注册通知显示 bot 名而非 agent ID | ⏳ |
| ✅-2 | `_notify_member_changed` 显示角色/名 | ⏳ |
| ✅-3 | 工具函数 `_get_agent_display()` 优先级正确 | ⏳ |
| ✅-4 | 现有 `_cmd_pipeline_status` 成员显示不受影响 | ⏳ |
| ✅-5 | 100% 回归——R58 测试 + R57 测试全部通过 | ⏳ |
| ✅-6 | shell/grep 验证零残留 agent ID 在系统消息中 | ⏳ |

### Step 6：合并部署归档

| 项目 | 说明 |
|:-----|:------|
| **主角** | 🦸 admin-bot |
| **备用** | arch-bot |
| **操作** | ① 合并 dev→main ② 部署生产容器 ③ 健康检查 ④ `!pipeline_status` 确认新代码运行 ⑤ 更新 TODO.md ⑥ 关闭工作室 ⑦ 恢复大厅接收 |
| **产出** | merge commit SHA |
| **完成** | ✅ 归档 — 所有文档推 dev，记忆更新，skill 更新 |

---

## 3. 关键设计决策摘要

| # | 决策 | 来源 |
|:-:|:-----|:------|
| D1 | `_get_agent_display()` 采用 4 级优先级：display_name > name > role > id[:12] | 需求文档 §1 |
| D2 | 不引入缓存——`auth.get_users()` 在当前环境下已经是内存操作，5s TTL 不必要 | PM 预判 |
| D3 | 范围严控：只改 5 处 agent_id[:N] → `_get_agent_display()`，不改其他系统消息 | 项目负责人长期约束 |
| D4 | 行号基准以 R59 代码基线（origin/dev）为准 | 当前基线 |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:-----|
| v1.0 | 2026-06-30 | R60 工作计划定稿 — 6 步管线 + 5 处替换 + 验收清单 |
