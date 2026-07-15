# R120 QA 验证清单（QA Checklist）

> **角色：** 泰虾（QA）
> **字数：** ≤ 10 句

1. **测试类型分类：** 单元测试（pytest server/tests/）、集成测试（本地 ws 连容器验证派活）、全流程管线验证（`##start##R{N}` → Step 1→6）。
2. **自动派活核检 #1 — 消息送达：** 派活 payload 的 type 必须是 `broadcast`，channel 必须是 `_inbox:{bot_id}`，否则 bot 网关静默丢弃（R119 根因）。
3. **自动派活核检 #2 — 状态转换：** Step 状态必须从 `pending` → `in_progress` → `done`，缺任何一步都说明自动派活或推进逻辑有 bug。
4. **自动派活核检 #3 — PM 通知：** 派活成功（sent>0）和完成（advance_step）后小谷必须收到 `_inbox` 通知，否则通知通道有问题。
5. **自动派活核检 #4 — 离线重试：** 目标 bot 离线时进入重试队列（60s×5），bot 上线后自动送达，5 次耗尽不发重复通知。
6. **容器恢复核检：** 容器重启后 `_restore_pipeline_dispatches` 必需恢复 `pending`/`in_progress` 状态的 step 派活，不跳过已完成 step。
7. **验证流程：** `git fetch && git log --oneline dev -10` 读变更 → 对照需求文档逐项检查 → 有 bug 记录现场日志 → 源码修复 → 不手动绕行。
8. **报告模板：** 测试项 | 期望 | 实际 | 结论 🟢/🔴；每项独立标注，归档副本到 `docs/R{N}/R{N}-test-report.md`。
