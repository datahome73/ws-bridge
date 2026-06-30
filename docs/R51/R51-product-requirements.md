# R51 产品需求 — 管线 step 交接完善 + 全流程验证

> **版本：** v0.2 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-29
> **本轮改动范围：** 仅第①类（服务器代码，`server/handler.py` 中 1 行变更）

---

## 0. 问题背景

R50 已成功部署了自动管线全流程（方向 A：自动 MSG_SET_ACTIVE_CHANNEL + 方向 B：`!pipeline_activate` / `!step_handoff` 过渡命令），且 Agent Card 角色查找机制已编码到位。但以下两个断点仍阻碍管线在全自动化模式下顺畅运转：

| # | 问题 | 类型 | 严重度 |
|:-:|:-----|:----|:------:|
| 1 | **`!step_complete` 对 step 名大小写敏感** — 用户输入 `Step4`（大写 S），但 Task 名和 Step 映射表都是小写 `step4`，精确匹配失败，返回「❌ 未找到 Step「Step4」的活跃 Task」 | 代码缺陷 | 🔴 P0 |
| 2 | **管线全流程未被生产环境实战验证** — R50 的所有改进（方向 A + 方向 B + Agent Card 机制）虽然在代码审查和单元测试中通过，但未经过完整的端到端管线实战 | 验证空白 | 🔴 P0 |

两个问题解耦且独立：#1 是纯代码修复，#2 是纯执行验证。

---

## 1. 需求描述

### 需求 A：`!step_complete` 大小写不敏感（修复代码缺陷）

**当前行为：**

`_cmd_step_complete()` 在第 1396 行直接取用户输入的 step 名：
```python
step_name = positional[0]
```
后续（行 1422、1440）用精确 `==` 与 Task 名和 Step 映射表 key 比较。而 Task 名在 `!pipeline_start` 创建时由配置传入小写值（如 `step2`），Step 映射表 key 也是小写（`step1`~`step6`）。

如果用户输入 `!step_complete Step4`（大写 S），两个比较都失败：
- 行 1422：`t.get("name") == "Step4"` → `"step4" == "Step4"` → False
- 行 1440：`k == "Step4"` → `"step4" == "Step4"` → False

**期望行为：**

管线内各角色在输入 `!step_complete` 时应不区分大小写。`Step4`、`step4`、`STEP4` 等写法应全部正常工作。

**修复方案：**

在 `handler.py` 第 1396 行加 `.lower()` 归一化：
```python
# 当前：
step_name = positional[0]
# 改为：
step_name = positional[0].lower()
```

这一处修改同时修复行 1422（Task 名比较）和行 1440（Step 映射表 key 比较）两个断点，改动量 **1 行**。

> **影响范围：** `!step_complete` 命令的 `step_name` 参数将不再区分大小写。现有管线中已存储的 Task 名均为小写，不受影响。向后兼容 ✅

### 需求 B：管线全流程端到端验证（实战执行）

在生产环境中用一次完整的管线启动 → 逐 Step 流转 → 合并部署来验证所有改进是否真实生效。分两个 Sub-Phase：

#### Phase V-R50：R50 改进实战验证

使用 `!pipeline_start R51 --from step2` 启动管线，逐一验证：

| V-# | 验证项 | 预期结果 |
|:---:|:-------|:---------|
| V-1 | `!pipeline_start R51 --from step2` 在 `_admin` 频道触发 | ✅ 工作室创建 + 点名全员 |
| V-2 | 点名后活跃频道自动切换（方向 A） | ✅ 各成员活跃频道变为 `ws:R51-dev` |
| V-3 | `!step_complete Step2 --output <sha>` 不区分大小写 | ✅ 匹配成功，点名 arch→dev |
| V-4 | `!step_complete Step3 --output <sha>` 后自动点名 review | ✅ dev→review 交接 |
| V-5 | Step 3 → 4 交接时活跃频道自动切换 | ✅ 审查者的频道自动切到工作室 |
| V-6 | `!step_complete Step6` 管线正常关闭 | ✅ 工作室关闭 + 大厅恢复 |

#### Phase V-R50a：Agent Card 管线角色验证

| V-# | 验证项 | 预期结果 |
|:---:|:-------|:---------|
| V-7 | Agent Card 中 `pipeline_roles` 字段已正确设置 | ✅ 各角色都有对应 roles |
| V-8 | `!pipeline_start` 通过 Agent Card 收集成员 | ✅ 工作室成员包含 arch/dev/review/qa/admin |
| V-9 | `!step_complete` 通过 Agent Card 查找下一角色成员 | ✅ 能找到对应角色的 agent |

---

## 2. 验收标准

### 需求 A：`!step_complete` 大小写不敏感

| A-# | 验收标准 | 优先级 |
|:---:|:---------|:------:|
| A-1 | `!step_complete Step2 --output [sha]` 在工作室中执行 → ✅ 匹配成功，推进到下一 Step | 🔴 P0 |
| A-2 | `!step_complete step2 --output [sha]`（全小写）同样有效，不回归 | 🔴 P0 |
| A-3 | `!step_complete STEP2 --output [sha]`（全大写）同样有效，不回归 | 🔴 P0 |
| A-4 | 现有小写 Task 名（`step4`）在升级后不丢失，可正常完成 | 🔴 P0 |
| A-5 | `!step_complete` 不传参数时返回友好错误消息（不变） | 🟢 P3 |

### 需求 B：管线全流程端到端验证

| B-# | 验收标准 | 优先级 |
|:---:|:---------|:------:|
| B-1 | V-1~V-6 全部通过（管线全流程通畅） | 🔴 P0 |
| B-2 | 管线 Step 交接时下一角色活跃频道自动切换 | 🔴 P0 |
| B-3 | 管线完成后工作室关闭 + 大厅恢复接收 | 🟡 P1 |

---

## 3. 不纳入本次需求

| 项目 | 原因 |
|:-----|:------|
| Agent Card 角色数据结构调整 | 当前结构已满足管线需求，无需修改 |
| 超时机制配置优化 | 独立性事项，不阻塞管线验证 |
| Gateway event loop 稳定性排查 | 与本次管线验证的目标无关 |
| Dev 分支 force-push 防护 | 仓库设置层面的操作，非代码变更 |
| 任何其他 R50 未完成的扩展方向 | R51 是轻量验证轮，不接新功能方向 |

---

## 4. 风险与依赖

| 风险 | 概率 | 影响 | 缓解 |
|:-----|:----:|:----:|:------|
| 生产环境 Agent Card `pipeline_roles` 未配置 | 低 | 🔴 管线无法自动点名 | Phase V-R50a 先验证，未配置则在工作室中通过 `!agent_card set` 补齐 |
| `!step_complete` 代码路径有其他未发现的 bug | 低 | 🟡 某 Step 卡住 | Phase V 逐 Step 验证，发现立即就地修复 |
| 管线超时机制在 Step 间隔过长时自动清空状态 | 中 | 🟡 需重新启动 | 控制 Step 间隔在超时阈值内，逐 Step 推进不休息 |
