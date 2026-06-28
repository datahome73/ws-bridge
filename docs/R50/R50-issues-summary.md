# R50 流程复盘 — 卡点记录（R51 输入）

> **日期：** 2026-06-28
> **文档定位：** R50 开发全流程中各环节暴露的不顺畅之处，作为 R51 拟定改进措施的输入。

---

## 总览

| # | 问题 | 类别 | 严重度 | 状态 |
|:-:|:-----|:----|:-----:|:----:|
| 1 | **Dev 分支被 force-push**，R50 文档提交（需求文档+WORK_PLAN+tech-plan）全部丢失，需重新补推 | 版本管理 | 🔴 P0 | ✅ 已修复（补推） |
| 2 | **Agent Card 角色查找失效** — `!step_complete` 的 `_find_agents_by_role` 不走 Agent Card，走的 `auth.get_users().role`，导致「工作区中未找到 role=dev/review/qa 的成员」 | 代码缺陷 | 🔴 P0 | ⬜ 待修复 |
| 3 | **Gateway event loop 冲突** — 无法通过 Gateway 向工作室发消息，`!step_complete` 等命令需要管理员在 `_admin` 频道或原始 WS 直连执行 | 基础设施 | 🟡 P2 | ⬜ 待定位 |
| 4 | **管道状态超时后自动清空** — Step 之间间隔太长导致管线超时（R49 超时机制），状态被清空，需要重新 `!pipeline_start` | 流程 | 🟡 P2 | ⬜ 待优化 |
| 5 | **点名报道=切频道仍未自动化** — 已有人在工作区但仍需手动 `!rollcall_role` + MSG_SET_ACTIVE_CHANNEL 才能激活。方向 A/B 已编码但未部署 | 代码部署 | 🔴 P0 | ⌛ 等部署 |
| 6 | **F-16 残留：成员角色全是 member** — `auth.get_users()` 中所有 bot 角色值为默认 `member`，只有 Agent Card 映射了角色。但 `!step_complete` 不读 Agent Card | 代码缺陷 | 🟡 P2 | ⬜ 待修复 |

---

## 详细分析

### 1. Force-push 导致文档丢失 🔴

**现象：** R50 的 4 个文档提交（`1f83a33` REQUIREMENTS、`4a780f1` WORK_PLAN、`269cb7f` 状态更新、`94e9edf` TODO 更新）在 dev 分支消失。`0778b48`（爱泰的方向 A 编码）直接建在 `ecf9ffd`（R49 merge）上，跳过了所有 R50 文档提交。

**影响：** docs/R50/ 目录完全消失，WORK_PLAN.md 404 导致 `!pipeline_start` 第二阶段验证失败。需要手工补推。

**根因：** 有人在 dev 分支上执行了 `git push --force`。

**修复：** 已手动补推 docs/R50/ 全部文件。

**预防：** dev 分支应禁止 force-push。

### 2. Agent Card 角色查找未集成 🔴

**现象：**
```
❌ 工作区中未找到角色为「dev」的成员
❌ 工作区中未找到角色为「review」的成员
❌ 工作区中未找到角色为「qa」的成员
```

`!pipeline_start` 创建工作室时从 Agent Card 拉人（正确），但 `!step_complete` 点名下一角色时用的是 `auth.get_users()` 的 `role` 字段来判断谁是什么角色，而不是查 Agent Card。

而 `auth.get_users()` 中所有 bot 的 role 都是 `member`——因为 Agent Card 是后来才加的功能，注册时写入的角色值仍是旧的。

**修复方向：** `_cmd_step_complete` 中的角色查找应优先使用 Agent Card，回退到 `auth.get_users().role`。

### 3. Gateway event loop 冲突 🟡

**现象：** Gateway 日志报 `no close frame received or sent` 错误。通过 Gateway 渠道向工作室发 `!` 命令不可靠。

**变通方案：** 通过原始 WebSocket 直连生产端口，在 `_admin` 频道执行 `!` 命令。

### 4. 管线超时自动清空 🟡

R49 的超时机制在 Step 之间间隔过长时会触发超时，然后自动清空管线状态。这在正常开发流程中不合适——开发中 Step 间隔可能长达数十分钟（编码时间），超时机制应该只告警不自动清空。配置项需要将超时时间放大或增加"不清除"模式。

### 5. 方向 A/B 已编码未部署 🔴

方向 B（`!pipeline_activate` / `!step_handoff`）在 `fbfd902` 提交但未部署。
方向 A（自动 MSG_SET_ACTIVE_CHANNEL）在 `0778b48` 提交但未部署。

当前生产环境没有过渡命令也没有自动切频道，靠小爱人工点名+切频道维持管线流转。

**修复方向：** 等审查+测试完成后合并 dev→main 部署。

---

## R51 候选改进方向

| 优先级 | 方向 | 解决问题 |
|:------:|:-----|:---------|
| 🔴 P0 | Agent Card 集成到 `!step_complete` 角色查找 | #2 #6 |
| 🟡 P1 | 超时配置优化（告警不自动清空或增大超时时间） | #4 |
| 🟡 P2 | Gateway event loop 稳定性排查 | #3 |
| 🟢 P3 | Dev 分支禁止 force-push（仓库设置） | #1 |
