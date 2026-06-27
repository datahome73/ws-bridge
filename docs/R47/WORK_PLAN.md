# R47 工作计划 — 进度 Tab 内容修复

- **轮次：** R47
- **类型：** Bug 修复（F-14） + 通知补全
- **日期：** 2026-06-27
- **文档作者：** 需求分析师（PM）

---

## 阶段总览

| 阶段 | 内容 | 负责人 | 预计 |
|:-----|:------|:-------|:-----|
| **Phase 1** | 代码修改 | arch（架构师）+ dev（开发工程师） | 30min |
| **Phase 2** | 编码审查 + 合并 main + 部署 | review（审查工程师）+ admin（超级管理员） | 15min |
| **Phase 3** | 触发管线 + 验证 | PM（需求分析师） | 20min |

---

## Phase 1 — 代码修改（架构师/开发工程师）

### Step 1：修复 F-14 — `get_tasks_by_context` → `list_tasks_by_context`

**文件：** `handler.py`

**状态：** ✅ 已完成 — 由 需求分析师 在 `8a64665` 修复
- `_cmd_step_complete` L1210: `get_tasks_by_context` → `list_tasks_by_context`
- `_cmd_pipeline_status` L1318: `get_tasks_by_context` → `list_tasks_by_context`

### Step 2：追加通知调用

**文件：** `handler.py`

**状态：** ✅ 已完成 — 通知链已通过 `_broadcast_task_notify` 自动运转
- `_cmd_task_create()` (L649) 内已有 `asyncio.create_task(_broadcast_task_notify(...))` → 由 `_cmd_pipeline_start` 调用 ✓
- `_cmd_task_update()` (L698) 内已有 `asyncio.create_task(_broadcast_task_notify(...))` → 由 `_cmd_step_complete` 调用 ✓
- `_broadcast_task_notify()` (L1486-1497) 向 `_admin` 频道写入 `📊` 消息 ✓
- F-14 修复后 `!pipeline_status` 也能正确返回任务清单 ✓

### Step 3：关闭清理 — A4

**文件：** `handler.py`

**状态：** ✅ 已完成 — 在 `_cmd_step_complete` 最终 Step 路径中插入 `📊` 完成通知到 `_admin`
- `_cmd_step_complete` (L1242-1253): 新增 cleanup_msg 保存到 `_admin` 频道
- 通知内容：`📊 {round_name} 管线已完成 ✅ 所有 Step 已完结，工作室已关闭`
- 验证：A4 满足 — 最后 Step 完成后 `_admin` 频道收到 `📊` 完成通知

---

## Phase 2 — 编码审查 + PR + 部署（review / admin）

### Step 4：审查

确认：
- [ ] 所有 `get_tasks_by_context` 调用全部修正
- [ ] `pipeline_start` 中有 `_task_notify_workspace` 调用
- [ ] `step_complete` 中有 `_task_notify_workspace` 调用
- [ ] workspace_close 或 final step 有进度清理
- [ ] 不引入新的未引用导入或死代码

### Step 5：PR → 合并 main

```bash
cd /tmp/ws-bridge-r47
git add -A
git commit -m "R47 fix: F-14 function name + task notification chain"
git push origin dev
# 创建 PR dev → main，合并
```

### Step 6：部署

通知 admin 重新部署生产容器（`docker compose restart ws-bridge` 或 `docker compose up -d --build`）。

---

## Phase 3 — 管线触发 + 验证（PM）

### Step 7：创建管线

向 `_admin` 频道发送：
```
!pipeline_start R47
```

### Step 8：验证

| 验证项 | 预期 | 实际 |
|:-------|:-----|:-----|
| `📊` 初始消息 | 创建管线后在 `_admin` 可见 | |
| `!pipeline_status` | 返回当前 Step 的任务清单 | |
| `!step_complete` 后 | `📊` 消息更新 Step 状态 | |
| 工作室关闭 | `📊` 标记为已关闭 | |

### Step 9：收尾

所有验证通过后：
- [ ] 更新 `docs/TODO.md` 标记 F-14 为 🟢
- [ ] 更新 R47 文档状态
- [ ] 将 R47 文档推送到 dev

---

## 回退方案

本轮回滚极其简单：仅 `handler.py` 修改，从 git revert 然后重新部署即可。生产环境不受数据完整性问题影响。
