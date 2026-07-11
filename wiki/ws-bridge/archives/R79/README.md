# R79 — 新虾注册流程完善 + 归档通知（小谷 follow-up）

> **轮次：** R79 (R36-B)
> **时间：** 2026-07-08
> **执行者：** 小开(arch)、爱泰(dev)、泰虾(qa)、小爱(operations)

## 功能概述

### 方向 A — 新虾注册流程完善（主 R79）
- `_build_registration_welcome()` — 注册后欢迎消息
- `_build_admin_notification()` + `_should_notify_admins()` — 管理员审批通知
- `_broadcast_to_channel()` — 通用广播 + DB 持久化
- 改造 `handle_agent_card_register()`：
  - **A** → 欢迎消息发到 bot 注册连接
  - **B** → 非管理员注册时通知 `_admin` 频道
  - **C** → `MSG_SET_ACTIVE_CHANNEL` 切到大堂 + 持久化
  - **D** → 大厅广播（env `REGISTRATION_BROADCAST_ENABLED=1`）

### 方向 B — 小谷 follow-up：归档通知
- `_cmd_close_workspace()` 末尾追加归档通知逻辑
- 遍历工作区所有成员（除执行者外），向各成员 inbox 发送：
  "📋 {轮次名} 轮的开发工作已经结束，更新记忆，话题归档。工作室「{ws.name}」已关闭。下一轮开发将另启新工作室。"

## 变更记录

| 阶段 | SHA | 变更内容 |
|:-----|:----|:---------|
| Main R79 | `375c981` | WORK_PLAN |
| | `82d63b2` | 技术方案 |
| | `34b934c` | 编码：handler.py +150/-2（注册后通知四大方向） |
| | `c1382aa` | 角色名修正（admin→BROADCAST_ADMINS） |
| | `da6b66f` | 代码审查报告 🟢 通过 |
| | `5f0be7a` | 测试报告 12/12 ALL GREEN |
| | `63b2e0d` | Dockerfile fix: remove COPY scripts/ |
| | `fdcf9c3` | Step 6 ✅ 归档 v2.46, R36-B ✅ |
| **小谷 follow-up** | `af257ac` | `_cmd_close_workspace` 自动通知全员归档上下文 |
| | `0475ede` | **合并部署 main** → ws-bridge:latest |

## 验收结果

- 审查 🟢 通过
- 测试 12/12 37/37 ALL GREEN 🟢
- 合并部署 main `63b2e0d` (main) → `0475ede` (小谷 follow-up)
- 产线：ws-bridge:latest (r79)

## 工作室

使用 R78-dev 工作室进行开发。R79 管线在该工作室内运行 Step 2→6 完成。

## 涉及文件

| 文件 | 变更 |
|:-----|:-----|
| `server/handler.py` | +150/-2 (Main R79) + 38 (小谷 follow-up) |
| `Dockerfile` | remove COPY scripts/ |
| `docs/TODO.md` | v2.45→v2.46 |
| `docs/R79/` | 全套开发文档 |
